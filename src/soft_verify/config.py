from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> dict[str, str]:
    loaded: dict[str, str] = {}
    base_dir = Path(__file__).resolve()
    candidate_paths = [
        base_dir.parent / ".env",
        base_dir.parents[2] / ".env",
    ]

    # Load the legacy local file first, then let the repo root override it.
    for env_path in candidate_paths:
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key:
                loaded[key] = value
    return loaded


_DOTENV = _load_dotenv()


def _getenv(*keys: str, default: str = "") -> str:
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    for key in keys:
        value = _DOTENV.get(key)
        if value:
            return value
    return default


def llm_config() -> dict[str, str | int]:
    """LLM config for both plan generation and soft-check agent evaluation."""
    api_key = _getenv("VERIFY_API_KEY", "BIGMODEL_API_KEY")
    model_name = _getenv("VERIFY_MODEL", default="glm-5")
    base_url = _getenv(
        "VERIFY_API_BASE",
        default="https://open.bigmodel.cn/api/paas/v4",
    )
    timeout_seconds = int(
        _getenv("VERIFY_TIMEOUT_SECONDS", default="120")
    )
    max_rounds = int(
        _getenv("VERIFY_SOFT_AGENT_MAX_ROUNDS", default="20")
    )
    return {
        "api_key": api_key,
        "model_name": model_name,
        "base_url": base_url.rstrip("/"),
        "timeout_seconds": timeout_seconds,
        "max_rounds": max(1, max_rounds),
    }
