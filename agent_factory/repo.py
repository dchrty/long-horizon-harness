"""Bare upstream git repo: create, seed, clone helpers.

The "upstream" is a bare repo on the host that every agent container
mounts and pushes into. The harness initialises it once with the user's
GOAL.md (plus JUDGE.md, judge.sh, verdicts.json scaffold, and seed/
contents if present).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from importlib import resources
from pathlib import Path

from agent_factory.config import ProjectLayout

log = logging.getLogger(__name__)

GIT_USER_NAME = "Claude Opus 4.6"
GIT_USER_EMAIL = "noreply@anthropic.com"
TEMPLATES_PACKAGE = "agent_factory.templates"


class GitError(RuntimeError):
    pass


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    log.debug("git %s (cwd=%s)", " ".join(args), cwd)
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed (cwd={cwd}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def _read_template(name: str) -> str:
    return resources.files(TEMPLATES_PACKAGE).joinpath(name).read_text()


def init_upstream(layout: ProjectLayout) -> None:
    """Initialise the bare upstream repo and seed it with the user's content.

    Idempotent only in the sense that it refuses to clobber an existing
    upstream.git. Delete it first to re-initialise.
    """
    if layout.upstream_repo.exists():
        raise FileExistsError(
            f"{layout.upstream_repo} already exists. "
            "Delete it to re-initialise (loses agent history)."
        )

    log.info("Creating bare upstream repo at %s", layout.upstream_repo)
    layout.upstream_repo.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(layout.upstream_repo)],
        check=True,
        capture_output=True,
        text=True,
    )

    with tempfile.TemporaryDirectory(prefix="agent-factory-seed-") as tmp:
        work = Path(tmp) / "seed"
        subprocess.run(
            ["git", "clone", str(layout.upstream_repo), str(work)],
            check=True,
            capture_output=True,
            text=True,
        )
        _git(work, "config", "user.name", GIT_USER_NAME)
        _git(work, "config", "user.email", GIT_USER_EMAIL)

        _seed_files(work, layout)

        _git(work, "add", "-A")
        _git(work, "commit", "-m", "Initial commit: seed from project directory")

        # Push, handling both default-branch names that might exist
        push = _git(work, "push", "origin", "HEAD:main", check=False)
        if push.returncode != 0:
            push = _git(work, "push", "origin", "HEAD:master", check=False)
        if push.returncode != 0:
            raise GitError(f"Failed to push initial commit:\n{push.stderr}")

    log.info("Upstream repo initialised.")


def _seed_files(work: Path, layout: ProjectLayout) -> None:
    """Lay down GOAL.md, JUDGE.md (if any), judge.sh, verdicts.json, seed/."""
    # GOAL.md — always present
    shutil.copy2(layout.goal_md, work / "GOAL.md")
    log.info("Seeded GOAL.md")

    # current_tasks/ — convention for agent coordination (cleared each run)
    (work / "current_tasks").mkdir()
    (work / "current_tasks" / ".gitkeep").touch()

    # JUDGE.md + judge.sh + verdicts.json — only if user opted into judging
    if layout.judge_md is not None:
        shutil.copy2(layout.judge_md, work / "JUDGE.md")
        log.info("Seeded JUDGE.md")

        judge_sh = work / "judge.sh"
        judge_sh.write_text(_read_template("judge.sh"))
        judge_sh.chmod(0o755)
        log.info("Seeded judge.sh from template")

        verdicts_path = work / "verdicts.json"
        verdicts_path.write_text(_read_template("verdicts.empty.json"))
        log.info("Seeded verdicts.json scaffold")

    # seed/ — user-supplied initial files
    if layout.seed_dir is not None:
        for child in layout.seed_dir.iterdir():
            target = work / child.name
            if child.is_dir():
                shutil.copytree(child, target, dirs_exist_ok=False)
            else:
                shutil.copy2(child, target)
        log.info("Seeded %d items from seed/", len(list(layout.seed_dir.iterdir())))


def clone_snapshot(layout: ProjectLayout, dest: Path) -> None:
    """Make a fresh clone of upstream into dest. Used by status/analytics."""
    subprocess.run(
        ["git", "clone", str(layout.upstream_repo), str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
