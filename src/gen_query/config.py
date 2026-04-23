"""Configuration for the workspace and query generation pipeline.

Edit this file directly to match your local environment.
Sensitive values (API keys, etc.) should be placed in the project root .env file.
"""

from __future__ import annotations

import os
from pathlib import Path


# ============================================================
# 加载项目根目录 .env（仅在环境变量尚未设置时填充）
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parents[2]
_env_file = PROJECT_ROOT / ".env"
if _env_file.exists():
    with open(_env_file, "r", encoding="utf-8") as _f:
        for _raw_line in _f:
            _line = _raw_line.strip()
            if not _line or _line.startswith("#"):
                continue
            if _line.startswith("export "):
                _line = _line[len("export "):].strip()
            _key, _sep, _value = _line.partition("=")
            if not _sep:
                continue
            _key = _key.strip()
            _value = _value.strip()
            if len(_value) >= 2 and _value[0] == _value[-1] and _value[0] in {"'", '"'}:
                _value = _value[1:-1]
            if _key and _key not in os.environ:
                os.environ[_key] = _value

GEN_QUERY_ROOT = Path(__file__).resolve().parent
DATA_DIR = GEN_QUERY_ROOT / "data"

# Step 0: workspace generation.
SKILL_HUBS = [
    PROJECT_ROOT / "skills",
]
WORKSPACE_HUB = PROJECT_ROOT / "workspace_hub_source"

WS_PREFIX = "workspace_"
WORKSPACES_TO_BUILD = 5
MIN_SKILLS_PER_WORKSPACE = 2
MAX_SKILLS_PER_WORKSPACE = 2
WORKSPACE_COPY_MODE = "symlink"
WORKSPACE_FORCE_CLEAN = False

# Step 0/1: shared sampling randomness.
RANDOM_SEED = 403

# Step 1: prompt generation.
QUERIES_PER_SKILL = 3

# Step 2/3: LLM generation and rewrite.
LITELLM_API_BASE = os.environ.get("GEN_QUERY_API_BASE", "")
LITELLM_API_KEY = os.environ.get("GEN_QUERY_API_KEY", "")
LITELLM_MODEL = os.environ.get("GEN_QUERY_MODEL", "")
# generate query thread nums 
BENCH_CONCURRENCY = 5
# rewrite query thread nums 
REWRITE_WORKERS = 5
REWRITE_TIMEOUT = 60

# Step 3: persona source file. This path stays configurable on purpose.
INSTRUCTIONS_FILE = DATA_DIR / "unique_task_instructions.json"

