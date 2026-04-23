#!/usr/bin/env python3
"""
批量调用 OpenClaw 为 benchmark query 预生成所需的输入文件（batch 版本）。

改动原则：
  - 保持旧脚本主体逻辑不变
  - 只调整参数读取方式
  - 大模型相关配置统一从 .env 读取
  - 路径和并发/超时参数统一从 argparse 读取

用法：
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
# 固定文件名
# ============================================================
INPUT_FILENAME = "queries_persona.jsonl"
LOG_FILENAME = "filegen_log.jsonl"

# ============================================================
# 运行时配置（由参数和 .env 初始化）
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
# 全局状态（线程安全）
# ============================================================
_log_lock = threading.Lock()
_setup_workspaces: set[str] = set()
_setup_workspaces_lock = threading.Lock()
_agent_cli_lock = threading.Lock()

# ============================================================
# 给 openclaw 的 prompt 模板
# ============================================================
PROMPT_TEMPLATE = """\
以下是一条用户 query，它在执行时可能需要一些本地文件作为输入（比如图片、音频、文档等）。

请你分析这条 query，找出其中"需要事先存在"的输入文件（即用户说"我有"、"帮我分析/识别/翻译这个文件"等的那些文件），然后帮我把这些文件生成出来。你可以调用 claw-input-file-generator 这个skill进行文件的生成。

如果不存在"需要事先存在"的输入文件，那就跳过这个query!
如果存在"需要事先存在"的输入文件，可以参考 claw-input-file-generator 这个skill来完成输入文件的合成。


注意：
- 只生成"输入文件"，不要生成 query 要求的"输出文件"（如"保存到 xxx"的那些）
- 如果 query 不需要任何预先存在的文件（比如纯文本搜索、纯生成类任务），直接回复"无需生成输入文件"即可
- 所有文件保存到 {workspace} 目录下，保持 query 中的相对路径结构
- 图片文件请用文生图或 canvas 功能生成内容合理的图片
- 音频文件请用语音合成功能生成
- 文本/文档文件直接写入合理的内容

用户 query 如下：
---
{query}
---"""


# ============================================================
# LLM 预筛选：判断 query 是否需要预生成输入文件
# ============================================================
FILTER_SYSTEM_PROMPT = """\
你是一个文件需求分析器。给定一条用户 query，你需要判断它在执行前是否需要"事先存在"的本地输入文件。

注意：有些用户会明确写出文件路径（如 `./receipt.png`），有些用户只会模糊描述文件（如"我有一份销售数据"、"我电脑上有份英文年报"）。两种情况都算需要输入文件！

需要输入文件的例子（明确路径）：
- "帮我识别 ./receipt.png 里的文字" → 需要（./receipt.png 必须事先存在）
- "翻译 ./report_en.pdf 的内容" → 需要（./report_en.pdf 必须事先存在）
- "帮我分析 ./sales_data.csv 的数据" → 需要（./sales_data.csv 必须事先存在）

需要输入文件的例子（模糊描述）：
- "我有一份销售数据，帮我分析一下趋势" → 需要（用户说"我有"，说明文件已存在）
- "我电脑上有份英文年报，帮我翻译" → 需要（用户提到已有的文件）
- "我之前存了一张发票照片，帮我识别上面的内容" → 需要（用户说"我之前存了"）
- "我昨天录的那段会议音频，帮我转成文字" → 需要（用户提到已有的音频）

不需要输入文件的例子：
- "帮我搜索新能源汽车行业资讯" → 不需要（纯搜索/生成类）
- "帮我生成一张宠物医院的宣传图，保存到 ./poster.png" → 不需要（./poster.png 是输出文件，不是输入）
- "帮我写一份行业分析报告" → 不需要（纯生成类）
- "帮我录一段关于咖啡行业的播客" → 不需要（纯生成类）
- "帮我设计一个前端网页" → 不需要（纯生成类）

关键区分：
- "输入文件"是 query 执行前用户已经拥有的、需要 AI 读取/处理的文件（不管是否给出了路径）
- "输出文件"是 query 要求 AI 生成/保存的文件，不算输入文件
- 用户说"我有…"、"我之前存了…"、"我电脑上有…"、"我昨天录的…" 等，都表示已有文件，需要预生成

只回复 YES 或 NO，不要有任何其他内容。"""

FILTER_USER_PROMPT = "以下是你要进行判定的query: "


# ============================================================
# 参数初始化
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
        raise argparse.ArgumentTypeError("参数必须为正整数")
    return ivalue


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="批量生成 query 所需输入文件")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help=".env 文件路径")

    subparsers = parser.add_subparsers(dest="action", required=True)

    def add_common_args(subparser: argparse.ArgumentParser):
        subparser.add_argument("--workspace-hub", type=Path, required=True, help="原始 workspace 根目录")
        subparser.add_argument("--workspace-base", type=Path, help="临时 workspace 根目录（run 时必填）")
        subparser.add_argument("--results-dir", type=Path, help="结果目录（run 时必填）")
        subparser.add_argument("--skills-source", type=Path, help="skills 来源目录（run 时必填）")
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
        raise ValueError("缺少 --workspace-hub")
    if not WORKSPACE_HUB.exists():
        raise FileNotFoundError(f"workspace_hub 不存在: {WORKSPACE_HUB}")

    if action == "run":
        if WORKSPACE_BASE is None:
            raise ValueError("run 模式缺少 --workspace-base")
        if RESULTS_DIR is None:
            raise ValueError("run 模式缺少 --results-dir")
        if SKILLS_SOURCE is None:
            raise ValueError("run 模式缺少 --skills-source")
        if not GEN_OPENCLAW_MODEL:
            raise ValueError("缺少 GEN_OPENCLAW_MODEL（请在 .env 中配置或通过 --openclaw-model 传入）")
        if not LITELLM_API_BASE:
            raise ValueError("缺少 FILTER_API_BASE（请在 .env 中配置）")
        if not LITELLM_API_KEY:
            raise ValueError("缺少 FILTER_API_KEY（请在 .env 中配置）")
        if not FILTER_MODEL:
            raise ValueError("缺少 FILTER_MODEL（请在 .env 中配置）")


# ============================================================
# 工具函数
# ============================================================
def list_workspace_dirs() -> list[Path]:
    assert WORKSPACE_HUB is not None
    return sorted(
        d for d in WORKSPACE_HUB.iterdir()
        if d.is_dir() and d.name.startswith("workspace_")
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
        if item.name in {LOG_FILENAME, "skills"}:
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
            print(f"  ⚠️ [{ws_dir.name}] 拷贝文件失败 {item.name}: {e}")

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
                    print(f"  ⚠️ [{ws_dir.name}] 同步 skill 失败 {skill_dir.name}: {e}")


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
    print(f"  📦 创建 agent: {agent_name}")
    print(f"     workspace: {tmp_ws}")
    with _agent_cli_lock:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"创建 agent 失败 {agent_name}: {result.stderr.strip()}")


# ============================================================
# 断点续跑 & 日志
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
            print(f"     ⚠️ 删除失败 {agent_name}: {result.stderr.strip()}")

    agent_record = Path.home() / ".openclaw" / "agents" / agent_name
    if agent_record.exists():
        try:
            if agent_record.is_dir():
                shutil.rmtree(agent_record)
            else:
                agent_record.unlink()
            if not silent:
                print(f"     🗑️  已清理本地记录: {agent_record}")
        except Exception as e:
            if not silent:
                print(f"     ⚠️ 清理本地记录失败: {e}")


def cleanup_agents():
    workspace_dirs = list_workspace_dirs()
    print(f"🧹 正在删除 {len(workspace_dirs)} 个 agents...\n")
    for ws_dir in workspace_dirs:
        agent_name = get_agent_name(ws_dir.name)
        cleanup_single_agent(agent_name)
    print("\n🎉 清理完毕！")


# ============================================================
# 阶段一：并发预筛选
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
                print(f"  ⚠️ 预筛选返回异常内容: {answer[:120]}")
                return None
    except Exception as e:
        print(f"  ⚠️ 预筛选调用失败: model={FILTER_MODEL}, error={e}")
        return None


def filter_one(rec: dict) -> tuple[str, bool | None]:
    rid = rec["id"]
    query = rec["result"]
    need = needs_input_files(query)
    return rid, need


def run_prefilter(todo: list[dict], ws_name: str, log_file: Path) -> tuple[list[dict], int]:
    need_generate = []
    skip_count = 0

    with tqdm(total=len(todo), desc=f"  {ws_name} 预筛选", unit="q",
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
                                   "[SKIP] 预筛选判定无需生成输入文件",
                                   status="skip")
                        skip_count += 1
                    else:
                        need_generate.append(rec)
                    pbar.set_postfix(need=len(need_generate),
                                     skip=skip_count, refresh=True)
                except Exception as e:
                    need_generate.append(rec)
                    pbar.write(f"  ⚠️ 预筛选异常 {rec['id']}: {e}")
                pbar.update(1)

    return need_generate, skip_count


# ============================================================
# 阶段二：串行调用 OpenClaw 生成文件
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
# 处理单个 workspace（领域）
# ============================================================
def process_workspace(ws_dir: Path) -> list[dict]:
    assert RESULTS_DIR is not None

    ws_name = ws_dir.name
    agent_name = get_agent_name(ws_name)
    tmp_ws = get_workspace_path(ws_name)
    input_file = ws_dir / INPUT_FILENAME
    log_file = ws_dir / LOG_FILENAME

    if not input_file.exists():
        print(f"\n⏭️  {ws_name}: 无 {INPUT_FILENAME}，跳过")
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
                print(f"  ⚠️ [{ws_name}] 输入文件第 {line_no} 行 JSON 解析失败: {e}")
                continue

            rid = rec.get("id")
            result = rec.get("result", "")
            if not rid:
                print(f"  ⚠️ [{ws_name}] 输入文件第 {line_no} 行缺少 id，已跳过")
                continue
            if result and not result.startswith("[ERROR]"):
                records.append(rec)

    if not records:
        print(f"\n⏭️  {ws_name}: 无有效记录，跳过")
        return []

    finished_ids = load_finished_ids(log_file)
    todo = [r for r in records if r["id"] not in finished_ids]

    if not todo:
        print(f"\n✅ {ws_name}: 全部 {len(records)} 条已完成，跳过")
        return []

    print(f"\n📦 {ws_name}: {len(records)} 条, 已完成 {len(finished_ids)}, 待处理 {len(todo)}")

    need_generate, skip_count = run_prefilter(todo, ws_name, log_file)
    print(f"   📊 预筛选完成: {len(need_generate)} 条需要生成, {skip_count} 条跳过")

    ensure_workspace(ws_dir)

    if not need_generate:
        print(f"   ✅ {ws_name}: 全部跳过，无需调用 OpenClaw")
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
                        print(f"  ⚠️ [{ws_name}] 拷贝对话记录失败 {fp.name}: {e}")
        finally:
            cleanup_single_agent(agent_name, silent=True)

    print(f"   → {ws_name} 本轮: 生成 {done_count}, 跳过 {skip_count}, 失败 {fail_count}")
    return results


# ============================================================
# 主流程：并发执行
# ============================================================
def reset_logs():
    workspace_dirs = list_workspace_dirs()
    count = 0
    for ws_dir in workspace_dirs:
        log_file = ws_dir / LOG_FILENAME
        if log_file.exists():
            log_file.unlink()
            count += 1
            print(f"  🗑️  已清除: {log_file}")
    if count:
        print(f"\n✅ 已清除 {count} 个日志文件，下次运行将从头开始")
    else:
        print("ℹ️  未找到日志文件，无需清除")


def show_status():
    workspace_dirs = list_workspace_dirs()
    total_records = 0
    total_done = 0

    print(f"\n📊 当前进度:")
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
        print(f"   {icon} {ws_name}: {done}/{total} (剩余 {remaining})")

    print("=" * 60)
    print(f"   总计: {total_done}/{total_records} (剩余 {total_records - total_done})")
    print("=" * 60 + "\n")


def run_all():
    assert RESULTS_DIR is not None

    workspace_dirs = list_workspace_dirs()

    if not workspace_dirs:
        print("❌ 未找到任何 workspace_* 目录")
        return

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Benchmark 输入文件生成器（batch 版本 · workspace 间并发）")
    print(f"  model: {GEN_OPENCLAW_MODEL}")
    print(f"  预筛选模型: {FILTER_MODEL}")
    print(f"  预筛选并发: {FILTER_WORKERS}")
    print(f"  workspace 间并发: {MAX_DOMAIN_PARALLEL}")
    print(f"  workspace 内: 串行")
    print(f"  输入文件: {INPUT_FILENAME}")
    print(f"  workspace_hub: {WORKSPACE_HUB}")
    print(f"  临时 workspace: {WORKSPACE_BASE}")
    print(f"  结果目录: {RESULTS_DIR}")
    print(f"  skills 来源: {SKILLS_SOURCE}")
    print("=" * 60)
    print(f"\n📂 发现 {len(workspace_dirs)} 个 workspace 目录")

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
                print(f"💥 workspace [{ws_name}] 执行异常: {e}")

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
    print(f"📊 执行完毕！耗时 {elapsed:.1f}s")
    print(f"   workspace 数: {len(workspace_dirs)}")
    print(f"   本次任务: {len(all_results)}")
    print(f"   ✅ 成功: {summary['this_run_success']}")
    print(f"   ⚪ empty_payloads: {summary['this_run_empty_payloads']}")
    print(f"   ❌ 失败: {summary['this_run_failed']}")
    print(f"   ⏰ 超时: {summary['this_run_timeout']}")
    print(f"   💥 异常: {summary['this_run_error']}")
    print(f"   📄 汇总: {summary_file}")
    if summary['this_run_empty_payloads'] or summary['this_run_failed'] or summary['this_run_timeout'] or summary['this_run_error']:
        print("   💡 重跑脚本会自动续跑 failed/timeout/error/empty_payloads 记录")
    print(f"{'=' * 60}")


# ============================================================
# 入口
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
        print(f"❌ 未知命令: {action}")
        sys.exit(1)


if __name__ == "__main__":
    main()
