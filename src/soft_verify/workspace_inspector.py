from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VerificationScope:
    workspace_path: str
    path_mode: str
    absolute_paths: list[str]
    allowed_roots: list[str]
    allowed_files: list[str]
    allow_workspace_root: bool


def resolve_verification_scope(
    intent: str,
    workspace_path: str,
    *,
    path_mode: str = "auto",
    max_files: int = 200,
    preview_chars: int = 3000,
) -> VerificationScope:
    workspace = str(workspace_path or "").strip()
    absolute_paths = extract_absolute_paths(intent)
    use_absolute_paths = path_mode in {"auto", "absolute-priority"} and bool(absolute_paths)
    if use_absolute_paths:
        return VerificationScope(
            workspace_path=workspace,
            path_mode=path_mode,
            absolute_paths=absolute_paths,
            allowed_roots=[
                str(path.resolve())
                for raw_path in absolute_paths
                for path in [Path(raw_path)]
                if path.exists() and path.is_dir()
            ],
            allowed_files=[
                str(Path(raw_path).resolve())
                for raw_path in absolute_paths
                if not (Path(raw_path).exists() and Path(raw_path).is_dir())
            ],
            allow_workspace_root=False,
        )

    return VerificationScope(
        workspace_path=workspace,
        path_mode=path_mode,
        absolute_paths=absolute_paths,
        allowed_roots=[str(Path(workspace).resolve())] if workspace else [],
        allowed_files=[],
        allow_workspace_root=True,
    )


def extract_absolute_paths(text: str) -> list[str]:
    # Do not treat preceding CJK characters as word-boundary blockers.
    # Intents often contain paths like "保存在/data/..." where `\w` would
    # incorrectly include the Chinese character before `/`.
    pattern = re.compile(r"(?<![A-Za-z0-9_.-])(/(?:[^ \t\r\n`\"'<>|]+))")
    found: list[str] = []
    for match in pattern.findall(text or ""):
        candidate = re.split(r"[，。；：！？、,;:!?）】」》)\]}]", match, maxsplit=1)[0]
        candidate = candidate.rstrip(".,;:!?)]}，。；：！？）】」》、")
        if candidate.startswith("//"):
            continue
        if candidate.startswith("/"):
            found.append(candidate)
    return list(dict.fromkeys(found))
