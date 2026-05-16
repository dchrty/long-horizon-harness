"""Project layout discovery.

A "project" is a directory the user owns. It contains, at minimum, a
GOAL.md. It may also contain a JUDGE.md (Goal 3) and a seed/ subdirectory
whose contents are copied into the initial commit of upstream.git.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_STATE_DIRNAME = "upstream.git"
LOG_DIRNAME = "agent_logs"


@dataclass(frozen=True)
class ProjectLayout:
    """Paths discovered inside the user's project directory."""

    root: Path
    goal_md: Path
    judge_md: Path | None
    seed_dir: Path | None
    upstream_repo: Path
    log_dir: Path

    @property
    def run_prefix(self) -> str:
        """Container/image name prefix unique to this project directory.

        The project's directory basename (sanitised) keeps multiple
        project worktrees on the same host from colliding on container
        names.
        """
        slug = re.sub(r"[^a-zA-Z0-9_]", "", self.root.name) or "factory"
        return f"agent-factory-{slug}"

    @property
    def image_tag(self) -> str:
        return f"{self.run_prefix}:latest"


def discover(project_dir: Path | str | None = None) -> ProjectLayout:
    """Locate the project files. Raises if GOAL.md is missing."""
    root = Path(project_dir).resolve() if project_dir else Path.cwd().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Project directory not found: {root}")

    goal_md = root / "GOAL.md"
    if not goal_md.is_file():
        raise FileNotFoundError(
            f"{goal_md} not found. The project directory must contain a GOAL.md."
        )

    judge_md = root / "JUDGE.md"
    seed_dir = root / "seed"

    return ProjectLayout(
        root=root,
        goal_md=goal_md,
        judge_md=judge_md if judge_md.is_file() else None,
        seed_dir=seed_dir if seed_dir.is_dir() else None,
        upstream_repo=root / PROJECT_STATE_DIRNAME,
        log_dir=root / LOG_DIRNAME,
    )
