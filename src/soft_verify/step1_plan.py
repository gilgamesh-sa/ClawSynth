#!/usr/bin/env python3
"""Step 1: Generate verification plan (llm_checks) from task records.

Usage:
    python step1_plan.py --input tasks.jsonl --output plan.jsonl [--workers 8] [--path-mode auto]

Input JSONL fields (per line):
    intent              - Task description (required)
    workspace           - Absolute path to workspace directory (required)
    agent_final_output  - Agent's final text response (optional)

Output JSONL fields (per line):
    intent, workspace, agent_final_output, llm_checks
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from soft_verify.pipeline import (
    build_failed_result,
    load_jsonl,
    process_records_to_jsonl,
)
from soft_verify.verifier import generate_verification_plan
from soft_verify.workspace_inspector import extract_absolute_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Step 1: Generate verification plan from task JSONL."
    )
    parser.add_argument("--input", required=True, help="Input JSONL file.")
    parser.add_argument("--output", required=True, help="Output plan JSONL file.")
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


def _plan_record(
    index: int, record: dict, *, path_mode: str
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
    if not workspace and not (
        path_mode in {"auto", "absolute-priority"}
        and extract_absolute_paths(intent)
    ):
        return index, build_failed_result(
            intent=intent,
            workspace=workspace,
            agent_final_output=agent_final_output,
            error_kind="input_validation",
            error_message="workspace is empty and no absolute paths in intent",
        )

    try:
        full_res = generate_verification_plan(
            intent,
            workspace,
            agent_final_output=agent_final_output,
            path_mode=path_mode,
        ).to_dict()
        result = {
            "intent": full_res["intent"],
            "workspace": full_res["workspace"],
            "agent_final_output": full_res["agent_final_output"],
            "llm_checks": full_res["llm_checks"],
        }
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
    print(f"Loaded {len(records)} records from {args.input}")

    process_records_to_jsonl(
        records,
        output_path=Path(args.output),
        workers=max(1, args.workers),
        handler=lambda idx, rec: _plan_record(
            idx, rec, path_mode=args.path_mode
        ),
        include_output_in_key=False,
    )
    print(f"Plan output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
