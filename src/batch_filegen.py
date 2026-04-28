#!/usr/bin/env python3
"""
Usage:
  1. python src/batch_filegen.py run --workspace-hub ... --workspace-base ... --results-dir ... --skills-source ...
  2. python src/batch_filegen.py cleanup --workspace-hub ...
  3. python src/batch_filegen.py reset --workspace-hub ...
  4. python src/batch_filegen.py status --workspace-hub ...
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from tqdm import tqdm

# ============================================================
# Fixed file names
# ============================================================
INPUT_FILENAME = "queries_persona.jsonl"
LOG_FILENAME = "filegen_log.jsonl"

# ============================================================
# Runtime config (initialized from args and .env)
# ============================================================
WORKSPACE_HUB: Path | None = None
WORKSPACE_BASE: Path | None = None
RESULTS_DIR: Path | None = None
SKILLS_SOURCE: Path | None = None

GEN_OPENCLAW_MODEL: str | None = None
OPENCLAW_TIMEOUT = 1200
MAX_DOMAIN_PARALLEL = 5

LITELLM_API_BASE: str | None = None
LITELLM_API_KEY: str | None = None
FILTER_MODEL: str | None = None
FILTER_TIMEOUT = 50
FILTER_WORKERS = 1

# ============================================================
# Global state (thread-safe)
# ============================================================
_log_lock = threading.Lock()
_setup_workspaces: set[str] = set()
_setup_workspaces_lock = threading.Lock()
_agent_cli_lock = threading.Lock()

# ============================================================
# Prompt template for OpenClaw
# ============================================================
PROMPT_TEMPLATE = """\
Below is a user query that may require some local files as input when executed, such as images, audio, or documents.

Please analyze this query, identify the input files that need to already exist beforehand, such as files the user refers to with phrases like "I have..." or "help me analyze/recognize/translate this file", and then generate those files. You may use the `claw-input-file-generator` skill to create them.

If there are no input files that must already exist, then skip this query.
If there are input files that must already exist, you can rely on the `claw-input-file-generator` skill to synthesize them.


Notes:
- Generate only input files. Do not generate output files requested by the query, such as files mentioned in "save to xxx".
- If the query does not require any pre-existing files, such as pure search or pure generation tasks, simply reply with "No input files need to be generated".
- Save all files under the `{workspace}` directory while preserving the relative path structure referenced in the query.
- For image files, generate reasonable image content using text-to-image or canvas capabilities.
- For audio files, generate them using speech synthesis.
- For text or document files, write reasonable content directly.

The user query is:
---
{query}
---"""


# ============================================================
# LLM prefilter: determine whether the query requires pre-generated input files
# ============================================================
FILTER_SYSTEM_PROMPT = """\
You are a file requirement analyzer. Given a user query, determine whether it requires local input files that must already exist before execution.

Note: some users explicitly provide file paths, such as `./receipt.png`, while others only describe the files vaguely, such as "I have some sales data" or "there is an English annual report on my computer". Both cases count as requiring input files.

Examples that require input files (explicit path):
- "Help me recognize the text in ./receipt.png" -> YES (`./receipt.png` must already exist)
- "Translate the content of ./report_en.pdf" -> YES (`./report_en.pdf` must already exist)
- "Help me analyze the data in ./sales_data.csv" -> YES (`./sales_data.csv` must already exist)

Examples that require input files (vague description):
- "I have some sales data, help me analyze the trend" -> YES (the user says "I have", which implies the file already exists)
- "There is an English annual report on my computer, help me translate it" -> YES (the user refers to an existing file)
- "I previously saved a photo of an invoice, help me recognize its content" -> YES (the user says "I previously saved")
- "That meeting audio I recorded yesterday, help me convert it to text" -> YES (the user refers to an existing audio file)

Examples that do not require input files:
- "Help me search for news about the new energy vehicle industry" -> NO (pure search/generation task)
- "Help me create a promotional image for a pet hospital and save it to ./poster.png" -> NO (`./poster.png` is an output file, not an input file)
- "Help me write an industry analysis report" -> NO (pure generation task)
- "Help me record a podcast about the coffee industry" -> NO (pure generation task)
- "Help me design a frontend webpage" -> NO (pure generation task)

Key distinction:
- An input file is a file the user already has before the query is executed and that the AI must read or process, whether or not a path is provided.
- An output file is a file the AI is asked to generate or save, so it does not count as an input file.
- Phrases like "I have...", "I previously saved...", "there is ... on my computer", or "I recorded yesterday..." all indicate an existing file and therefore require pre-generation.

Reply only with YES or NO, and nothing else."""

FILTER_USER_PROMPT = "Here is the query you need to classify: "


# ============================================================
# Argument initialization
# ============================================================
def load_dotenv(env_file: Path):
    if not env_file.exists():
        return

    with open(env_file, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()

            key, sep, value = line.partition("=")
            if not sep:
                continue

            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]

            if key and key not in os.environ:
                os.environ[key] = value


def positive_int(value: str) -> int:
    ivalue = int(value)
    if ivalue <= 0:
        raise argparse.ArgumentTypeError("The argument must be a positive integer")
    return ivalue


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch-generate the input files required by queries")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Path to the .env file")

    subparsers = parser.add_subparsers(dest="action", required=True)

    def add_common_args(subparser: argparse.ArgumentParser):
        subparser.add_argument("--workspace-hub", type=Path, required=True, help="Root directory of the source workspaces")
        subparser.add_argument("--workspace-base", type=Path, help="Root directory for temporary workspaces (required for run)")
        subparser.add_argument("--results-dir", type=Path, help="Results directory (required for run)")
        subparser.add_argument("--skills-source", type=Path, help="Skills source directory (required for run)")
        subparser.add_argument("--openclaw-model", type=str, default=os.getenv("GEN_OPENCLAW_MODEL"))
        subparser.add_argument("--openclaw-timeout", type=positive_int, default=OPENCLAW_TIMEOUT)
        subparser.add_argument("--max-domain-parallel", type=positive_int, default=MAX_DOMAIN_PARALLEL)
        subparser.add_argument("--filter-timeout", type=positive_int, default=FILTER_TIMEOUT)
        subparser.add_argument("--filter-workers", type=positive_int, default=FILTER_WORKERS)

    for action in ("run", "cleanup", "reset", "status"):
        add_common_args(subparsers.add_parser(action))

    return parser


def init_config(args):
    global WORKSPACE_HUB, WORKSPACE_BASE, RESULTS_DIR, SKILLS_SOURCE
    global GEN_OPENCLAW_MODEL, OPENCLAW_TIMEOUT, MAX_DOMAIN_PARALLEL
    global LITELLM_API_BASE, LITELLM_API_KEY, FILTER_MODEL, FILTER_TIMEOUT, FILTER_WORKERS

    WORKSPACE_HUB = args.workspace_hub
    WORKSPACE_BASE = args.workspace_base
    RESULTS_DIR = args.results_dir
    SKILLS_SOURCE = args.skills_source

    GEN_OPENCLAW_MODEL = args.openclaw_model
    OPENCLAW_TIMEOUT = args.openclaw_timeout
    MAX_DOMAIN_PARALLEL = args.max_domain_parallel

    LITELLM_API_BASE = os.getenv("FILTER_API_BASE")
    LITELLM_API_KEY = os.getenv("FILTER_API_KEY")
    FILTER_MODEL = os.getenv("FILTER_MODEL")
    FILTER_TIMEOUT = args.filter_timeout
    FILTER_WORKERS = args.filter_workers


def validate_config(action: str):
    if WORKSPACE_HUB is None:
        raise ValueError("Missing --workspace-hub")
    if not WORKSPACE_HUB.exists():
        raise FileNotFoundError(f"workspace_hub does not exist: {WORKSPACE_HUB}")

    if action == "run":
        if WORKSPACE_BASE is None:
            raise ValueError("Missing --workspace-base in run mode")
        if RESULTS_DIR is None:
            raise ValueError("Missing --results-dir in run mode")
        if SKILLS_SOURCE is None:
            raise ValueError("Missing --skills-source in run mode")
        if not GEN_OPENCLAW_MODEL:
            raise ValueError("Missing GEN_OPENCLAW_MODEL (set it in .env or pass it via --openclaw-model)")
        if not LITELLM_API_BASE:
            raise ValueError("Missing FILTER_API_BASE (please set it in .env)")
        if not LITELLM_API_KEY:
            raise ValueError("Missing FILTER_API_KEY (please set it in .env)")
        if not FILTER_MODEL:
            raise ValueError("Missing FILTER_MODEL (please set it in .env)")


# ============================================================
# Utility helpers
# ============================================================
def list_workspace_dirs() -> list[Path]:
    assert WORKSPACE_HUB is not None
    return sorted(
        d for d in WORKSPACE_HUB.iterdir()
        if d.is_dir() and (d / INPUT_FILENAME).exists()
    )


def get_workspace_path(ws_name: str) -> Path:
    assert WORKSPACE_BASE is not None
    return WORKSPACE_BASE / f"{ws_name}_workspace"


def get_agent_name(ws_name: str) -> str:
    return f"fg_{ws_name}"


def sync_workspace(ws_dir: Path, tmp_ws: Path):
    assert SKILLS_SOURCE is not None

    tmp_ws.mkdir(parents=True, exist_ok=True)

    for item in ws_dir.iterdir():
        if item.name == LOG_FILENAME:
            continue
        target = tmp_ws / item.name
        try:
            if item.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)
        except Exception as e:
            print(f"  ⚠️ [{ws_dir.name}] Failed to copy file {item.name}: {e}")

    if SKILLS_SOURCE.exists():
        target_skills = tmp_ws / "skills"
        target_skills.mkdir(parents=True, exist_ok=True)
        for skill_dir in SKILLS_SOURCE.iterdir():
            if not skill_dir.is_dir():
                continue
            target_skill = target_skills / skill_dir.name
            try:
                if target_skill.is_symlink() or target_skill.is_file():
                    target_skill.unlink()
                elif target_skill.exists():
                    shutil.rmtree(target_skill)
                target_skill.symlink_to(skill_dir, target_is_directory=True)
            except Exception:
                try:
                    if target_skill.is_symlink() or target_skill.is_file():
                        target_skill.unlink()
                    elif target_skill.exists():
                        shutil.rmtree(target_skill)
                    shutil.copytree(skill_dir, target_skill)
                except Exception as e:
                    print(f"  ⚠️ [{ws_dir.name}] Failed to sync skill {skill_dir.name}: {e}")


def ensure_workspace(ws_dir: Path):
    ws_name = ws_dir.name
    with _setup_workspaces_lock:
        if ws_name in _setup_workspaces:
            return

    tmp_ws = get_workspace_path(ws_name)
    sync_workspace(ws_dir, tmp_ws)

    with _setup_workspaces_lock:
        _setup_workspaces.add(ws_name)


def create_agent(ws_name: str):
    assert GEN_OPENCLAW_MODEL is not None

    agent_name = get_agent_name(ws_name)
    tmp_ws = get_workspace_path(ws_name)
    cmd = [
        "openclaw", "agents", "add", agent_name,
        "--model", GEN_OPENCLAW_MODEL,
        "--workspace", str(tmp_ws),
        "--non-interactive",
    ]
    print(f"  📦 Creating agent: {agent_name}")
    print(f"     workspace: {tmp_ws}")
    with _agent_cli_lock:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create agent {agent_name}: {result.stderr.strip()}")


# ============================================================
# Resume support and logs
# ============================================================
def load_finished_ids(log_file: Path) -> set[str]:
    if not log_file.exists():
        return set()
    done = set()
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                status = rec.get("status", "")
                if status in ("success", "skip"):
                    done.add(rec["id"])
                elif not status and rec.get("success"):
                    done.add(rec["id"])
            except json.JSONDecodeError:
                continue
    return done


def log_result(log_file: Path, rid: str, success: bool, output: str, status: str = ""):
    with _log_lock:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "id": rid,
                "success": success,
                "status": status or ("success" if success else "failed"),
                "output": output[:500],
                "timestamp": datetime.now().isoformat(),
            }, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())


def cleanup_single_agent(agent_name: str, silent: bool = False):
    cmd = ["openclaw", "agents", "delete", agent_name, "--force"]
    with _agent_cli_lock:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if not silent and result.returncode != 0 and "not found" not in result.stderr.lower():
            print(f"     ⚠️ Failed to delete {agent_name}: {result.stderr.strip()}")

    agent_record = Path.home() / ".openclaw" / "agents" / agent_name
    if agent_record.exists():
        try:
            if agent_record.is_dir():
                shutil.rmtree(agent_record)
            else:
                agent_record.unlink()
            if not silent:
                print(f"     🗑️  Cleaned local record: {agent_record}")
        except Exception as e:
            if not silent:
                print(f"     ⚠️ Failed to clean local record: {e}")


def cleanup_agents():
    workspace_dirs = list_workspace_dirs()
    print(f"🧹 Deleting {len(workspace_dirs)} agents...\n")
    for ws_dir in workspace_dirs:
        agent_name = get_agent_name(ws_dir.name)
        cleanup_single_agent(agent_name)
    print("\n🎉 Cleanup complete!")


# ============================================================
# Stage 1: concurrent prefiltering
# ============================================================
def needs_input_files(query: str) -> bool | None:
    assert LITELLM_API_BASE is not None
    assert LITELLM_API_KEY is not None
    assert FILTER_MODEL is not None

    url = f"{LITELLM_API_BASE.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LITELLM_API_KEY}",
    }
    payload = {
        "model": FILTER_MODEL,
        "messages": [
            {"role": "system", "content": FILTER_SYSTEM_PROMPT},
            {"role": "user", "content": FILTER_USER_PROMPT + query},
        ]
    }
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=FILTER_TIMEOUT) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            answer = result["choices"][0]["message"]["content"].strip().upper()
            if "YES" in answer:
                return True
            elif "NO" in answer:
                return False
            else:
                print(f"  ⚠️ Prefilter returned unexpected content: {answer[:120]}")
                return None
    except Exception as e:
        print(f"  ⚠️ Prefilter request failed: model={FILTER_MODEL}, error={e}")
        return None


def filter_one(rec: dict) -> tuple[str, bool | None]:
    rid = rec["id"]
    query = rec["result"]
    need = needs_input_files(query)
    return rid, need


def run_prefilter(todo: list[dict], ws_name: str, log_file: Path) -> tuple[list[dict], int]:
    need_generate = []
    skip_count = 0

    with tqdm(total=len(todo), desc=f"  {ws_name} prefilter", unit="q",
              bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}] {postfix}") as pbar:
        with ThreadPoolExecutor(max_workers=FILTER_WORKERS) as executor:
            future_to_rec = {
                executor.submit(filter_one, rec): rec
                for rec in todo
            }
            for future in as_completed(future_to_rec):
                rec = future_to_rec[future]
                try:
                    rid, need = future.result()
                    if need is False:
                        log_result(log_file, rid, True,
                                   "[SKIP] Prefilter determined that no input files need to be generated",
                                   status="skip")
                        skip_count += 1
                    else:
                        need_generate.append(rec)
                    pbar.set_postfix(need=len(need_generate),
                                     skip=skip_count, refresh=True)
                except Exception as e:
                    need_generate.append(rec)
                    pbar.write(f"  ⚠️ Prefilter error for {rec['id']}: {e}")
                pbar.update(1)

    return need_generate, skip_count


# ============================================================
# Stage 2: serial OpenClaw calls to generate files
# ============================================================
def run_single_task(agent_name: str, session_id: str, message: str,
                    ws_name: str, task_idx: int) -> dict:
    start_time = time.time()

    cmd = [
        "openclaw", "agent",
        "--agent", agent_name,
        "--session-id", session_id,
        "--message", message,
        "--thinking", "high",
        "--timeout", str(OPENCLAW_TIMEOUT),
        "--json",
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=OPENCLAW_TIMEOUT + 60,
            env={**os.environ},
        )
        elapsed = time.time() - start_time
        success = result.returncode == 0
        status = "success" if success else "failed"
        icon = "✅" if success else "❌"
        print(f"  {icon} [{ws_name}] task {task_idx:03d} ({elapsed:.1f}s) - {status}")

        return {
            "domain": ws_name,
            "task_idx": task_idx,
            "session_id": session_id,
            "message": message[:200],
            "status": status,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "elapsed_seconds": round(elapsed, 2),
            "timestamp": datetime.now().isoformat(),
        }
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        print(f"  ⏰ [{ws_name}] task {task_idx:03d} ({elapsed:.1f}s) - timeout")
        return {
            "domain": ws_name,
            "task_idx": task_idx,
            "session_id": session_id,
            "message": message[:200],
            "status": "timeout",
            "returncode": -1,
            "stdout": "",
            "stderr": "TimeoutExpired",
            "elapsed_seconds": round(elapsed, 2),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"  💥 [{ws_name}] task {task_idx:03d} ({elapsed:.1f}s) - error: {e}")
        return {
            "domain": ws_name,
            "task_idx": task_idx,
            "session_id": session_id,
            "message": message[:200],
            "status": "error",
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
            "elapsed_seconds": round(elapsed, 2),
            "timestamp": datetime.now().isoformat(),
        }


# ============================================================
# Process a single workspace (domain)
# ============================================================
def process_workspace(ws_dir: Path) -> list[dict]:
    assert RESULTS_DIR is not None

    ws_name = ws_dir.name
    agent_name = get_agent_name(ws_name)
    tmp_ws = get_workspace_path(ws_name)
    input_file = ws_dir / INPUT_FILENAME
    log_file = ws_dir / LOG_FILENAME

    if not input_file.exists():
        print(f"\n⏭️  {ws_name}: no {INPUT_FILENAME}, skipping")
        return []

    records = []
    with open(input_file, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  ⚠️ [{ws_name}] JSON parse failed for line {line_no} in the input file: {e}")
                continue

            rid = rec.get("id")
            result = rec.get("result", "")
            if not rid:
                print(f"  ⚠️ [{ws_name}] Missing id on line {line_no} in the input file, skipped")
                continue
            if result and not result.startswith("[ERROR]"):
                records.append(rec)

    if not records:
        print(f"\n⏭️  {ws_name}: no valid records, skipping")
        return []

    finished_ids = load_finished_ids(log_file)
    todo = [r for r in records if r["id"] not in finished_ids]

    if not todo:
        print(f"\n✅ {ws_name}: all {len(records)} records are already done, skipping")
        return []

    print(f"\n📦 {ws_name}: {len(records)} records, {len(finished_ids)} completed, {len(todo)} pending")

    need_generate, skip_count = run_prefilter(todo, ws_name, log_file)
    print(f"   📊 Prefilter complete: {len(need_generate)} need generation, {skip_count} skipped")

    ensure_workspace(ws_dir)

    if not need_generate:
        print(f"   ✅ {ws_name}: everything was skipped, no need to call OpenClaw")
        return []

    domain_results_dir = RESULTS_DIR / ws_name
    domain_results_dir.mkdir(parents=True, exist_ok=True)

    results = []
    done_count = 0
    fail_count = 0

    for idx, rec in enumerate(need_generate, start=1):
        rid = rec["id"]
        query = rec["result"]

        try:
            cleanup_single_agent(agent_name, silent=True)
            create_agent(ws_name)

            session_id = f"fg_{rid}_{uuid.uuid4().hex[:8]}"
            prompt = PROMPT_TEMPLATE.format(workspace=tmp_ws, query=query)
            task_result = run_single_task(agent_name, session_id, prompt, ws_name, idx)
            results.append(task_result)

            stdout_output = task_result.get("stdout", "")
            is_empty_payloads = '"payloads": []' in stdout_output
            actual_success = task_result["status"] == "success" and not is_empty_payloads

            if task_result["status"] == "success" and is_empty_payloads:
                actual_status = "empty_payloads"
            else:
                actual_status = task_result["status"]

            task_result["status"] = actual_status
            task_result["success"] = actual_success

            log_result(log_file, rid, actual_success,
                       stdout_output[:500] or task_result.get("stderr", "")[:500],
                       status=actual_status)

            if actual_success:
                done_count += 1
            else:
                fail_count += 1

            session_dir = Path.home() / ".openclaw" / "agents" / agent_name / "sessions"
            if session_dir.exists() and session_dir.is_dir():
                jsonl_files = sorted(fp for fp in session_dir.glob("*.jsonl") if fp.is_file())
                for file_idx, fp in enumerate(jsonl_files):
                    try:
                        target_path = domain_results_dir / f"{session_id}_{file_idx}.jsonl"
                        shutil.copy2(str(fp), str(target_path))
                    except Exception as e:
                        print(f"  ⚠️ [{ws_name}] Failed to copy conversation record {fp.name}: {e}")
        finally:
            cleanup_single_agent(agent_name, silent=True)

    print(f"   → {ws_name} this run: generated {done_count}, skipped {skip_count}, failed {fail_count}")
    return results


# ============================================================
# Main flow: execute concurrently
# ============================================================
def reset_logs():
    workspace_dirs = list_workspace_dirs()
    count = 0
    for ws_dir in workspace_dirs:
        log_file = ws_dir / LOG_FILENAME
        if log_file.exists():
            log_file.unlink()
            count += 1
            print(f"  🗑️  Cleared: {log_file}")
    if count:
        print(f"\n✅ Cleared {count} log files. The next run will start from scratch")
    else:
        print("ℹ️  No log files found, nothing to clear")


def show_status():
    workspace_dirs = list_workspace_dirs()
    total_records = 0
    total_done = 0

    print("\n📊 Current progress:")
    print("=" * 60)
    for ws_dir in workspace_dirs:
        ws_name = ws_dir.name
        input_file = ws_dir / INPUT_FILENAME
        log_file = ws_dir / LOG_FILENAME

        if not input_file.exists():
            continue

        records = []
        with open(input_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rec = json.loads(line)
                        if rec.get("result") and not rec["result"].startswith("[ERROR]"):
                            records.append(rec)
                    except json.JSONDecodeError:
                        continue

        total = len(records)
        done = len(load_finished_ids(log_file))
        remaining = total - done
        total_records += total
        total_done += done

        icon = "✅" if remaining == 0 else ("🔄" if done > 0 else "⬜")
        print(f"   {icon} {ws_name}: {done}/{total} (remaining {remaining})")

    print("=" * 60)
    print(f"   Total: {total_done}/{total_records} (remaining {total_records - total_done})")
    print("=" * 60 + "\n")


def run_all():
    assert RESULTS_DIR is not None

    workspace_dirs = list_workspace_dirs()

    if not workspace_dirs:
        print(f"❌ No workspace directories containing {INPUT_FILENAME} were found")
        return

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Benchmark input file generator (batch version, concurrent across workspaces)")
    print(f"  model: {GEN_OPENCLAW_MODEL}")
    print(f"  prefilter model: {FILTER_MODEL}")
    print(f"  prefilter workers: {FILTER_WORKERS}")
    print(f"  cross-workspace concurrency: {MAX_DOMAIN_PARALLEL}")
    print("  within each workspace: serial")
    print(f"  input file: {INPUT_FILENAME}")
    print(f"  workspace_hub: {WORKSPACE_HUB}")
    print(f"  temporary workspace: {WORKSPACE_BASE}")
    print(f"  results directory: {RESULTS_DIR}")
    print(f"  skills source: {SKILLS_SOURCE}")
    print("=" * 60)
    print(f"\n📂 Found {len(workspace_dirs)} workspace directories")

    all_results = []
    start_time = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_DOMAIN_PARALLEL) as executor:
        futures = {
            executor.submit(process_workspace, ws_dir): ws_dir.name
            for ws_dir in workspace_dirs
        }
        for future in concurrent.futures.as_completed(futures):
            ws_name = futures[future]
            try:
                results = future.result()
                all_results.extend(results)
            except Exception as e:
                print(f"💥 Workspace [{ws_name}] execution error: {e}")

    elapsed = time.time() - start_time

    summary_file = RESULTS_DIR / "summary.json"
    summary = {
        "total_workspaces": len(workspace_dirs),
        "this_run_tasks": len(all_results),
        "total_elapsed_seconds": round(elapsed, 2),
        "this_run_success": sum(1 for r in all_results if r["status"] == "success"),
        "this_run_empty_payloads": sum(1 for r in all_results if r["status"] == "empty_payloads"),
        "this_run_failed": sum(1 for r in all_results if r["status"] == "failed"),
        "this_run_timeout": sum(1 for r in all_results if r["status"] == "timeout"),
        "this_run_error": sum(1 for r in all_results if r["status"] == "error"),
        "timestamp": datetime.now().isoformat(),
        "results": all_results,
    }
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print(f"📊 Run complete. Elapsed time: {elapsed:.1f}s")
    print(f"   workspace count: {len(workspace_dirs)}")
    print(f"   tasks in this run: {len(all_results)}")
    print(f"   ✅ success: {summary['this_run_success']}")
    print(f"   ⚪ empty_payloads: {summary['this_run_empty_payloads']}")
    print(f"   ❌ failed: {summary['this_run_failed']}")
    print(f"   ⏰ timeout: {summary['this_run_timeout']}")
    print(f"   💥 error: {summary['this_run_error']}")
    print(f"   📄 summary: {summary_file}")
    if summary['this_run_empty_payloads'] or summary['this_run_failed'] or summary['this_run_timeout'] or summary['this_run_error']:
        print("   💡 Rerunning the script will automatically resume failed/timeout/error/empty_payloads records")
    print(f"{'=' * 60}")


# ============================================================
# Entry point
# ============================================================
def main():
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--env-file", type=Path, default=Path(".env"))
    pre_args, _ = pre_parser.parse_known_args()
    load_dotenv(pre_args.env_file)

    parser = build_parser()
    args = parser.parse_args()

    load_dotenv(args.env_file)
    init_config(args)
    validate_config(args.action)

    action = args.action.lower()
    if action == "run":
        run_all()
    elif action == "cleanup":
        cleanup_agents()
    elif action == "reset":
        reset_logs()
    elif action == "status":
        show_status()
    else:
        print(f"❌ Unknown command: {action}")
        sys.exit(1)


if __name__ == "__main__":
    main()
