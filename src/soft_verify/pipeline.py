"""Shared batch-processing utilities for step1/step2 scripts."""
from __future__ import annotations

import concurrent.futures
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable


def load_jsonl(path: str) -> list[dict]:
    """Load records from a JSONL file."""
    records: list[dict] = []
    for line_number, raw_line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"Line {line_number} is not a JSON object")
        records.append(payload)
    return records


def normalize_plan_intent(intent: str) -> str:
    """Strip leading [timestamp] prefix from an intent string."""
    normalized = str(intent or "").strip()
    return re.sub(r"^\[[^\]]*\]\s*", "", normalized, count=1)


def dedupe_records(records: list[dict]) -> list[dict]:
    """De-duplicate records by normalized intent."""
    deduped: list[dict] = []
    seen: set[str] = set()
    for record in records:
        intent = str(record.get("intent", "")).strip()
        key = normalize_plan_intent(intent)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def record_key(
    record: dict, *, include_output: bool = False
) -> tuple[str, str, str]:
    """Build a dedup key from a record."""
    intent = normalize_plan_intent(str(record.get("intent", "")).strip())
    workspace = str(record.get("workspace", "")).strip()
    output = (
        str(record.get("agent_final_output", "done")).strip()
        if include_output
        else ""
    )
    return (intent, workspace, output)


def process_records_to_jsonl(
    records: list[dict],
    *,
    output_path: Path,
    workers: int,
    handler: Callable[[int, dict], tuple[int, dict]],
    include_output_in_key: bool = False,
) -> None:
    """Process records concurrently and write results to JSONL with resume."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    reusable, kept_records, removed = _load_reusable_results(
        output_path, include_output_in_key=include_output_in_key
    )
    if removed > 0:
        with output_path.open("w", encoding="utf-8") as f:
            for item in kept_records:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
                f.flush()

    pending: list[tuple[int, dict]] = []
    for index, rec in enumerate(records):
        key = record_key(rec, include_output=include_output_in_key)
        cached = reusable.get(key) or []
        if cached:
            cached.pop(0)
            continue
        pending.append((index, rec))

    reused = len(records) - len(pending)
    print(
        f"Resume: total={len(records)} reused={reused} "
        f"pending={len(pending)} removed={removed}"
    )

    with output_path.open("a", encoding="utf-8") as f:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(handler, idx, rec): idx
                for idx, rec in pending
            }
            for future in concurrent.futures.as_completed(futures):
                _, item = future.result()
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
                f.flush()


def build_failed_result(
    *,
    intent: str,
    workspace: str,
    agent_final_output: str,
    error_kind: str,
    error_message: str,
) -> dict:
    """Build a standardized failure result dict."""
    return {
        "intent": intent,
        "workspace": workspace,
        "agent_final_output": agent_final_output,
        "verdict": "fail",
        "score": 0.0,
        "soft_score_avg": 0.0,
        "soft_error": {
            "kind": error_kind,
            "message": error_message,
        },
        "llm_checks": [],
        "llm_check_results": [],
    }


# ── Internal helpers ──────────────────────────────────────────────────────


def _load_reusable_results(
    path: Path,
    *,
    include_output_in_key: bool,
) -> tuple[dict[tuple, list[dict]], list[dict], int]:
    """Load existing results, separating reusable from broken records."""
    if not path.exists():
        return {}, [], 0

    records = load_jsonl(str(path))
    reusable: dict[tuple, list[dict]] = defaultdict(list)
    kept: list[dict] = []
    removed = 0
    seen_keys: set[tuple] = set()

    for rec in records:
        if not isinstance(rec, dict):
            removed += 1
            continue
        # Drop records with soft errors so they get re-computed.
        soft_error = rec.get("soft_error")
        if soft_error not in (None, {}):
            removed += 1
            continue
        key = record_key(rec, include_output=include_output_in_key)
        if key in seen_keys:
            removed += 1
            continue
        seen_keys.add(key)
        kept.append(rec)
        reusable[key].append(rec)

    return dict(reusable), kept, removed
