"""Workspace and skill discovery helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillInfo:
    slug: str
    name: str
    description: str
    directory: Path


def iter_workspace_dirs(workspace_hub: Path, workspace_prefix: str) -> list[Path]:
    return sorted(
        directory
        for directory in workspace_hub.iterdir()
        if directory.is_dir() and directory.name.startswith(workspace_prefix)
    )


def parse_skill_md(skill_dir: Path) -> SkillInfo | None:
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return None

    content = skill_file.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return None

    parts = content.split("---", 2)
    if len(parts) < 3:
        return None

    frontmatter = parts[1].strip()

    name_match = re.search(r"^name:\s*(.+)$", frontmatter, re.MULTILINE)
    name = name_match.group(1).strip().strip('"').strip("'") if name_match else skill_dir.name

    description_match = re.search(
        r"^description:\s*(.+?)$",
        frontmatter,
        re.MULTILINE | re.DOTALL,
    )
    description = ""
    if description_match:
        description = description_match.group(1).strip().strip('"').strip("'")
    if not description:
        quoted_match = re.search(r"description:\s*[\"'](.+?)[\"']", frontmatter, re.DOTALL)
        if quoted_match:
            description = quoted_match.group(1).strip()

    if not description:
        return None

    return SkillInfo(
        slug=skill_dir.name,
        name=name,
        description=description,
        directory=skill_dir,
    )


def load_workspace_skills(workspace_dir: Path) -> list[SkillInfo]:
    skills_dir = workspace_dir / "skills"
    if not skills_dir.exists():
        return []

    skills: list[SkillInfo] = []
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir():
            continue
        info = parse_skill_md(child)
        if info is not None:
            skills.append(info)
    return skills


def collect_workspace_specs(
    workspace_hub: Path,
    workspace_prefix: str,
) -> list[tuple[Path, list[SkillInfo]]]:
    if not workspace_hub.exists():
        raise FileNotFoundError(f"workspace_hub does not exist: {workspace_hub}")

    specs: list[tuple[Path, list[SkillInfo]]] = []
    for workspace_dir in iter_workspace_dirs(workspace_hub, workspace_prefix):
        skills = load_workspace_skills(workspace_dir)
        if skills:
            specs.append((workspace_dir, skills))
    return specs
