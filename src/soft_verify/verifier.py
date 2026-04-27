from __future__ import annotations

import json
import multiprocessing as mp
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from time import monotonic

from .llm_client import generate_direct_rule_plan, judge_soft_checks_with_agent
from .config import llm_config
from .prompts import build_direct_rule_plan_prompt, build_soft_check_agent_prompt
from .soft_tools import get_soft_tool_definitions, run_soft_tool_call
from .workspace_inspector import extract_absolute_paths, resolve_verification_scope


# ── Data types ────────────────────────────────────────────────────────────


@dataclass
class VerificationResult:
    intent: str
    workspace: str
    agent_final_output: str
    verdict: str
    score: float
    soft_score_avg: float
    soft_error: dict[str, str] | None
    llm_checks: list[dict[str, str]]
    llm_check_results: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Public API ────────────────────────────────────────────────────────────


def generate_verification_plan(
    intent: str,
    workspace: str,
    *,
    agent_final_output: str = "",
    path_mode: str = "auto",
) -> VerificationResult:
    """Generate a verification plan: call LLM to produce llm_checks.

    All checks (including any rule_check from the LLM response) are
    converted to llm_checks for soft-only verification.
    """
    scope = resolve_verification_scope(intent, workspace, path_mode=path_mode)
    direct_rule_prompt = build_direct_rule_plan_prompt(
        intent=intent,
        workspace_path=scope.workspace_path,
        agent_final_output=agent_final_output,
    )
    payload, _err = _generate_direct_rule_plan(direct_rule_prompt)
    llm_checks = _normalize_check_dicts(
        payload.get("llm_checks", []), prefix="llm"
    )

    # Convert any rule_check from LLM output to an llm_check (all-soft policy).
    rule_check = payload.get("rule_check", {})
    if isinstance(rule_check, dict):
        rc_desc = str(rule_check.get("description", "")).strip()
        if rc_desc:
            rc_id = str(rule_check.get("id", "")).strip()
            candidate = {
                "id": rc_id or f"llm_{len(llm_checks) + 1}",
                "description": rc_desc,
            }
            if not any(
                c.get("id") == candidate["id"]
                and c.get("description") == candidate["description"]
                for c in llm_checks
            ):
                llm_checks.append(candidate)

    return VerificationResult(
        intent=intent,
        workspace=workspace,
        agent_final_output=agent_final_output,
        verdict="pass",
        score=1.0,
        soft_score_avg=0.0,
        soft_error=None,
        llm_checks=llm_checks,
        llm_check_results=[],
    )


def verify_workspace_from_plan(
    intent: str,
    workspace: str,
    plan_record: dict[str, Any],
    *,
    agent_final_output: str = "",
    path_mode: str = "auto",
) -> VerificationResult:
    """Evaluate a previously generated plan using the soft-check agent."""
    scope = resolve_verification_scope(intent, workspace, path_mode=path_mode)
    _, llm_checks, _, _ = _extract_plan_checks_and_detector(plan_record)

    llm_check_results = run_llm_agent_verifier(
        intent=intent,
        workspace=scope.workspace_path,
        absolute_paths=list(scope.absolute_paths),
        llm_checks=llm_checks,
        agent_final_output=agent_final_output,
    )

    soft_score_avg = _average_check_score(llm_check_results)
    verdict = _score_to_verdict(soft_score_avg)

    return VerificationResult(
        intent=intent,
        workspace=workspace,
        agent_final_output=agent_final_output,
        verdict=verdict,
        score=soft_score_avg,
        soft_score_avg=soft_score_avg,
        soft_error=_extract_soft_error(llm_check_results),
        llm_checks=llm_checks,
        llm_check_results=llm_check_results,
    )


# ── Soft-check agent core ────────────────────────────────────────────────


def run_llm_agent_verifier(
    *,
    intent: str,
    workspace: str,
    absolute_paths: list[str],
    llm_checks: list[dict[str, str]],
    agent_final_output: str,
) -> list[dict[str, Any]]:
    """Run the multi-round soft-check agent to evaluate llm_checks."""
    if not llm_checks:
        return []

    run_id = uuid4().hex[:12]
    config = llm_config()
    max_rounds = int(config["max_rounds"])
    run_timeout_seconds = _get_soft_run_timeout_seconds()
    tool_timeout_seconds = _get_soft_tool_timeout_seconds()
    available_tools = get_soft_tool_definitions()
    tool_history: list[dict[str, Any]] = []
    executed_tool_names: list[str] = []
    run_started_at = monotonic()

    _soft_log(
        {
            "event": "soft_run_start",
            "run_id": run_id,
            "workspace": workspace,
            "intent": intent,
            "absolute_paths": list(absolute_paths),
            "llm_checks": llm_checks,
            "agent_final_output": agent_final_output,
            "llm_check_count": len(llm_checks),
            "max_rounds": max_rounds,
            "model": str(config.get("model_name", "")),
        }
    )

    initial_prompt = build_soft_check_agent_prompt(
        intent=intent,
        workspace=workspace,
        absolute_paths=absolute_paths,
        llm_checks=llm_checks,
        available_tools=available_tools,
        tool_history=tool_history,
        agent_final_output=agent_final_output,
    )
    conversation_messages: list[dict[str, Any]] = [
        {"role": "user", "content": initial_prompt}
    ]
    fallback_results = [
        {
            "check_id": llm_check.get("id") or "",
            "verdict": "review",
            "score": 0.0,
            "summary": "",
            "evidence": [],
        }
        for llm_check in llm_checks
    ]

    try:
        payload: dict[str, Any] = {}
        request_messages: list[dict[str, Any]] = []

        for round_index in range(1, max_rounds + 1):
            _soft_log(
                {
                    "event": "soft_round_prompt",
                    "run_id": run_id,
                    "round": round_index,
                }
            )

            if _soft_run_timed_out(run_started_at, run_timeout_seconds):
                _soft_log(
                    {
                        "event": "soft_round_stop_run_timeout",
                        "run_id": run_id,
                        "round": round_index,
                        "run_timeout_seconds": run_timeout_seconds,
                    }
                )
                break

            payload = judge_soft_checks_with_agent(
                conversation_messages=conversation_messages,
                available_tools=available_tools,
            )
            if not isinstance(payload, dict):
                payload = {}

            assistant_message = payload.get("_assistant_message")
            if isinstance(assistant_message, dict):
                sanitized_message = {
                    k: v
                    for k, v in assistant_message.items()
                    if isinstance(k, str) and not k.startswith("_")
                }
                if sanitized_message:
                    conversation_messages.append(sanitized_message)

            request_messages = (
                assistant_message.get("_request_messages")
                if isinstance(assistant_message, dict)
                else None
            )

            raw_tool_calls = payload.get("tool_calls", [])
            if not isinstance(raw_tool_calls, list):
                raw_tool_calls = []

            _soft_log(
                {
                    "event": "soft_round_response",
                    "run_id": run_id,
                    "round": round_index,
                    "tool_call_count": len(raw_tool_calls),
                    "result_count": (
                        len(payload.get("results", []))
                        if isinstance(payload.get("results"), list)
                        else 0
                    ),
                }
            )

            round_results_payload = payload.get("results", [])
            if not isinstance(round_results_payload, list):
                round_results_payload = []
            if _has_complete_soft_results(round_results_payload, llm_checks):
                _soft_log(
                    {
                        "event": "soft_round_stop_with_results",
                        "run_id": run_id,
                        "round": round_index,
                        "result_count": len(round_results_payload),
                    }
                )
                break

            valid_calls = []
            for item in raw_tool_calls[:5]:
                if not isinstance(item, dict):
                    continue
                valid_calls.append(
                    {
                        "id": str(item.get("id") or "").strip(),
                        "name": str(item.get("name") or "").strip(),
                        "arguments": item.get("arguments", {}),
                    }
                )
            if not valid_calls:
                _soft_log(
                    {
                        "event": "soft_round_stop_no_tool_calls",
                        "run_id": run_id,
                        "round": round_index,
                    }
                )
                break

            round_results = []
            for call in valid_calls:
                if _soft_run_timed_out(run_started_at, run_timeout_seconds):
                    break

                tool_call_id = str(call.get("id") or "").strip()
                tool_name = str(call.get("name") or "").strip()
                raw_arguments = call.get("arguments")
                normalized_arguments = _normalize_soft_tool_arguments(
                    tool_name,
                    raw_arguments if isinstance(raw_arguments, dict) else {},
                    workspace=workspace,
                    absolute_paths=absolute_paths,
                )

                _soft_log(
                    {
                        "event": "soft_tool_call",
                        "run_id": run_id,
                        "round": round_index,
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "arguments": normalized_arguments,
                    }
                )

                tool_result = _run_soft_tool_call_with_timeout(
                    tool_name,
                    normalized_arguments,
                    timeout_seconds=tool_timeout_seconds,
                )

                _soft_log(
                    {
                        "event": "soft_tool_result",
                        "run_id": run_id,
                        "round": round_index,
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "ok": bool(tool_result.get("ok")),
                        "error": str(tool_result.get("error") or ""),
                        "result_chars": _json_size(tool_result.get("result")),
                        "tool_result": tool_result,
                    }
                )

                tool_result_payload = json.dumps(
                    tool_result, ensure_ascii=False
                )
                if tool_call_id:
                    conversation_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": tool_result_payload,
                        }
                    )
                else:
                    conversation_messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"Tool result for {tool_name}: "
                                f"{tool_result_payload}. "
                                "Continue and return final JSON results "
                                "when ready."
                            ),
                        }
                    )

                if tool_name and tool_name not in executed_tool_names:
                    executed_tool_names.append(tool_name)
                round_results.append(
                    {
                        "tool_call": {
                            "id": tool_call_id,
                            "name": tool_name,
                            "arguments": normalized_arguments,
                        },
                        "tool_result": tool_result,
                    }
                )

            if _soft_run_timed_out(run_started_at, run_timeout_seconds):
                break

            tool_history.append(
                {
                    "round": round_index,
                    "tool_steps": round_results,
                }
            )

        # ── Merge results ─────────────────────────────────────────────
        raw_results = (
            payload.get("results", []) if isinstance(payload, dict) else []
        )
        if not isinstance(raw_results, list):
            raw_results = []

        result_by_id: dict[str, dict[str, Any]] = {}
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            check_id = str(item.get("check_id") or "").strip()
            if not check_id:
                continue
            result_by_id[check_id] = {
                "check_id": check_id,
                "verdict": str(item.get("verdict") or "review"),
                "score": _clamp_score(item.get("score", 0.0)),
                "summary": str(item.get("summary") or ""),
                "evidence": (
                    [str(e) for e in item.get("evidence", [])][:10]
                    if isinstance(item.get("evidence"), list)
                    else []
                ),
                "used_tools": list(executed_tool_names),
            }

        merged_results: list[dict[str, Any]] = []
        for llm_check in llm_checks:
            check_id = llm_check.get("id") or ""
            merged_results.append(
                result_by_id.get(
                    check_id,
                    {
                        "check_id": check_id,
                        "verdict": "review",
                        "score": 0.0,
                        "summary": "soft-check agent did not return this check",
                        "evidence": [],
                        "used_tools": list(executed_tool_names),
                    },
                )
            )

        merged_results = _sanitize_judge_attribution(merged_results)

        _soft_log(
            {
                "event": "soft_run_complete",
                "run_id": run_id,
                "result_count": len(merged_results),
                "avg_score": _average_check_score(merged_results),
                "used_tools": executed_tool_names,
                "merged_results": merged_results,
            }
        )
        return merged_results

    except Exception as exc:
        _soft_log(
            {
                "event": "soft_run_error",
                "run_id": run_id,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }
        )
        for item in fallback_results:
            item["summary"] = f"soft-check agent failed: {exc}"
            item["evidence"] = [str(exc)]
            item["used_tools"] = list(executed_tool_names)
        return fallback_results


# ── Internal helpers ──────────────────────────────────────────────────────


def _generate_direct_rule_plan(
    prompt_text: str,
) -> tuple[dict[str, Any], str | None]:
    try:
        payload = generate_direct_rule_plan(prompt_text)
        if not isinstance(payload, dict):
            return {}, "LLM did not return a valid JSON object"
        return payload, None
    except Exception as exc:
        return {}, str(exc)


def _get_soft_run_timeout_seconds() -> int:
    raw = str(
        os.environ.get("OPENCLAW_SOFT_AGENT_RUN_TIMEOUT_SECONDS", "1200")
    ).strip()
    try:
        value = int(raw)
    except ValueError:
        value = 1200
    return max(30, value)


def _get_soft_tool_timeout_seconds() -> int:
    raw = str(
        os.environ.get("OPENCLAW_SOFT_TOOL_TIMEOUT_SECONDS", "240")
    ).strip()
    try:
        value = int(raw)
    except ValueError:
        value = 240
    return max(10, value)


def _soft_run_timed_out(started_at: float, timeout_seconds: int) -> bool:
    return (monotonic() - started_at) > int(timeout_seconds)


def _soft_tool_worker(
    tool_name: str, arguments: dict[str, Any], result_queue: Any
) -> None:
    try:
        payload = run_soft_tool_call(tool_name, arguments)
    except Exception as exc:
        payload = {
            "tool_name": str(tool_name or "").strip(),
            "ok": False,
            "error": f"tool worker crashed: {exc}",
            "result": None,
        }
    try:
        result_queue.put(payload)
    except Exception:
        pass


def _run_soft_tool_call_with_timeout(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    timeout = max(1, int(timeout_seconds))
    queue: Any = mp.Queue(maxsize=1)
    process = mp.Process(
        target=_soft_tool_worker,
        args=(tool_name, dict(arguments or {}), queue),
        daemon=True,
    )
    process.start()
    process.join(timeout=timeout)
    if process.is_alive():
        process.terminate()
        process.join(timeout=3)
        return {
            "tool_name": str(tool_name or "").strip(),
            "ok": False,
            "error": f"tool call timed out after {timeout}s",
            "result": None,
        }
    try:
        if not queue.empty():
            payload = queue.get_nowait()
            if isinstance(payload, dict):
                return payload
    except Exception:
        pass
    exit_code = process.exitcode
    return {
        "tool_name": str(tool_name or "").strip(),
        "ok": False,
        "error": f"tool process exited without result (exit_code={exit_code})",
        "result": None,
    }


def _sanitize_judge_attribution(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        updated = dict(item)
        summary = updated.get("summary")
        if isinstance(summary, str):
            updated["summary"] = _sanitize_judge_attribution_text(summary)
        evidence = updated.get("evidence")
        if isinstance(evidence, list):
            updated["evidence"] = [
                _sanitize_judge_attribution_text(str(line))
                for line in evidence
            ][:10]
        if not isinstance(updated.get("used_tools"), list):
            updated["used_tools"] = []
        sanitized.append(updated)
    return sanitized


def _has_complete_soft_results(
    raw_results: list[dict[str, Any]],
    llm_checks: list[dict[str, str]],
) -> bool:
    if not raw_results or not llm_checks:
        return False
    expected_ids = {
        str(item.get("id") or "").strip()
        for item in llm_checks
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    if not expected_ids:
        return False
    present_ids = {
        str(item.get("check_id") or "").strip()
        for item in raw_results
        if isinstance(item, dict) and str(item.get("check_id") or "").strip()
    }
    return expected_ids.issubset(present_ids)


def _sanitize_judge_attribution_text(text: str) -> str:
    if not text:
        return text
    lowered = text.lower()
    has_agent = "agent" in lowered or "智能体" in text
    tool_markers = (
        "tool",
        "list_workspace",
        "glob_files",
        "file_stat",
        "markdown_convert",
        "PaddleOCR",
        "searched",
        "called",
        "invoked",
        "browsed",
        "使用了工具",
        "调用了工具",
        "搜索了",
    )
    if not has_agent or not any(
        marker in lowered or marker in text for marker in tool_markers
    ):
        return text
    replacements = [
        (r"\b[Tt]he agent\b", "During evaluation, the judge"),
        (r"\b[Aa]gent\b", "judge"),
        (r"智能体调用了工具", "评判阶段调用了工具"),
        (r"智能体使用了工具", "评判阶段使用了工具"),
        (r"智能体搜索了", "评判阶段搜索了"),
    ]
    updated = text
    for pattern, replacement in replacements:
        updated = re.sub(pattern, replacement, updated)
    return updated


def _extract_soft_error(
    llm_check_results: list[dict[str, Any]],
) -> dict[str, str] | None:
    if not llm_check_results:
        return None
    summaries = [
        str(item.get("summary") or "")
        for item in llm_check_results
        if isinstance(item, dict)
    ]
    if not summaries:
        return None
    prefix = "soft-check agent failed: "
    failed = [s for s in summaries if s.startswith(prefix)]
    if len(failed) != len(llm_check_results):
        return None
    message = failed[0][len(prefix) :].strip() if failed else ""
    if not message:
        return None
    return {
        "kind": _classify_soft_error(message),
        "message": message,
    }


def _classify_soft_error(message: str) -> str:
    lowered = str(message or "").lower()
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    if "prompt exceeds max length" in lowered:
        return "prompt_too_long"
    if "http error" in lowered:
        return "llm_http_error"
    if "valid json" in lowered:
        return "invalid_json"
    return "agent_error"


def _normalize_check_dicts(
    items: Any, *, prefix: str = "llm"
) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(items, start=1):
        if isinstance(item, dict):
            check_id = (
                str(item.get("id", "")).strip() or f"{prefix}_{index}"
            )
            description = str(item.get("description", "")).strip()
        else:
            check_id = f"{prefix}_{index}"
            description = str(item).strip()
        if not description:
            continue
        key = f"{check_id}|{description}"
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"id": check_id, "description": description})
    return normalized


def _extract_plan_checks_and_detector(
    plan_record: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]], str, dict[str, Any]]:
    """Extract rule_checks, llm_checks, detector_code from a plan record.

    Supports both the legacy format (separate fields) and compact format
    (check_items list).
    """
    raw_rule_checks = _normalize_check_dicts(
        plan_record.get("rule_checks", []), prefix="rule"
    )
    raw_llm_checks = _normalize_check_dicts(
        plan_record.get("llm_checks", []), prefix="llm"
    )
    detector_code = ""
    detector_meta: dict[str, Any] = {}

    detector_entries = plan_record.get("rule_detector_codes", [])
    if isinstance(detector_entries, list):
        for item in detector_entries:
            if not isinstance(item, dict):
                continue
            candidate = str(item.get("detector_code", "")).strip()
            if not candidate:
                continue
            detector_code = candidate
            detector_meta = item

    # Compact format: check_items.
    check_items = plan_record.get("check_items")
    if isinstance(check_items, list):
        compact_rule_checks: list[dict[str, str]] = []
        compact_llm_checks: list[dict[str, str]] = []
        compact_rule_meta: dict[str, Any] = {}
        compact_detector_code = ""
        for item in check_items:
            if not isinstance(item, dict):
                continue
            check_type = str(item.get("type", "")).strip().lower()
            check_id = str(item.get("id", "")).strip()
            description = str(item.get("description", "")).strip()
            if not check_id and not description:
                continue
            if check_type == "rule":
                compact_rule_checks.append(
                    {"id": check_id or "rule_1", "description": description}
                )
                code = str(item.get("detector_code", "")).strip()
                if code and not compact_detector_code:
                    compact_detector_code = code
                    compact_rule_meta = {
                        "id": check_id,
                        "description": description,
                    }
            elif check_type in {"llm", "soft"}:
                compact_llm_checks.append(
                    {"id": check_id or "llm_1", "description": description}
                )
        if compact_rule_checks:
            raw_rule_checks = _normalize_check_dicts(
                compact_rule_checks, prefix="rule"
            )
        if compact_llm_checks:
            raw_llm_checks = _normalize_check_dicts(
                compact_llm_checks, prefix="llm"
            )
        if compact_detector_code:
            detector_code = compact_detector_code
            detector_meta = compact_rule_meta

    if not detector_code:
        payload = plan_record.get("payload", {})
        if isinstance(payload, dict):
            detector_code = str(payload.get("detector_code", "")).strip()

    if detector_meta and not raw_rule_checks:
        raw_rule_checks = _normalize_check_dicts(
            [
                {
                    "id": str(detector_meta.get("id", "")).strip(),
                    "description": str(
                        detector_meta.get("description", "")
                    ).strip(),
                }
            ],
            prefix="rule",
        )

    return raw_rule_checks, raw_llm_checks, detector_code, detector_meta


def _normalize_soft_tool_arguments(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    workspace: str,
    absolute_paths: list[str],
) -> dict[str, Any]:
    normalized = dict(arguments or {})
    if (
        tool_name in {"list_workspace", "glob_files"}
        and "workspace_path" not in normalized
    ):
        normalized["workspace_path"] = _resolve_soft_workspace_path(
            "",
            workspace=workspace,
            absolute_paths=absolute_paths,
            tool_name=tool_name,
        )
    if "path" in normalized:
        normalized["path"] = _resolve_soft_path(
            normalized.get("path"),
            workspace=workspace,
            absolute_paths=absolute_paths,
        )
    if "workspace_path" in normalized:
        normalized["workspace_path"] = _resolve_soft_workspace_path(
            normalized.get("workspace_path"),
            workspace=workspace,
            absolute_paths=absolute_paths,
            tool_name=tool_name,
        )
    return normalized


def _resolve_soft_path(
    raw_value: Any, *, workspace: str, absolute_paths: list[str]
) -> Any:
    if not isinstance(raw_value, str):
        return raw_value
    value = raw_value.strip()
    if not value:
        return value
    target = Path(value)
    if target.is_absolute():
        return str(target.resolve())
    if workspace:
        return str((Path(workspace) / target).resolve())
    return value


def _resolve_soft_workspace_path(
    raw_value: Any,
    *,
    workspace: str,
    absolute_paths: list[str],
    tool_name: str,
) -> Any:
    if not isinstance(raw_value, str):
        return raw_value
    value = raw_value.strip()
    if value:
        target = Path(value)
        if target.is_absolute():
            return str(target.resolve())
        if workspace:
            return str((Path(workspace) / target).resolve())
        return value
    if tool_name in {"list_workspace", "glob_files"} and absolute_paths:
        first = Path(absolute_paths[0])
        if first.is_absolute():
            return str(
                (first if first.is_dir() else first.parent).resolve()
            )
    return value


# ── Scoring helpers ───────────────────────────────────────────────────────


def _average_check_score(checks: list[dict[str, Any]]) -> float:
    if not checks:
        return 0.0
    return round(
        sum(_clamp_score(item.get("score", 0.0)) for item in checks)
        / len(checks),
        3,
    )


def _clamp_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, score))


def _score_to_verdict(score: float) -> str:
    if score >= 1.0:
        return "pass"
    if score > 0.0:
        return "review"
    return "fail"


# ── Logging helpers ───────────────────────────────────────────────────────


def _json_size(payload: Any) -> int:
    try:
        return len(
            json.dumps(payload, ensure_ascii=False, default=_json_log_default)
        )
    except (TypeError, ValueError):
        return len(str(payload))


def _json_log_default(value: Any) -> Any:
    if isinstance(value, (datetime, Path)):
        return str(value)
    return str(value)


def _soft_log(event: dict[str, Any]) -> None:
    if not isinstance(event, dict):
        return
    path = str(
        os.environ.get("OPENCLAW_SOFT_AGENT_LOG_JSONL", "")
    ).strip()
    stdout_enabled = str(
        os.environ.get("OPENCLAW_SOFT_AGENT_LOG_STDOUT", "")
    ).strip().lower() in {"1", "true", "yes", "on"}
    if not path and not stdout_enabled:
        return
    payload = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        **event,
    }
    line = json.dumps(payload, ensure_ascii=False, default=_json_log_default)
    run_id = str(payload.get("run_id") or "").strip()
    if path:
        try:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            if run_id:
                split_dir = target.parent / f"{target.stem}_by_run_id"
                split_dir.mkdir(parents=True, exist_ok=True)
                split_target = split_dir / f"{run_id}.jsonl"
                with split_target.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except OSError:
            pass
    if stdout_enabled:
        print(line)
