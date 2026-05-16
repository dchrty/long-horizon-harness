"""Snapshot the state of an in-flight (or completed) run.

Replaces status.sh. Reports:
- agents currently running (and their uptime)
- repo commit count + recent log
- file-count breakdown by extension (no opinion on which extensions matter)
- task locks under current_tasks/ if the GOAL.md uses that convention
- working-tree status inside each live agent (`git status --short`)
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from agent_factory.config import ProjectLayout
from agent_factory.docker_runner import (
    container_status,
    exec_in_container,
)
from agent_factory.repo import clone_snapshot

log = logging.getLogger(__name__)


@dataclass
class StatusSnapshot:
    agents: list[dict[str, str]] = field(default_factory=list)
    commit_count: int = 0
    latest_commit: str = ""
    recent_commits: list[str] = field(default_factory=list)
    extensions: Counter[str] = field(default_factory=Counter)
    total_files: int = 0
    total_lines: int = 0
    task_locks: list[tuple[str, str]] = field(default_factory=list)
    live_work: dict[str, list[str]] = field(default_factory=dict)


def snapshot(layout: ProjectLayout, short: bool = False) -> StatusSnapshot:
    snap = StatusSnapshot()
    snap.agents = container_status(layout)

    if not layout.upstream_repo.exists():
        return snap

    with tempfile.TemporaryDirectory(prefix="agent-factory-status-") as tmp:
        work = Path(tmp) / "code"
        try:
            clone_snapshot(layout, work)
        except subprocess.CalledProcessError:
            return snap

        commits = _git_lines(work, "rev-list", "--count", "HEAD")
        snap.commit_count = int(commits[0]) if commits else 0
        snap.latest_commit = _git_text(work, "log", "--oneline", "-1")
        snap.recent_commits = _git_lines(work, "log", "--oneline", "-20")

        snap.extensions, snap.total_files, snap.total_lines = _walk_tree(work)

        if short:
            return snap

        snap.task_locks = _read_task_locks(work)

    snap.live_work = _collect_live_work(snap.agents)
    return snap


def _git_text(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    return result.stdout.strip()


def _git_lines(cwd: Path, *args: str) -> list[str]:
    return [line for line in _git_text(cwd, *args).splitlines() if line.strip()]


def _walk_tree(work: Path) -> tuple[Counter[str], int, int]:
    """Count files and (best-effort) line counts by extension. Skip .git."""
    ext = Counter()
    files = 0
    lines = 0
    for path in work.rglob("*"):
        if not path.is_file():
            continue
        if ".git" in path.parts:
            continue
        files += 1
        suffix = path.suffix.lower() or "(none)"
        ext[suffix] += 1
        try:
            with path.open("rb") as fh:
                lines += sum(1 for _ in fh)
        except OSError:
            pass
    return ext, files, lines


def _read_task_locks(work: Path) -> list[tuple[str, str]]:
    tasks_dir = work / "current_tasks"
    if not tasks_dir.is_dir():
        return []
    out: list[tuple[str, str]] = []
    for f in sorted(tasks_dir.glob("*.txt")):
        try:
            first = f.read_text(errors="replace").splitlines()[:1]
            summary = first[0] if first else ""
        except OSError:
            summary = ""
        out.append((f.stem, summary))
    return out


def _collect_live_work(agents: list[dict[str, str]]) -> dict[str, list[str]]:
    """For each running agent, capture `git status --short` from its workspace."""
    out: dict[str, list[str]] = {}
    for agent in agents:
        name = agent["name"]
        text = exec_in_container(
            name,
            "bash",
            "-c",
            "cd /workspace/code 2>/dev/null && git status --short 2>/dev/null",
        )
        out[name] = [line for line in text.splitlines() if line.strip()]
    return out


def render(snap: StatusSnapshot, short: bool = False) -> str:
    lines: list[str] = []
    lines.append("=" * 56)
    lines.append("  Agent Factory - Status")
    lines.append("=" * 56)
    lines.append(f"Agents running: {len(snap.agents)}")
    for agent in snap.agents:
        lines.append(f"  {agent['name']}  up {agent['uptime']}")
    lines.append("")

    lines.append("--- Repository ---")
    lines.append(f"Commits: {snap.commit_count}")
    lines.append(f"Latest:  {snap.latest_commit or '(none)'}")
    lines.append(f"Files:   {snap.total_files}  ({snap.total_lines} total lines)")
    if snap.extensions:
        breakdown = ", ".join(f"{ext}={n}" for ext, n in snap.extensions.most_common(8))
        lines.append(f"By ext:  {breakdown}")
    lines.append("")

    if short:
        return "\n".join(lines)

    lines.append("--- Recent Commits ---")
    if snap.recent_commits:
        for c in snap.recent_commits:
            lines.append(f"  {c}")
    else:
        lines.append("  (none)")
    lines.append("")

    lines.append("--- Active Task Locks ---")
    if snap.task_locks:
        for name, summary in snap.task_locks:
            lines.append(f"  [{name}] {summary}")
    else:
        lines.append("  (none)")
    lines.append("")

    if snap.live_work:
        lines.append("--- Live Agent Work (uncommitted) ---")
        for agent, items in snap.live_work.items():
            lines.append(f"  {agent}:")
            if items:
                for entry in items[:15]:
                    lines.append(f"    {entry}")
                if len(items) > 15:
                    lines.append(f"    ... and {len(items) - 15} more")
            else:
                lines.append("    (clean working tree)")
        lines.append("")

    return "\n".join(lines)
