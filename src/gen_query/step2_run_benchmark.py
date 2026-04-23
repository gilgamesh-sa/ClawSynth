#!/usr/bin/env python3
"""Step 2: render prompt records into concrete queries with an LLM."""

from __future__ import annotations

import argparse
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from tqdm import tqdm

from src.gen_query.config import (
    BENCH_CONCURRENCY,
    LITELLM_API_BASE,
    LITELLM_API_KEY,
    LITELLM_MODEL,
    WORKSPACE_HUB,
    WS_PREFIX,
)
from src.gen_query.utils.constants import QUERIES_FILENAME, TMP_PROMPTS_FILENAME
from src.gen_query.utils.jsonl_io import append_jsonl, load_jsonl
from src.gen_query.utils.llm import chat_completion
from src.gen_query.utils.workspace import iter_workspace_dirs


MAX_RETRIES = 5
RETRY_DELAY = 5
REQUEST_TIMEOUT = 120

WRITE_LOCK = threading.Lock()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate concrete queries from prompt records.")
    parser.add_argument(
        "--workspace-hub",
        type=Path,
        default=None,
        help="Override workspace hub directory. Defaults to config.",
    )
    return parser.parse_args()


def parse_query(raw_query: str) -> tuple[str, str]:
    parts = re.split(r"\n\[USER\]\n", raw_query, maxsplit=1)
    if len(parts) != 2:
        return "", raw_query.strip()

    system_prompt = re.sub(r"^\[SYSTEM\]\n", "", parts[0]).strip()
    user_prompt = parts[1].strip()
    return system_prompt, user_prompt


def call_llm(system_prompt: str, user_prompt: str) -> str:
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    return chat_completion(
        api_base=LITELLM_API_BASE,
        api_key=LITELLM_API_KEY,
        model=LITELLM_MODEL,
        messages=messages,
        timeout=REQUEST_TIMEOUT,
    )


def load_finished_ids(output_file: Path) -> set[str]:
    if not output_file.exists():
        return set()

    finished: set[str] = set()
    for record in load_jsonl(output_file):
        record_id = record.get("id")
        result = record.get("result")
        if isinstance(record_id, str) and isinstance(result, str) and result and not result.startswith("[ERROR]"):
            finished.add(record_id)
    return finished


def process_one(
    record: dict[str, Any],
    output_file: Path,
    workspace_name: str,
    progress_bar: tqdm | None = None,
    stats: dict[str, int] | None = None,
) -> dict[str, Any]:
    query_id = str(record["id"])
    system_prompt, user_prompt = parse_query(str(record["query"]))

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = call_llm(system_prompt, user_prompt)
            completed_record = dict(record)
            completed_record["result"] = result

            with WRITE_LOCK:
                append_jsonl(output_file, completed_record)
                if stats is not None:
                    stats["done"] += 1

            if progress_bar is not None and stats is not None:
                progress_bar.set_postfix(ok=stats["done"], fail=stats["fail"], refresh=True)
                progress_bar.update(1)
            return completed_record
        except Exception as exc:
            last_error = str(exc)
            if attempt < MAX_RETRIES:
                if progress_bar is not None:
                    progress_bar.write(
                        f"  retry {attempt}/{MAX_RETRIES - 1} for {workspace_name}/{query_id}: {last_error[:80]}"
                    )
                time.sleep(RETRY_DELAY * attempt)

    failed_record = dict(record)
    failed_record["result"] = f"[ERROR] {last_error}"
    with WRITE_LOCK:
        append_jsonl(output_file, failed_record)
        if stats is not None:
            stats["fail"] += 1

    if progress_bar is not None and stats is not None:
        progress_bar.set_postfix(ok=stats["done"], fail=stats["fail"], refresh=True)
        progress_bar.update(1)
    return failed_record


def main() -> None:
    args = parse_args()
    workspace_hub = args.workspace_hub.resolve() if args.workspace_hub else WORKSPACE_HUB

    if not workspace_hub.exists():
        raise FileNotFoundError(
            f"workspace_hub does not exist: {workspace_hub}\n"
            "Run step1 first or fix WORKSPACE_HUB in src/gen_query/config.py."
        )

    print("=" * 60)
    print("Step 2: generate queries")
    print(f"  model: {LITELLM_MODEL}")
    print(f"  api base: {LITELLM_API_BASE}")
    print(f"  concurrency: {BENCH_CONCURRENCY}")
    print(f"  workspace_hub: {workspace_hub}")
    print(f"  workspace prefix: {WS_PREFIX}")
    print("=" * 60)

    workspace_dirs = iter_workspace_dirs(workspace_hub, WS_PREFIX)
    print(f"\nFound {len(workspace_dirs)} workspace directories")

    all_tasks: list[tuple[dict[str, Any], Path, str]] = []
    global_total = 0
    skipped_workspaces = 0

    for workspace_dir in workspace_dirs:
        workspace_name = workspace_dir.name
        input_file = workspace_dir / TMP_PROMPTS_FILENAME
        output_file = workspace_dir / QUERIES_FILENAME

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
            print(f"  {workspace_name}: all {len(records)} records already completed")
            continue

        print(
            f"  {workspace_name}: total {len(records)}, done {len(finished_ids)}, remaining {len(todo)}"
        )
        for record in todo:
            all_tasks.append((record, output_file, workspace_name))

    if skipped_workspaces:
        print(f"  skipped {skipped_workspaces} workspaces with no input records")

    if not all_tasks:
        print("\nNothing to do.")
        return

    print(f"\nCollected {len(all_tasks)} pending records ({global_total} total records)")

    stats = {"done": 0, "fail": 0}
    with tqdm(total=len(all_tasks), desc="global progress", unit="q") as progress_bar:
        with ThreadPoolExecutor(max_workers=BENCH_CONCURRENCY) as executor:
            futures = {
                executor.submit(process_one, record, output_file, workspace_name, progress_bar, stats):
                (workspace_name, str(record["id"]))
                for record, output_file, workspace_name in all_tasks
            }
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    workspace_name, query_id = futures[future]
                    progress_bar.write(f"  uncaught error for {workspace_name}/{query_id}: {exc}")

    print(f"\n{'=' * 60}")
    print("Done.")
    print(f"  workspaces: {len(workspace_dirs)}")
    print(f"  total records: {global_total}")
    print(f"  succeeded this run: {stats['done']}")
    print(f"  failed this run: {stats['fail']}")
    if stats["fail"]:
        print("  rerun step2 to resume failed records")
    print(f"  output file: <workspace_dir>/{QUERIES_FILENAME}")


if __name__ == "__main__":
    main()
