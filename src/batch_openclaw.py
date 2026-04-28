#!/usr/bin/env python3
"""
Usage:
  python batch_openclaw.py run      # Execute all tasks
  python batch_openclaw.py cleanup  # Manually clean up leftover agents
  python batch_openclaw.py reset    # Clear checkpoint records and restart from scratch
  python batch_openclaw.py status   # Show current progress
"""

import argparse
import subprocess
import concurrent.futures
import json
import sys
import os
import time
import shutil
import threading
import random
from pathlib import Path
from datetime import datetime

# ======================== Runtime config (initialized from args and .env) ========================
OPENCLAW_MODEL: str | None = None
WORKSPACE_HUB_DIR: Path | None = None
WORKSPACE_BASE: Path | None = None
RESULTS_DIR: Path | None = None
MAX_DOMAIN_PARALLEL = 5
TIMEOUT_SECONDS = 1200
SKILL_MIN = 3
SKILL_MAX = 3

CHECKPOINT_FILE: Path | None = None
SKILLS_POOL_DIR: Path | None = None
SKILLS_TO_REMOVE: set[str] = {"synthetic-test-files"}
REQUIRED_SKILLS: set[str] = {

}

# ======================== Global state ========================
_setup_workspaces = set()
_setup_workspaces_lock = threading.Lock()

# Checkpoint write lock
_checkpoint_lock = threading.Lock()

# CLI lock: prevent registry corruption from concurrent agent add/delete operations
_agent_cli_lock = threading.Lock()

# Domain task data, loaded lazily in main()
DOMAINS = {}


# ======================== Argument initialization ========================

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
    parser = argparse.ArgumentParser(description="Batch script for running OpenClaw tasks")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Path to the .env file")

    subparsers = parser.add_subparsers(dest="action", required=True)

    def add_common_args(subparser: argparse.ArgumentParser):
        subparser.add_argument("--workspace-hub", type=Path, required=True, help="Root directory of the source workspaces")
        subparser.add_argument("--workspace-base", type=Path, help="Root directory for temporary workspaces (required for run)")
        subparser.add_argument("--results-dir", type=Path, help="Results directory (required for run)")
        subparser.add_argument("--openclaw-model", type=str, default=os.getenv("OPENCLAW_MODEL"), help="Model name, defaults to the value from .env")
        subparser.add_argument("--openclaw-timeout", type=positive_int, default=1200, help="Timeout per task")
        subparser.add_argument("--max-domain-parallel", type=positive_int, default=5, help="Concurrency across domains")
        subparser.add_argument("--skills-pool", type=Path, help="Optional skills pool directory")
        subparser.add_argument("--skill-min", type=positive_int, default=3, help="Minimum number of randomly selected skills")
        subparser.add_argument("--skill-max", type=positive_int, default=3, help="Maximum number of randomly selected skills")

    for action in ("run", "cleanup", "reset", "status"):
        add_common_args(subparsers.add_parser(action))

    return parser

def init_config(args):
    global OPENCLAW_MODEL, WORKSPACE_HUB_DIR, WORKSPACE_BASE, RESULTS_DIR
    global MAX_DOMAIN_PARALLEL, TIMEOUT_SECONDS, SKILL_MIN, SKILL_MAX
    global CHECKPOINT_FILE, SKILLS_POOL_DIR

    OPENCLAW_MODEL = args.openclaw_model
    WORKSPACE_HUB_DIR = args.workspace_hub
    WORKSPACE_BASE = args.workspace_base
    RESULTS_DIR = args.results_dir

    MAX_DOMAIN_PARALLEL = args.max_domain_parallel
    TIMEOUT_SECONDS = args.openclaw_timeout
    SKILL_MIN = args.skill_min
    SKILL_MAX = args.skill_max

    if RESULTS_DIR:
        CHECKPOINT_FILE = RESULTS_DIR / "checkpoint.jsonl"
    SKILLS_POOL_DIR = args.skills_pool

def validate_config(action: str):
    if not WORKSPACE_HUB_DIR:
        raise ValueError("Missing --workspace-hub")
    if not WORKSPACE_HUB_DIR.exists():
        raise FileNotFoundError(f"workspace_hub does not exist: {WORKSPACE_HUB_DIR}")

    if action == "run":
        if not WORKSPACE_BASE:
            raise ValueError("Missing --workspace-base in run mode")
        if not RESULTS_DIR:
            raise ValueError("Missing --results-dir in run mode")
        if not OPENCLAW_MODEL:
            raise ValueError("Missing OPENCLAW_MODEL (set it in .env or pass it via --openclaw-model)")


# ======================== Checkpoint management ========================

def load_checkpoint() -> set:
    """Load completed tasks, including success/timeout/error/failed."""
    completed = set()
    if CHECKPOINT_FILE is None or not CHECKPOINT_FILE.exists():
        return completed

    with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                domain = record.get("domain", "")
                task_idx = record.get("task_idx", -1)
                status = record.get("status", "")
                
                # Skip anything that has already been attempted to avoid infinite retry loops.
                if status in ("success", "failed", "timeout", "error") and domain and task_idx >= 0:
                    completed.add(f"{domain}::{task_idx}")
            except Exception:
                continue
    return completed


def save_checkpoint(result: dict):
    with _checkpoint_lock:
        if RESULTS_DIR:
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        if CHECKPOINT_FILE:
            with open(CHECKPOINT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())


def reset_checkpoint():
    if CHECKPOINT_FILE and CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        print(f"✅ Cleared checkpoint file: {CHECKPOINT_FILE}")
    else:
        print("ℹ️  Checkpoint file does not exist, nothing to clear")


def show_status():
    completed = load_checkpoint()
    total_tasks = sum(len(msgs) for msgs in DOMAINS.values())

    domain_completed = {}
    for key in completed:
        domain = key.split("::")[0]
        domain_completed[domain] = domain_completed.get(domain, 0) + 1

    print("\n📊 Current progress:")
    print(f"{'='*50}")
    print(f"   Total tasks: {total_tasks}")
    print(f"   Completed: {len(completed)}")
    print(f"   Remaining: {total_tasks - len(completed)}")
    print(f"{'='*50}")

    for domain, messages in sorted(DOMAINS.items()):
        total = len(messages)
        done = domain_completed.get(domain, 0)
        remaining = total - done
        icon = "✅" if remaining == 0 else "🔄" if done > 0 else "⬜"
        print(f"   {icon} {domain}: {done}/{total} (remaining {remaining})")
    print(f"{'='*50}\n")


# ======================== Task definitions ========================

def get_domains_data():
    domains = {}
    if WORKSPACE_HUB_DIR is None or not WORKSPACE_HUB_DIR.exists():
        print(f"❌ Data directory not found: {WORKSPACE_HUB_DIR}")
        return domains

    for domain_dir in WORKSPACE_HUB_DIR.iterdir():
        if not domain_dir.is_dir():
            continue

        queries_file = domain_dir / "queries_persona.jsonl"
        if not queries_file.exists():
            continue

        domain_name = domain_dir.name
        tasks = []
        with open(queries_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if "result" in data:
                        tasks.append(data["result"])
                except Exception:
                    pass

        if tasks:
            domains[domain_name] = tasks

    return domains


# ======================== Core logic ========================

def get_workspace_path(domain: str) -> str:
    return str(WORKSPACE_BASE / f"{domain}_workspace")


def _remove_path(path: Path):
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)


def prepare_workspace_skills(domain: str, workspace_path: Path):
    skills_dir = workspace_path / "skills"
    if not skills_dir.exists() or not skills_dir.is_dir():
        return

    for skill_name in SKILLS_TO_REMOVE:
        try:
            _remove_path(skills_dir / skill_name)
        except Exception as e:
            print(f"  ⚠️ [{domain}] Failed to remove skill {skill_name}: {e}")

    if SKILLS_POOL_DIR is None or not SKILLS_POOL_DIR.exists() or not SKILLS_POOL_DIR.is_dir():
        print(f"  ⚠️ [{domain}] Skills pool directory is missing or not provided: {SKILLS_POOL_DIR}")
        return

    pool_skill_names = [
        item.name
        for item in SKILLS_POOL_DIR.iterdir()
        if item.exists() or item.is_symlink()
    ]
    pool_skill_set = set(pool_skill_names)

    missing_required = sorted(REQUIRED_SKILLS - pool_skill_set)
    if missing_required:
        print(f"  ⚠️ [{domain}] Missing required skills: {', '.join(missing_required)}")

    required_skills = REQUIRED_SKILLS & pool_skill_set
    target_total = random.randint(SKILL_MIN, SKILL_MAX)
    extra_needed = max(0, target_total - len(required_skills))
    sample_candidates = [name for name in pool_skill_names if name not in required_skills]
    sampled_skills = set(random.sample(sample_candidates, min(len(sample_candidates), extra_needed)))
    selected_skills = sampled_skills | required_skills

    for skill_name in selected_skills:
        source = SKILLS_POOL_DIR / skill_name
        target = skills_dir / skill_name
        if target.exists() or target.is_symlink():
            continue
        try:
            target.symlink_to(source, target_is_directory=source.is_dir())
        except Exception as e:
            print(f"  ⚠️ [{domain}] Failed to create skill symlink {skill_name}: {e}")


def ensure_workspace(domain: str):
    """Ensure the physical workspace is prepared by copying base files once."""
    with _setup_workspaces_lock:
        if domain in _setup_workspaces:
            return

    ws = get_workspace_path(domain)
    os.makedirs(ws, exist_ok=True)

    source_dir = WORKSPACE_HUB_DIR / domain
    if source_dir.exists():
        for item in source_dir.iterdir():
            if item.name in {"queries_persona.jsonl", "queries.jsonl", "tmp_benchmark_queries.jsonl"}:
                continue
            target = Path(ws) / item.name
            try:
                if item.is_dir():
                    if not target.exists():
                        shutil.copytree(item, target, symlinks=True)
                else:
                    if not target.exists():
                        shutil.copy2(item, target, follow_symlinks=False)
            except Exception as e:
                print(f"  ⚠️ [{domain}] Failed to copy workspace file {item.name}: {e}")

    prepare_workspace_skills(domain, Path(ws))

    with _setup_workspaces_lock:
        _setup_workspaces.add(domain)


def create_agent(domain: str):
    """Create a brand-new agent."""
    ws = get_workspace_path(domain)
    cmd = [
        "openclaw", "agents", "add", domain,
        "--model", str(OPENCLAW_MODEL),
        "--workspace", ws,
        "--non-interactive",
    ]
    with _agent_cli_lock:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ❌ [{domain}] Failed to create agent: {result.stderr.strip()}")


def cleanup_single_agent(domain: str, silent: bool = False):
    """Destroy an agent completely to avoid leftover zombie processes."""
    # 1. Try deleting it via the CLI command.
    cmd = ["openclaw", "agents", "delete", domain, "--force"]
    with _agent_cli_lock:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if not silent and result.returncode != 0 and "not found" not in result.stderr.lower():
            print(f"  ⚠️ [{domain}] Agent deletion warning: {result.stderr.strip()}")

    # 2. Physically remove leftover config records and session directories.
    agent_record_path = Path.home() / ".openclaw" / "agents" / domain
    if agent_record_path.exists():
        try:
            shutil.rmtree(agent_record_path)
            if not silent:
                print(f"  🗑️ [{domain}] Cleaned local isolated records")
        except Exception:
            pass


def run_single_task(domain: str, task_idx: int, message: str) -> dict:
    """Run a single task."""
    session_id = f"{domain}_task_{task_idx:03d}"
    start_time = time.time()

    cmd = [
        "openclaw", "agent",
        "--agent", domain,
        "--session-id", session_id,
        "--message", message,
        "--thinking", "high",
        "--timeout", str(TIMEOUT_SECONDS),
        "--json",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS + 60,
        )
        elapsed = time.time() - start_time
        success = result.returncode == 0
        status = "success" if success else "failed"
        icon = "✅" if success else "❌"

        print(f"  {icon} [{domain}] task {task_idx:03d} ({elapsed:.1f}s) - {status}")

        return {
            "domain": domain,
            "task_idx": task_idx,
            "session_id": session_id,
            "message": message,
            "status": status,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "elapsed_seconds": round(elapsed, 2),
            "timestamp": datetime.now().isoformat(),
        }
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        print(f"  ⏰ [{domain}] task {task_idx:03d} ({elapsed:.1f}s) - timeout")
        return {
            "domain": domain,
            "task_idx": task_idx,
            "session_id": session_id,
            "message": message,
            "status": "timeout",
            "returncode": -1,
            "stdout": "",
            "stderr": "TimeoutExpired",
            "elapsed_seconds": round(elapsed, 2),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"  💥 [{domain}] task {task_idx:03d} ({elapsed:.1f}s) - error: {e}")
        return {
            "domain": domain,
            "task_idx": task_idx,
            "session_id": session_id,
            "message": message,
            "status": "error",
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
            "elapsed_seconds": round(elapsed, 2),
            "timestamp": datetime.now().isoformat(),
        }


def run_domain_tasks(domain: str, messages: list[str], completed: set) -> list[dict]:
    results = []

    pending_indices = [
        idx for idx in range(len(messages))
        if f"{domain}::{idx}" not in completed
    ]

    if not pending_indices:
        print(f"\n⏭️  Domain [{domain}] has already completed all tasks, skipping")
        return results

    print(f"\n🚀 Domain [{domain}] has {len(pending_indices)} remaining tasks to run...")

    ensure_workspace(domain)

    domain_results_dir = RESULTS_DIR / domain
    domain_results_dir.mkdir(parents=True, exist_ok=True)
    session_dir = Path.home() / ".openclaw" / "agents" / domain / "sessions"

    for idx in pending_indices:
        msg = messages[idx]

        # Core lifecycle: before each task, clear leftovers from the previous run and rebuild a clean agent environment.
        cleanup_single_agent(domain, silent=True)
        create_agent(domain)

        result = run_single_task(domain, idx, msg)
        results.append(result)
        save_checkpoint(result)

        # Copy conversation records. Because a fresh agent is created each time, the session directory should only contain files from this task.
        session_id = f"{domain}_task_{idx:03d}"
        if session_dir.exists() and session_dir.is_dir():
            jsonl_files = sorted(f for f in session_dir.glob("*.jsonl") if f.is_file())
            for file_idx, file_path in enumerate(jsonl_files):
                try:
                    target_path = domain_results_dir / f"{session_id}_{file_idx}.jsonl"
                    shutil.copy2(str(file_path), str(target_path))
                except Exception:
                    pass

        cleanup_single_agent(domain, silent=True)

    return results


def run_all():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    completed = load_checkpoint()
    total_tasks = sum(len(msgs) for msgs in DOMAINS.values())
    completed_count = len(completed)
    remaining_count = total_tasks - completed_count

    print(f"📋 {len(DOMAINS)} domains, {total_tasks} tasks in total")
    if completed_count > 0:
        print(f"📌 Resumed from checkpoint: {completed_count} completed, {remaining_count} remaining")
    print(f"⚙️  Cross-domain concurrency: {MAX_DOMAIN_PARALLEL}")
    print(f"📂 Results directory: {RESULTS_DIR}")
    print(f"📝 Checkpoint: {CHECKPOINT_FILE}\n")

    if remaining_count == 0:
        print("🎉 All tasks are already complete. Run the reset command if you want to execute them again.")
        return

    all_results = []
    start_time = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_DOMAIN_PARALLEL) as executor:
        futures = {
            executor.submit(run_domain_tasks, domain, messages, completed): domain
            for domain, messages in DOMAINS.items()
        }
        for future in concurrent.futures.as_completed(futures):
            domain = futures[future]
            try:
                results = future.result()
                all_results.extend(results)
            except Exception as e:
                print(f"💥 Domain [{domain}] execution error: {e}")

    elapsed = time.time() - start_time
    final_completed = load_checkpoint()

    summary_file = RESULTS_DIR / "summary.json"
    summary = {
        "total_tasks": total_tasks,
        "total_completed": len(final_completed),
        "total_elapsed_seconds": round(elapsed, 2),
        "this_run_tasks": len(all_results),
        "this_run_success": sum(1 for r in all_results if r["status"] == "success"),
        "this_run_failed": sum(1 for r in all_results if r["status"] == "failed"),
        "this_run_timeout": sum(1 for r in all_results if r["status"] == "timeout"),
        "this_run_error": sum(1 for r in all_results if r["status"] == "error"),
        "resumed_from_checkpoint": completed_count > 0,
        "timestamp": datetime.now().isoformat(),
        "results": all_results,
    }
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"📊 Run complete. Elapsed time: {elapsed:.1f}s")
    print(f"   📌 Total tasks: {total_tasks}, completed overall: {len(final_completed)}")
    print(f"   ✅ Success: {summary['this_run_success']}")
    print(f"   ❌ Failed/timeout/error: {summary['this_run_failed'] + summary['this_run_timeout'] + summary['this_run_error']}")
    print(f"   📄 Summary log: {summary_file}")
    print(f"{'='*50}")


def cleanup_agents():
    print("🧹 Scanning for leftover agents associated with this batch...\n")
    
    # 1. Get currently registered agents from the CLI.
    result = subprocess.run(["openclaw", "agents", "list"], capture_output=True, text=True)
    existing_agents = set()
    for line in result.stdout.split('\n'):
        line = line.strip()
        if line.startswith("- "):
            # Extract the name, e.g. "- main (default)" -> "main".
            agent_name = line[2:].split()[0]
            existing_agents.add(agent_name)
            
    # 2. Get orphaned leftover agents from the local cache directory.
    local_agents_dir = Path.home() / ".openclaw" / "agents"
    if local_agents_dir.exists() and local_agents_dir.is_dir():
        for d in local_agents_dir.iterdir():
            if d.is_dir():
                existing_agents.add(d.name)

    # 3. Find agents that both belong to this script's domains and still physically exist.
    targets_to_delete = existing_agents.intersection(set(DOMAINS.keys()))
    
    if not targets_to_delete:
        print("🎉 No leftover agents for the current full batch were found. No cleanup needed.")
        return

    print(f"👀 Found {len(targets_to_delete)} related zombie leftovers. Starting targeted cleanup...")
    for domain in targets_to_delete:
        cleanup_single_agent(domain)
        
    print("\n🎉 Cleanup complete. Related system background entries and local records have been fully removed.")


def main():
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--env-file", type=Path, default=Path(".env"))
    pre_args, _ = pre_parser.parse_known_args()
    load_dotenv(pre_args.env_file)

    parser = build_parser()
    args = parser.parse_args()

    # Load arguments again after dotenv variables are available.
    load_dotenv(args.env_file)
    init_config(args)
    validate_config(args.action)

    # Lazily load DOMAINS data.
    global DOMAINS
    DOMAINS = get_domains_data()

    action = args.action.lower()
    if action == "run":
        run_all()
    elif action == "cleanup":
        cleanup_agents()
    elif action == "reset":
        reset_checkpoint()
    elif action == "status":
        show_status()
    else:
        print(f"❌ Unknown command: {action}")
        sys.exit(1)


if __name__ == "__main__":
    main()
