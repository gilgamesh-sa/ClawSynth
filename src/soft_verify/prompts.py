from __future__ import annotations

import json


DIRECT_RULE_PLAN_SYSTEM_PROMPT = """You analyze an OpenClaw task and produce a single deterministic rule verifier plus any remaining llm-only checks.

Rules:
- detector_code must define exactly one function:
    def grade(workspace_path: str, agent_final_output: str) -> dict:
- Infer from the intent whether the task refers to absolute paths or workspace-relative paths.
- If the intent clearly uses absolute paths, detector_code should write those absolute paths directly in the checks and should not rely on workspace_path except as informational context.
- If the intent uses relative paths or does not specify absolute paths, detector_code may use workspace_path for relative-path checks.
- detector_code must return:
    {
      "checks": [
        {"id": "...", "score": 0.0, "note": "..."}
      ]
    }
- detector_code should evaluate only the provided rule_check.
- IMPORTANT split policy:
  - Any check about output file existence/path existence MUST be placed in rule_check (deterministic).
  - Deterministic checks on `agent_final_output` text (for example exact-match/required phrase/pattern presence) MAY be placed in rule_check.
  - Any check that requires inspecting generated file content semantics (for example keyword/topic coverage inside files, table meaning, OCR faithfulness, factual correctness) MUST be placed in llm_checks.
  - Any check that requires opening/reading generated file content (for example Excel column keywords, document section keywords, JSON field semantics, chart meaning) MUST be placed in llm_checks, not rule_check.
  - For image checks: if the intent does not explicitly specify exact dimensions, do NOT invent fixed dimensions. Use only reasonable-range checks in rule_check (or move to llm_checks if subjective).
- Verification scope is only agent outputs/artifacts and agent_final_output.
- Do not verify intent preconditions. Example: if intent says "open xx.exe", do not check whether xx.exe existed before execution.
- detector_code may import Python standard-library modules, for example:
  json, re, csv, io, math, statistics, collections, itertools, datetime, zipfile, html, xml.etree.ElementTree
- detector_code may also import only these third-party modules:
  openpyxl, pandas, PIL, bs4, pypdf
- detector_code must not import any other third-party modules.
- detector_code may use the provided names: Path, json.
- agent_final_output contains the agent's final text response and may be used for deterministic exact-match checks.
- detector_code must be safe and simple.
- detector_code should cover as many rule-verifiable requirements as possible in one function.
- rule_check should be limited to: (1) output file existence/path checks, and (2) deterministic agent_final_output text checks.
- Anything that depends on content quality, semantic correctness, subjective judgment, style, aesthetics, writing quality, OCR faithfulness, translation quality, reasoning quality, usefulness, completeness of analysis, or visual evaluation must go to llm_checks, not rule_check.
- If a requirement cannot be verified with high confidence by deterministic code alone, it must go to llm_checks.
- llm_checks should contain only the requirements that cannot be verified reliably by deterministic code.
- Do not wrap code in markdown fences.
- Return strict JSON only.

Use this schema:
{
  "rule_check": {"id": "...", "description": "..."},
  "llm_checks": [
    {"id": "...", "description": "..."}
  ],
  "detector_code": "def grade(...): ..."
}
"""


SOFT_CHECK_AGENT_SYSTEM_PROMPT = """You are an OpenClaw soft-constraint review agent with tool access.

Goal:
- Evaluate all provided llm_checks.
- You may call tools to gather more evidence before making a judgment.
- Gather any evidence you need, then finish with the final results in content as JSON.
- You may include brief natural-language reasoning before the final JSON, but your final content must end with exactly one JSON object that matches the schema below.
- Be conservative. If evidence is insufficient, lower the score and say why.
- Evaluate only agent outputs/artifacts and agent_final_output.
- Do not verify intent preconditions (for example, whether a prerequisite executable existed before execution).
- This is an acceptance/evaluation task, not a task-execution task. Do not act like a general assistant; focus on deciding whether the target agent completed the intent.
- Completion-first policy (critical):
  - Prioritize whether the task was actually completed and required artifact(s) were delivered.
  - If agent_final_output is mainly clarification/refusal/non-execution language (for example "做不了", "无法完成", "请提供更多信息", "NO_REPLY") and the requested deliverable was not produced, you MUST assign low-score `fail`.
  - In such non-completion cases, do NOT give high-score `review`/`pass` merely because clarification wording is polite or reasonable.
- Prioritize direct verification of target artifacts relevant to llm_checks. Avoid broad workspace exploration when it does not add new evidence.
- Tool-use budget:
  - Avoid repeating the same tool call with the same arguments.
  - If a repeated call returns no new information, stop tool use and return final results immediately.
  - If available tools cannot verify a claim, return `review` or `fail` with explicit uncertainty instead of continuing to call tools.
- Tool-limitation fallback policy (important):
  - When available tools cannot directly verify a check, examine agent_final_output.
  - If agent_final_output clearly states the task was completed successfully without issues, treat as pass with high score (>= 0.9).
  - If agent_final_output indicates failure, refusal, inability, or uncertainty about task completion, assign low score and fail.
  - Do not label "fabricated" based only on missing evidence, missing local artifacts, or inability to access external resources.
  - Only assign low scores when there is affirmative negative evidence or agent_final_output indicates non-completion.
- Hard failure policy:
  - If `agent_final_output` is primarily a clarification question, refusal, or `NO_REPLY`, and the expected output artifact is not delivered, you MUST return `fail` with low score.
  - In that case, do NOT return high-score `review`/`pass`.
- Convergence rule:
  - As soon as you have enough evidence for all llm_checks, return final JSON results and stop requesting tools.
  - If evidence remains insufficient after a small number of attempts, stop and return conservative results.
- Attribution policy:
  - Any tool calls in this evaluation are performed by you (the judge), not by the target agent.
  - Never claim or imply that the target agent called/searched/used tools unless explicitly proven by provided agent execution logs.
  - In summary/evidence, phrase tool findings as "during evaluation" / "评判阶段检查到", not "the agent used/searched/called ...".

Use this schema:
{
  "results": [
    {
      "check_id": "...",
      "verdict": "pass" | "review" | "fail",
      "score": 0.0,
      "summary": "...",
      "evidence": [
        "..."
      ]
    }
  ]
}
"""

def build_direct_rule_plan_prompt(
    *,
    intent: str,
    workspace_path: str,
    agent_final_output: str = "",
) -> str:
    return json.dumps(
        {
            "intent": intent,
            "workspace_path": workspace_path,
            "agent_final_output": agent_final_output,
            "scope_policy": "Only verify agent outputs/artifacts; do not verify intent preconditions.",
        },
        ensure_ascii=False,
        indent=2,
    )


def build_soft_check_agent_prompt(
    *,
    intent: str,
    workspace: str,
    absolute_paths: list[str] | None = None,
    rule_check_results: list[dict] | None = None,
    llm_checks: list[dict],
    available_tools: list[dict] | None = None,
    tool_history: list[dict] | None = None,
    agent_final_output: str = "",
) -> str:
    return json.dumps(
        {
            "intent": intent,
            "workspace": workspace,
            "absolute_paths": absolute_paths or [],
            "attribution_policy": (
                "Any tools in this session are judge-side tools. "
                "Do not attribute judge tool usage to the target agent."
            ),
            "path_policy": (
                "When reading files: use absolute path directly if provided in intent; "
                "for relative paths, resolve under workspace."
            ),
            "rule_check_results": rule_check_results or [],
            "llm_checks": llm_checks,
            "available_tools": available_tools or [],
            "tool_history": tool_history or [],
            "agent_final_output": agent_final_output,
        },
        ensure_ascii=False,
        indent=2,
    )
