"""Bare upstream git repo: create, seed, clone helpers.

The "upstream" is a bare repo on the host that every agent container
mounts and pushes into. The harness initialises it once by snapshotting
the user's project directory: everything in it is committed, except a
small skip list of harness state and common dev clutter. judge.sh and
an empty verdicts.json are added on top if the project includes a
JUDGE.md.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from importlib import resources
from pathlib import Path

from agent_factory.config import SEED_SKIP_TOP_LEVEL, ProjectLayout

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
    """Snapshot the project directory into `work`, then add harness files.

    Everything in the project root is copied except entries in
    `SEED_SKIP_TOP_LEVEL` (the harness's own state and common dev
    clutter like `.git`, `.venv`, `__pycache__`, `node_modules`, ...).
    On top, the harness lays down `current_tasks/` and — if `JUDGE.md`
    exists in the project — `judge.sh` and a verdicts.json scaffold.
    """
    copied = 0
    for child in layout.root.iterdir():
        if child.name in SEED_SKIP_TOP_LEVEL:
            continue
        target = work / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=False)
        else:
            shutil.copy2(child, target)
        copied += 1
    log.info("Seeded %d top-level entries from %s", copied, layout.root)

    if not (work / "GOAL.md").is_file():
        # discover() already enforced this, but guard against skip-list
        # misconfiguration that would silently strip GOAL.md.
        raise GitError("GOAL.md was not copied into the seed — check SEED_SKIP_TOP_LEVEL.")

    # current_tasks/ — convention for agent coordination (cleared each run)
    tasks_dir = work / "current_tasks"
    tasks_dir.mkdir(exist_ok=True)
    (tasks_dir / ".gitkeep").touch(exist_ok=True)

    # judge.sh + verdicts.json — only if the project opted into judging
    if layout.judge_md is not None:
        judge_sh = work / "judge.sh"
        judge_sh.write_text(_read_template("judge.sh"))
        judge_sh.chmod(0o755)
        log.info("Seeded judge.sh from template")

        verdicts_path = work / "verdicts.json"
        if not verdicts_path.exists():
            verdicts_path.write_text(_read_template("verdicts.empty.json"))
            log.info("Seeded verdicts.json scaffold")


def clone_snapshot(layout: ProjectLayout, dest: Path) -> None:
    """Make a fresh clone of upstream into dest. Used by status/analytics."""
    subprocess.run(
        ["git", "clone", str(layout.upstream_repo), str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
