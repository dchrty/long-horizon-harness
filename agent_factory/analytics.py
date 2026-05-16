"""Replay every commit and emit a generic LOC-over-time table.

Replaces analytics.sh / timeseries.sh / plot_timeseries.py. Goal-agnostic:
walks the commit history, counts files and lines at each commit (by
extension), and writes CSV. Optional matplotlib plot if the `[plot]`
extra is installed.
"""

from __future__ import annotations

import csv
import logging
import subprocess
import tempfile
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from agent_factory.config import ProjectLayout
from agent_factory.repo import clone_snapshot
from agent_factory.status import _walk_tree

log = logging.getLogger(__name__)


@dataclass
class CommitPoint:
    minutes_from_start: int
    hash: str
    timestamp: int
    files: int
    lines: int
    message: str


def collect(layout: ProjectLayout) -> list[CommitPoint]:
    if not layout.upstream_repo.exists():
        return []

    with tempfile.TemporaryDirectory(prefix="agent-factory-analytics-") as tmp:
        work = Path(tmp) / "code"
        clone_snapshot(layout, work)

        commits = _log_commits(work)
        if not commits:
            return []

        first_epoch = commits[0][1]
        points: list[CommitPoint] = []
        for sha, epoch, message in commits:
            subprocess.run(
                ["git", "checkout", "--quiet", "--force", sha],
                cwd=work,
                capture_output=True,
                text=True,
                check=False,
            )
            _, total_files, total_lines = _walk_tree(work)
            points.append(
                CommitPoint(
                    minutes_from_start=(epoch - first_epoch) // 60,
                    hash=sha,
                    timestamp=epoch,
                    files=total_files,
                    lines=total_lines,
                    message=message,
                )
            )
        return points


def to_csv(points: list[CommitPoint]) -> str:
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(["minutes", "hash", "timestamp", "files", "lines", "message"])
    for p in points:
        writer.writerow([p.minutes_from_start, p.hash, p.timestamp, p.files, p.lines, p.message])
    return buf.getvalue()


def plot(points: list[CommitPoint], output: Path) -> None:
    """Render lines-over-time to a PNG. Requires the [plot] extra."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as e:
        raise RuntimeError(
            "matplotlib not installed. Install the [plot] extra: pip install 'agent-factory[plot]'"
        ) from e

    if not points:
        return

    xs = [p.minutes_from_start for p in points]
    ys = [p.lines for p in points]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(xs, ys, marker="o", linewidth=1, markersize=3)
    ax.set_xlabel("Minutes from first commit")
    ax.set_ylabel("Total lines in working tree")
    ax.set_title("Agent factory: lines over time")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output, dpi=120)
    log.info("Wrote plot to %s", output)


def _log_commits(work: Path) -> list[tuple[str, int, str]]:
    """List commits oldest-first as (sha, epoch, subject)."""
    result = subprocess.run(
        ["git", "log", "--reverse", "--format=%H\t%at\t%s"],
        cwd=work,
        capture_output=True,
        text=True,
        check=False,
    )
    out: list[tuple[str, int, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        sha, epoch_s, message = parts
        try:
            out.append((sha, int(epoch_s), message))
        except ValueError:
            continue
    return out
