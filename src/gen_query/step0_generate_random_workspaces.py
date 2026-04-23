#!/usr/bin/env python3
"""Generate workspaces by randomly sampling skills from one or more hubs.

Each input hub is scanned for direct child directories containing `SKILL.md`.
The script creates `workspace_*` directories under the output path, and places
symlinks (default) or copies of sampled skill directories under each workspace's
`skills/` folder.
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from src.gen_query.config import (
    MAX_SKILLS_PER_WORKSPACE,
    MIN_SKILLS_PER_WORKSPACE,
    RANDOM_SEED,
    SKILL_HUBS,
    WORKSPACES_TO_BUILD,
    WORKSPACE_COPY_MODE,
    WORKSPACE_FORCE_CLEAN,
    WORKSPACE_HUB,
    WS_PREFIX,
)


@dataclass(frozen=True)
class Skill:
    slug: str
    source_dir: Path
    hub_name: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Randomly sample skills from one or more skill hubs and generate "
            "workspace directories containing symlinks."
        )
    )
    parser.add_argument(
        "skill_hubs",
        nargs="*",
        help="Optional positional skill hub directories containing direct child skill folders.",
    )
    parser.add_argument(
        "--skill-hub",
        dest="skill_hub_overrides",
        action="append",
        default=[],
        help="Additional skill hub directory. Can be specified multiple times.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory where workspace_* directories will be created. Defaults to config.",
    )
    parser.add_argument(
        "-n",
        "--num-workspaces",
        type=int,
        default=None,
        help="Number of workspaces to generate. Defaults to config.",
    )
    parser.add_argument(
        "--min-skills",
        type=int,
        default=None,
        help="Minimum skills per workspace. Defaults to config.",
    )
    parser.add_argument(
        "--max-skills",
        type=int,
        default=None,
        help="Maximum skills per workspace. Defaults to config.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducible sampling. Defaults to config.",
    )
    parser.add_argument(
        "--workspace-prefix",
        default=None,
        help="Workspace directory prefix. Defaults to config.",
    )
    parser.add_argument(
        "--force-clean",
        action="store_true",
        help="Delete the output directory first if it already exists.",
    )
    parser.add_argument(
        "--copy-mode",
        choices=["symlink", "copy"],
        default=None,
        help="How to populate skill directories. Defaults to config.",
    )
    return parser.parse_args()


def find_skills(hub_path: Path) -> list[Skill]:
    if not hub_path.exists():
        raise FileNotFoundError(f"Skill hub does not exist: {hub_path}")
    if not hub_path.is_dir():
        raise NotADirectoryError(f"Skill hub is not a directory: {hub_path}")

    skills: list[Skill] = []
    for child in sorted(hub_path.iterdir()):
        if not child.is_dir():
            continue
        if (child / "SKILL.md").exists():
            skills.append(
                Skill(
                    slug=child.name,
                    source_dir=child.resolve(),
                    hub_name=hub_path.name,
                )
            )
    return skills


def collect_skills(hub_paths: list[Path]) -> list[Skill]:
    skills: list[Skill] = []
    seen_source_dirs: set[Path] = set()

    for hub_path in hub_paths:
        for skill in find_skills(hub_path):
            if skill.source_dir in seen_source_dirs:
                continue
            seen_source_dirs.add(skill.source_dir)
            skills.append(skill)

    if not skills:
        raise ValueError("No skills found. Expected direct child directories containing SKILL.md.")

    return skills


def ensure_output_dir(output_dir: Path, force_clean: bool) -> None:
    if output_dir.exists() and force_clean:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def choose_link_name(skill: Skill, used_names: set[str]) -> str:
    base_name = skill.slug
    if base_name not in used_names:
        used_names.add(base_name)
        return base_name

    derived_name = f"{skill.hub_name}__{skill.slug}"
    if derived_name not in used_names:
        used_names.add(derived_name)
        return derived_name

    suffix = 2
    while True:
        candidate = f"{derived_name}__{suffix}"
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
        suffix += 1


def build_workspace(
    workspace_dir: Path,
    all_skills: list[Skill],
    sample_size: int,
    rng: random.Random,
    copy_mode: str = "symlink",
) -> list[tuple[str, Path]]:
    sampled_skills = rng.sample(all_skills, sample_size)
    skills_dir = workspace_dir / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    used_names: set[str] = set()
    created_links: list[tuple[str, Path]] = []
    for skill in sampled_skills:
        link_name = choose_link_name(skill, used_names)
        dest_path = skills_dir / link_name
        if copy_mode == "copy":
            shutil.copytree(skill.source_dir, dest_path)
        else:
            os.symlink(skill.source_dir, dest_path)
        created_links.append((link_name, skill.source_dir))

    return created_links


def validate_sampling_args(
    *,
    num_workspaces: int,
    min_skills: int,
    max_skills: int,
) -> None:
    if num_workspaces <= 0:
        raise ValueError("--num-workspaces must be greater than 0")
    if min_skills <= 0:
        raise ValueError("--min-skills must be greater than 0")
    if max_skills < min_skills:
        raise ValueError("--max-skills must be greater than or equal to --min-skills")


def generate_workspaces(
    *,
    skill_hubs: list[Path],
    output_dir: Path,
    num_workspaces: int,
    min_skills: int,
    max_skills: int,
    seed: int | None,
    workspace_prefix: str,
    force_clean: bool,
    copy_mode: str,
) -> None:
    validate_sampling_args(
        num_workspaces=num_workspaces,
        min_skills=min_skills,
        max_skills=max_skills,
    )

    hub_paths = [Path(path).resolve() for path in skill_hubs]
    output_dir = output_dir.resolve()
    all_skills = collect_skills(hub_paths)

    if len(all_skills) < min_skills:
        raise ValueError(
            f"Not enough skills to sample. Found {len(all_skills)}, need at least {min_skills}."
        )

    ensure_output_dir(output_dir, force_clean)

    rng = random.Random(seed)
    width = max(3, len(str(num_workspaces)))

    print(f"Found {len(all_skills)} skills from {len(hub_paths)} hub(s).")
    print(f"Output directory: {output_dir}")
    print(f"Workspace prefix: {workspace_prefix}")
    print(f"Workspaces to build: {num_workspaces}")
    print(f"Skills per workspace: {min_skills}..{max_skills}")
    print(f"Copy mode: {copy_mode}")
    print(f"Random seed: {seed}")

    for index in range(1, num_workspaces + 1):
        sample_size = rng.randint(min_skills, min(max_skills, len(all_skills)))
        workspace_name = f"{workspace_prefix}{index:0{width}d}"
        workspace_dir = output_dir / workspace_name
        linked_skills = build_workspace(workspace_dir, all_skills, sample_size, rng, copy_mode)

        print(f"{workspace_name}: linked {len(linked_skills)} skills")
        for link_name, source_dir in linked_skills:
            print(f"  - {link_name} -> {source_dir}")


def run_from_config() -> None:
    generate_workspaces(
        skill_hubs=SKILL_HUBS,
        output_dir=WORKSPACE_HUB,
        num_workspaces=WORKSPACES_TO_BUILD,
        min_skills=MIN_SKILLS_PER_WORKSPACE,
        max_skills=MAX_SKILLS_PER_WORKSPACE,
        seed=RANDOM_SEED,
        workspace_prefix=WS_PREFIX,
        force_clean=WORKSPACE_FORCE_CLEAN,
        copy_mode=WORKSPACE_COPY_MODE,
    )


def main() -> None:
    if len(sys.argv) == 1:
        run_from_config()
        return

    args = parse_args()
    skill_hubs = [Path(raw) for raw in args.skill_hubs]
    skill_hubs.extend(Path(raw) for raw in args.skill_hub_overrides)

    generate_workspaces(
        skill_hubs=skill_hubs or SKILL_HUBS,
        output_dir=Path(args.output) if args.output else WORKSPACE_HUB,
        num_workspaces=args.num_workspaces if args.num_workspaces is not None else WORKSPACES_TO_BUILD,
        min_skills=args.min_skills if args.min_skills is not None else MIN_SKILLS_PER_WORKSPACE,
        max_skills=args.max_skills if args.max_skills is not None else MAX_SKILLS_PER_WORKSPACE,
        seed=args.seed if args.seed is not None else RANDOM_SEED,
        workspace_prefix=args.workspace_prefix or WS_PREFIX,
        force_clean=args.force_clean or WORKSPACE_FORCE_CLEAN,
        copy_mode=args.copy_mode or WORKSPACE_COPY_MODE,
    )


if __name__ == "__main__":
    main()
