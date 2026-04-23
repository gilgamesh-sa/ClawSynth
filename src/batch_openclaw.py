#!/usr/bin/env python3
"""
批量运行 OpenClaw 任务脚本

架构更新：
  - 核心变更：【每跑一次 Task，彻底销毁并重建 Agent】。确保上下文 100% 隔离，杜绝任何僵尸进程对后续 Task 或日志文件的污染。
  - 每个领域对应 1 个独立 workspace 物理目录。
  - 领域间并发，领域内串行执行。
  - 支持断点续跑：使用 checkpoint 文件记录已完成的任务，中断后再次运行自动跳过。

用法：
  python batch_openclaw.py run      # 执行所有任务
  python batch_openclaw.py cleanup  # 手动清理残留 agents
  python batch_openclaw.py reset    # 清除 checkpoint 记录，从头开始跑
  python batch_openclaw.py status   # 查看当前进度
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

# ======================== 运行时配置（由参数和 .env 初始化） ========================
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

# ======================== 全局状态 ========================
_setup_workspaces = set()
_setup_workspaces_lock = threading.Lock()

# checkpoint 写入锁
_checkpoint_lock = threading.Lock()

# CLI 锁：防止高并发增删 Agent 导致 openclaw 系统注册表竞争损坏
_agent_cli_lock = threading.Lock()

# 领域任务数据，由 main 函数中延迟加载
DOMAINS = {}


# ======================== 参数初始化 ========================

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
        raise argparse.ArgumentTypeError("参数必须为正整数")
    return ivalue

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="批量运行 OpenClaw 任务脚本")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help=".env 文件路径")

    subparsers = parser.add_subparsers(dest="action", required=True)

    def add_common_args(subparser: argparse.ArgumentParser):
        subparser.add_argument("--workspace-hub", type=Path, required=True, help="原始 workspace 根目录")
        subparser.add_argument("--workspace-base", type=Path, help="临时 workspace 根目录（run 时必填）")
        subparser.add_argument("--results-dir", type=Path, help="结果目录（run 时必填）")
        subparser.add_argument("--openclaw-model", type=str, default=os.getenv("OPENCLAW_MODEL"), help="模型名，默认通过 .env 配置")
        subparser.add_argument("--openclaw-timeout", type=positive_int, default=1200, help="单任务超时")
        subparser.add_argument("--max-domain-parallel", type=positive_int, default=5, help="领域间并发数")
        subparser.add_argument("--skills-pool", type=Path, help="可选 skills 池目录")
        subparser.add_argument("--skill-min", type=positive_int, default=3, help="随机抽取技能最小值")
        subparser.add_argument("--skill-max", type=positive_int, default=3, help="随机抽取技能最大值")

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
        raise ValueError("缺少 --workspace-hub")
    if not WORKSPACE_HUB_DIR.exists():
        raise FileNotFoundError(f"workspace_hub 不存在: {WORKSPACE_HUB_DIR}")

    if action == "run":
        if not WORKSPACE_BASE:
            raise ValueError("run 模式缺少 --workspace-base")
        if not RESULTS_DIR:
            raise ValueError("run 模式缺少 --results-dir")
        if not OPENCLAW_MODEL:
            raise ValueError("缺少 OPENCLAW_MODEL（请在 .env 中配置或通过 --openclaw-model 传入）")


# ======================== Checkpoint 管理 ========================

def load_checkpoint() -> set:
    """加载已完成的任务（包含 success/timeout/error/failed）"""
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
                
                # 只要执行过就跳过，避免陷入死循环
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
        print(f"✅ 已清除 checkpoint 文件: {CHECKPOINT_FILE}")
    else:
        print(f"ℹ️  checkpoint 文件不存在，无需清除")


def show_status():
    completed = load_checkpoint()
    total_tasks = sum(len(msgs) for msgs in DOMAINS.values())

    domain_completed = {}
    for key in completed:
        domain = key.split("::")[0]
        domain_completed[domain] = domain_completed.get(domain, 0) + 1

    print(f"\n📊 当前进度:")
    print(f"{'='*50}")
    print(f"   总任务数: {total_tasks}")
    print(f"   已完成数: {len(completed)}")
    print(f"   剩余任务: {total_tasks - len(completed)}")
    print(f"{'='*50}")

    for domain, messages in sorted(DOMAINS.items()):
        total = len(messages)
        done = domain_completed.get(domain, 0)
        remaining = total - done
        icon = "✅" if remaining == 0 else "🔄" if done > 0 else "⬜"
        print(f"   {icon} {domain}: {done}/{total} (剩余 {remaining})")
    print(f"{'='*50}\n")


# ======================== 任务定义 ========================

def get_domains_data():
    domains = {}
    if WORKSPACE_HUB_DIR is None or not WORKSPACE_HUB_DIR.exists():
        print(f"❌ 找不到数据目录: {WORKSPACE_HUB_DIR}")
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


# ======================== 核心逻辑 ========================

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
            print(f"  ⚠️ [{domain}] 删除 skill 失败 {skill_name}: {e}")

    if SKILLS_POOL_DIR is None or not SKILLS_POOL_DIR.exists() or not SKILLS_POOL_DIR.is_dir():
        print(f"  ⚠️ [{domain}] skills 池目录不存在或未提供: {SKILLS_POOL_DIR}")
        return

    pool_skill_names = [
        item.name
        for item in SKILLS_POOL_DIR.iterdir()
        if item.exists() or item.is_symlink()
    ]
    pool_skill_set = set(pool_skill_names)

    missing_required = sorted(REQUIRED_SKILLS - pool_skill_set)
    if missing_required:
        print(f"  ⚠️ [{domain}] 必选 skills 缺失: {', '.join(missing_required)}")

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
            print(f"  ⚠️ [{domain}] 创建 skill 软链接失败 {skill_name}: {e}")


def ensure_workspace(domain: str):
    """确保物理工作区已准备好（拷贝基准文件），只需跑一次即可"""
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
                print(f"  ⚠️ [{domain}] 拷贝工作区文件失败 {item.name}: {e}")

    prepare_workspace_skills(domain, Path(ws))

    with _setup_workspaces_lock:
        _setup_workspaces.add(domain)


def create_agent(domain: str):
    """创建一个崭新的 Agent"""
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
            print(f"  ❌ [{domain}] Agent 创建失败: {result.stderr.strip()}")


def cleanup_single_agent(domain: str, silent: bool = False):
    """彻底销毁 Agent，避免残留僵尸进程"""
    # 1. 尝试调用命令删除
    cmd = ["openclaw", "agents", "delete", domain, "--force"]
    with _agent_cli_lock:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if not silent and result.returncode != 0 and "not found" not in result.stderr.lower():
            print(f"  ⚠️ [{domain}] Agent 删除异常: {result.stderr.strip()}")

    # 2. 物理清除残留配置记录和 Session 目录
    agent_record_path = Path.home() / ".openclaw" / "agents" / domain
    if agent_record_path.exists():
        try:
            shutil.rmtree(agent_record_path)
            if not silent:
                print(f"  🗑️ [{domain}] 已清理隔离文件记录")
        except Exception:
            pass


def run_single_task(domain: str, task_idx: int, message: str) -> dict:
    """执行单个任务"""
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
        print(f"\n⏭️  领域 [{domain}] 所有任务已完成，跳过")
        return results

    print(f"\n🚀 领域 [{domain}] 剩余 {len(pending_indices)} 个任务待执行...")

    ensure_workspace(domain)

    domain_results_dir = RESULTS_DIR / domain
    domain_results_dir.mkdir(parents=True, exist_ok=True)
    session_dir = Path.home() / ".openclaw" / "agents" / domain / "sessions"

    for idx in pending_indices:
        msg = messages[idx]

        # 【核心生命周期】每次 Task 开始前清理上次残留，并重建纯净 Agent 环境
        cleanup_single_agent(domain, silent=True)
        create_agent(domain)

        result = run_single_task(domain, idx, msg)
        results.append(result)
        save_checkpoint(result)

        # 拷贝对话记录。因为每次建了新 Agent，此时 session_dir 里理论上只有本次任务生成的文件
        session_id = f"{domain}_task_{idx:03d}"
        if session_dir.exists() and session_dir.is_dir():
            jsonl_files = sorted(f for f in session_dir.glob("*.jsonl") if f.is_file())
            for file_idx, file_path in enumerate(jsonl_files):
                try:
                    target_path = domain_results_dir / f"{session_id}_{file_idx}.jsonl"
                    shutil.copy2(str(file_path), str(target_path))
                except Exception:
                    pass

        # 【核心生命周期】每次 Task 结束后，立即彻底销毁 Agent，切断任何后台孤儿进程
        cleanup_single_agent(domain, silent=True)

    return results


def run_all():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    completed = load_checkpoint()
    total_tasks = sum(len(msgs) for msgs in DOMAINS.values())
    completed_count = len(completed)
    remaining_count = total_tasks - completed_count

    print(f"📋 共 {len(DOMAINS)} 个领域, {total_tasks} 个任务")
    if completed_count > 0:
        print(f"📌 从 checkpoint 恢复: 已完成 {completed_count}, 剩余 {remaining_count}")
    print(f"⚙️  领域间并发: {MAX_DOMAIN_PARALLEL}")
    print(f"📂 结果目录: {RESULTS_DIR}")
    print(f"📝 Checkpoint: {CHECKPOINT_FILE}\n")

    if remaining_count == 0:
        print("🎉 所有任务已完成！如需重新执行，请先执行 reset 命令。")
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
                print(f"💥 领域 [{domain}] 执行异常: {e}")

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
    print(f"📊 本次执行完毕！耗时 {elapsed:.1f}s")
    print(f"   📌 总任务: {total_tasks}, 累计完成: {len(final_completed)}")
    print(f"   ✅ 成功: {summary['this_run_success']}")
    print(f"   ❌ 失败/超时/异常: {summary['this_run_failed'] + summary['this_run_timeout'] + summary['this_run_error']}")
    print(f"   📄 汇总日志: {summary_file}")
    print(f"{'='*50}")


def cleanup_agents():
    print("🧹 正在扫描清理属于本批次数据的遗留 Agent...\n")
    
    # 1. 从 CLI 获取当前已注册的 agent
    result = subprocess.run(["openclaw", "agents", "list"], capture_output=True, text=True)
    existing_agents = set()
    for line in result.stdout.split('\n'):
        line = line.strip()
        if line.startswith("- "):
            # 提取名称，形如 "- main (default)" 取 "main"
            agent_name = line[2:].split()[0]
            existing_agents.add(agent_name)
            
    # 2. 从本地缓存记录目录获取残留的孤弃 agent
    local_agents_dir = Path.home() / ".openclaw" / "agents"
    if local_agents_dir.exists() and local_agents_dir.is_dir():
        for d in local_agents_dir.iterdir():
            if d.is_dir():
                existing_agents.add(d.name)

    # 3. 找出既属于当前脚本的 DOMAINS，实际上又存在残留的 Agent
    targets_to_delete = existing_agents.intersection(set(DOMAINS.keys()))
    
    if not targets_to_delete:
        print("🎉 未发现属于当前全量批次的残留 Agent，无需遍历清理！")
        return

    print(f"👀 发现 {len(targets_to_delete)} 个关联僵尸残留，开始极速精准打击...")
    for domain in targets_to_delete:
        cleanup_single_agent(domain)
        
    print("\n🎉 清理完毕！相关的系统后台及本地 records 已彻底抹除。")


def main():
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--env-file", type=Path, default=Path(".env"))
    pre_args, _ = pre_parser.parse_known_args()
    load_dotenv(pre_args.env_file)

    parser = build_parser()
    args = parser.parse_args()

    # 第二次带上 dotenv 的变量去加载参数
    load_dotenv(args.env_file)
    init_config(args)
    validate_config(args.action)

    # 延迟加载 DOMAINS 数据
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
        print(f"❌ 未知命令: {action}")
        sys.exit(1)


if __name__ == "__main__":
    main()
