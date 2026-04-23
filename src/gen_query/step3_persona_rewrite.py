#!/usr/bin/env python3
"""Step 3: rewrite generated queries with persona style."""

from __future__ import annotations

import argparse
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from tqdm import tqdm

from src.gen_query.config import (
    INSTRUCTIONS_FILE,
    LITELLM_API_BASE,
    LITELLM_API_KEY,
    LITELLM_MODEL,
    REWRITE_TIMEOUT,
    REWRITE_WORKERS,
    WORKSPACE_HUB,
    WS_PREFIX,
)
from src.gen_query.utils.constants import PERSONA_FILENAME, QUERIES_FILENAME
from src.gen_query.utils.jsonl_io import append_jsonl, load_jsonl
from src.gen_query.utils.llm import chat_completion
from src.gen_query.utils.workspace import iter_workspace_dirs


WRITE_LOCK = threading.Lock()

REWRITE_SYSTEM_PROMPT = """\
你是一个 query 改写器。给定一条原始用户 query 和一个人设描述，你需要在保留原意的基础上，用该人设的语气重新改写 query。

严格规则：
1. 不改变意图
2. 不改变文件名和路径
3. 不增减需求
4. 只改语气和措辞
5. 用中文改写
6. 只输出改写后的 query
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rewrite generated queries with persona style.")
    parser.add_argument(
        "--workspace-hub",
        type=Path,
        default=None,
        help="Override workspace hub directory. Defaults to config.",
    )
    return parser.parse_args()


def load_instructions(path: Path) -> list[str]:
    raw_instructions = load_jsonl_array(path)
    skip_keywords = [
        "zip code",
        "cancel",
        "refund",
        "exchange",
        "order",
        "bottle",
        "address change",
    ]
    return [
        instruction
        for instruction in raw_instructions
        if not any(keyword in instruction.lower() for keyword in skip_keywords)
    ]


def load_jsonl_array(path: Path) -> list[str]:
    import json

    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"Instruction file must contain a JSON array: {path}")
    return [str(item) for item in data]


def rewrite_query(query: str, persona: str) -> str | None:
    try:
        return chat_completion(
            api_base=LITELLM_API_BASE,
            api_key=LITELLM_API_KEY,
            model=LITELLM_MODEL,
            messages=[
                {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
                {"role": "user", "content": f"## 人设\n{persona}\n\n## 原始 query\n{query}"},
            ],
            timeout=REWRITE_TIMEOUT,
        ).strip().strip('"')
    except Exception:
        return None


def rewrite_one(record: dict[str, Any], persona: str) -> dict[str, Any]:
    rewritten_record = dict(record)
    original = str(rewritten_record.get("result", ""))

    if not original or original.startswith("[ERROR]"):
        rewritten_record["persona"] = None
        rewritten_record["result_persona"] = original
        rewritten_record["result_persona_skipped"] = True
        return rewritten_record

    rewritten = rewrite_query(original, persona)
    if rewritten:
        rewritten_record["result_original"] = original
        rewritten_record["result"] = rewritten
        rewritten_record["persona"] = persona
    else:
        rewritten_record["persona"] = None
        rewritten_record["result_persona_error"] = True

    return rewritten_record


def load_finished_ids(output_file: Path) -> set[str]:
    if not output_file.exists():
        return set()
    return {str(record.get("id")) for record in load_jsonl(output_file) if record.get("id")}


def main() -> None:
    args = parse_args()
    workspace_hub = args.workspace_hub.resolve() if args.workspace_hub else WORKSPACE_HUB

    if not workspace_hub.exists():
        raise FileNotFoundError(
            f"workspace_hub does not exist: {workspace_hub}\n"
            "Run step1 and step2 first or fix WORKSPACE_HUB in src/gen_query/config.py."
        )
    if not INSTRUCTIONS_FILE.exists():
        raise FileNotFoundError(
            f"Instruction file does not exist: {INSTRUCTIONS_FILE}\n"
            "Fix INSTRUCTIONS_FILE in src/gen_query/config.py."
        )

    instructions = load_instructions(INSTRUCTIONS_FILE)
    if not instructions:
        raise ValueError(f"No usable persona instructions found in {INSTRUCTIONS_FILE}")

    print("=" * 60)
    print("Step 3: persona rewrite")
    print(f"  model: {LITELLM_MODEL}")
    print(f"  workers: {REWRITE_WORKERS}")
    print(f"  timeout: {REWRITE_TIMEOUT}")
    print(f"  workspace_hub: {workspace_hub}")
    print(f"  workspace prefix: {WS_PREFIX}")
    print(f"  instruction file: {INSTRUCTIONS_FILE}")
    print("=" * 60)
    print(f"\nLoaded {len(instructions)} persona instructions")
    print(f"Sample: {instructions[0][:60]}...")

    workspace_dirs = iter_workspace_dirs(workspace_hub, WS_PREFIX)
    print(f"\nFound {len(workspace_dirs)} workspace directories")

    all_tasks: list[tuple[dict[str, Any], Path, str, str]] = []
    global_total = 0
    skipped_workspaces = 0

    for workspace_dir in workspace_dirs:
        workspace_name = workspace_dir.name
        input_file = workspace_dir / QUERIES_FILENAME
        output_file = workspace_dir / PERSONA_FILENAME

        if not input_file.exists():
            skipped_workspaces += 1
            continue

        records = load_jsonl(input_file)
        if not records:
            skipped_workspaces += 1
            continue

        global_total += len(records)
        finished_ids = load_finished_ids(output_file)
        todo = [record for record in records if record["id"] not in finished_ids]

        if not todo:
            print(f"  {workspace_name}: all {len(records)} records already rewritten")
            continue

        print(
            f"  {workspace_name}: total {len(records)}, rewritten {len(finished_ids)}, remaining {len(todo)}"
        )
        for record in todo:
            persona = random.choice(instructions)
            all_tasks.append((record, output_file, workspace_name, persona))

    if skipped_workspaces:
        print(f"  skipped {skipped_workspaces} workspaces with no input records")

    if not all_tasks:
        print("\nNothing to do.")
        return

    print(f"\nCollected {len(all_tasks)} pending rewrites ({global_total} total records)")

    stats = {"ok": 0, "fail": 0, "skipped": 0}
    with tqdm(total=len(all_tasks), desc="global progress", unit="q") as progress_bar:
        with ThreadPoolExecutor(max_workers=REWRITE_WORKERS) as executor:
            future_map = {
                executor.submit(rewrite_one, record, persona): (record, output_file)
                for record, output_file, _, persona in all_tasks
            }

            for future in as_completed(future_map):
                record, output_file = future_map[future]
                try:
                    result_record = future.result()
                    with WRITE_LOCK:
                        append_jsonl(output_file, result_record)
                    if result_record.get("persona") is None and result_record.get("result_persona_error"):
                        stats["fail"] += 1
                    elif result_record.get("result_persona_skipped"):
                        stats["skipped"] += 1
                    else:
                        stats["ok"] += 1
                except Exception as exc:
                    failed_record = dict(record)
                    failed_record["persona"] = None
                    failed_record["result_persona_error"] = True
                    with WRITE_LOCK:
                        append_jsonl(output_file, failed_record)
                    stats["fail"] += 1
                    progress_bar.write(f"  uncaught error for {record['id']}: {exc}")

                progress_bar.update(1)
                progress_bar.set_postfix(ok=stats["ok"], fail=stats["fail"], refresh=True)

    print(f"\n{'=' * 60}")
    print("Done.")
    print(f"  workspaces: {len(workspace_dirs)}")
    print(f"  total records: {global_total}")
    print(f"  rewritten this run: {stats['ok']}")
    if stats["skipped"]:
        print(f"  skipped this run: {stats['skipped']}")
    print(f"  failed this run: {stats['fail']}")
    if stats["fail"]:
        print("  failed rewrites keep the original query; rerun step3 to resume")
    print(f"  output file: <workspace_dir>/{PERSONA_FILENAME}")


if __name__ == "__main__":
    main()
