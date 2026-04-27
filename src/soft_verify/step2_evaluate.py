#!/usr/bin/env python3
"""Step 2: Evaluate verification plan using soft-check agent.

Usage:
    python step2_evaluate.py --input plan.jsonl --output result.jsonl [--workers 8] [--path-mode auto]

Input JSONL: step1_plan.py output (must contain intent, workspace, llm_checks).
Output JSONL: verification results with verdict, score, and llm_check_results.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from soft_verify.pipeline import (
    build_failed_result,
    dedupe_records,
    load_jsonl,
    normalize_plan_intent,
    process_records_to_jsonl,
)
from soft_verify.verifier import verify_workspace_from_plan
from soft_verify.workspace_inspector import extract_absolute_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Step 2: Evaluate checks from plan JSONL."
    )
    parser.add_argument(
        "--input", required=True, help="Input plan JSONL (step1 output)."
    )
    parser.add_argument("--output", required=True, help="Output result JSONL.")
    parser.add_argument(
        "--workers", type=int, default=8, help="Number of concurrent workers."
    )
    parser.add_argument(
        "--path-mode",
        choices=["auto", "workspace-only", "absolute-priority"],
        default="auto",
        help="Path resolution mode.",
    )
    return parser


def _build_plan_index(records: list[dict]) -> dict[str, dict]:
    """Build a lookup from normalized intent to plan record."""
    index: dict[str, dict] = {}
    for i, record in enumerate(records, 1):
        intent = str(record.get("intent", "")).strip()
        if not intent:
            raise ValueError(f"Plan JSONL line {i} missing intent")
        key = normalize_plan_intent(intent)
        if key in index:
            raise ValueError(f"Plan JSONL line {i} duplicate intent: {key}")
        index[key] = record
    return index


def _evaluate_record(
    index: int,
    record: dict,
    *,
    plan_index: dict[str, dict],
    path_mode: str,
) -> tuple[int, dict]:
    intent = str(record.get("intent", "")).strip()
    workspace = str(record.get("workspace", "")).strip()
    agent_final_output = str(record.get("agent_final_output", "done")).strip()

    if not intent:
        return index, build_failed_result(
            intent=intent,
            workspace=workspace,
            agent_final_output=agent_final_output,
            error_kind="input_validation",
            error_message="intent is empty",
        )

    plan_record = plan_index.get(normalize_plan_intent(intent))
    if plan_record is None:
        return index, build_failed_result(
            intent=intent,
            workspace=workspace,
            agent_final_output=agent_final_output,
            error_kind="plan_lookup",
            error_message="No matching plan found",
        )

    try:
        result = verify_workspace_from_plan(
            intent,
            workspace,
            plan_record,
            agent_final_output=agent_final_output,
            path_mode=path_mode,
        ).to_dict()
    except Exception as exc:
        return index, build_failed_result(
            intent=intent,
            workspace=workspace,
            agent_final_output=agent_final_output,
            error_kind=type(exc).__name__,
            error_message=str(exc),
        )
    return index, result


def main() -> int:
    args = build_parser().parse_args()
    records = load_jsonl(args.input)
    records = dedupe_records(records)
    plan_index = _build_plan_index(records)
    print(f"Loaded {len(records)} plan records from {args.input}")

    process_records_to_jsonl(
        records,
        output_path=Path(args.output),
        workers=max(1, args.workers),
        handler=lambda idx, rec: _evaluate_record(
            idx, rec, plan_index=plan_index, path_mode=args.path_mode
        ),
        include_output_in_key=True,
    )
    print(f"Result output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
