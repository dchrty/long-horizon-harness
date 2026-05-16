"""Project layout discovery.

A "project" is a directory the user owns. It must contain a GOAL.md.
It may also contain a JUDGE.md (enables judgement gating). Everything
else in the directory IS the initial state of the agents' shared repo
— there is no separate "seed" concept. A small skip list keeps harness
state and common cruft out of the seeded snapshot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_STATE_DIRNAME = "upstream.git"
LOG_DIRNAME = "agent_logs"

# Top-level names that should NOT be copied into the initial commit.
# Includes the harness's own state and the usual local-dev clutter.
SEED_SKIP_TOP_LEVEL = frozenset(
    [
        ".git",
        PROJECT_STATE_DIRNAME,
        LOG_DIRNAME,
        ".venv",
        "venv",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "__pycache__",
        "node_modules",
        ".DS_Store",
    ]
)


@dataclass(frozen=True)
class ProjectLayout:
    """Paths discovered inside the user's project directory."""

    root: Path
    goal_md: Path
    judge_md: Path | None
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

    return ProjectLayout(
        root=root,
        goal_md=goal_md,
        judge_md=judge_md if judge_md.is_file() else None,
        upstream_repo=root / PROJECT_STATE_DIRNAME,
        log_dir=root / LOG_DIRNAME,
    )
