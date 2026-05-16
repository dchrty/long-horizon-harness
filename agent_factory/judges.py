"""Read + render the judge_history.jsonl that judge.sh writes.

`judge.sh` appends one JSON line per invocation to
`<project>/agent_logs/judge_history.jsonl`. This module is the read
side: parse the records, filter, format, optionally follow.

The visible UX flow this powers:

  agent-factory judges                    # last 20 invocations, tabular
  agent-factory judges --follow           # live append-tailed
  agent-factory judges --agent <id>       # filter to one agent
  agent-factory judges --verdict fail     # only failures
  agent-factory judges --show <short>     # dump the tee log for a hash

The point is operator-visibility over a nested subprocess that the
existing `docker logs` view can't show into. PIDs change; container
names stay stable; git hashes stay stable. We key everything on the
short hash + agent name and never expose a PID.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import click

from agent_factory.config import LOG_DIRNAME, ProjectLayout

log = logging.getLogger(__name__)

HISTORY_FILENAME = "judge_history.jsonl"


@dataclass(frozen=True)
class JudgeRecord:
    """One row from judge_history.jsonl."""

    ts: str
    agent_id: str
    git_hash: str
    git_hash_short: str
    model: str
    exit_code: int
    verdict: str
    duration_ms: int
    tee_log: str

    @classmethod
    def from_json(cls, payload: dict) -> JudgeRecord:
        # Be permissive on read: missing fields shouldn't crash the
        # viewer for older log lines or partially-written records.
        return cls(
            ts=str(payload.get("ts", "")),
            agent_id=str(payload.get("agent_id", "")),
            git_hash=str(payload.get("git_hash", "")),
            git_hash_short=str(
                payload.get("git_hash_short") or (payload.get("git_hash", "")[:8])
            ),
            model=str(payload.get("model", "")),
            exit_code=int(payload.get("exit_code", -1)),
            verdict=str(payload.get("verdict", "unknown")),
            duration_ms=int(payload.get("duration_ms", 0)),
            tee_log=str(payload.get("tee_log", "")),
        )


def history_path(layout: ProjectLayout) -> Path:
    """Resolve the JSONL history file location for this project."""
    return layout.root / LOG_DIRNAME / HISTORY_FILENAME


def read_history(layout: ProjectLayout) -> list[JudgeRecord]:
    """Read the full JSONL history, skipping malformed lines (don't crash
    the viewer on a partial write — it'll show next time)."""
    path = history_path(layout)
    if not path.is_file():
        return []
    out: list[JudgeRecord] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                log.debug("skipping malformed judge_history line: %r", line[:120])
                continue
            if not isinstance(payload, dict):
                continue
            out.append(JudgeRecord.from_json(payload))
    return out


def filter_records(
    records: list[JudgeRecord],
    *,
    agent: str | None = None,
    verdict: str | None = None,
) -> list[JudgeRecord]:
    out = records
    if agent:
        out = [r for r in out if r.agent_id == agent]
    if verdict:
        out = [r for r in out if r.verdict == verdict]
    return out


def show(
    layout: ProjectLayout,
    follow: bool,
    tail: int,
    agent: str | None,
    verdict: str | None,
    show_hash: str | None,
) -> None:
    """Render the JSONL history as a table, or tail it, or dump one log."""
    if show_hash:
        _show_log_for_hash(layout, show_hash)
        return

    records = read_history(layout)
    filtered = filter_records(records, agent=agent, verdict=verdict)

    if not filtered:
        # Distinguish "no judges ever" from "no judges match the filter"
        if not records:
            click.echo(
                f"No judge invocations recorded yet ({history_path(layout)})."
            )
        else:
            click.echo(
                f"No judge invocations match the filter "
                f"(records total={len(records)})."
            )
        if not follow:
            return

    if not follow:
        _print_table(filtered[-tail:] if tail and tail > 0 else filtered)
        return

    # Follow mode: print what's there now, then watch for new appends.
    _print_table(filtered[-tail:] if tail and tail > 0 else filtered)
    _tail_history(layout, agent=agent, verdict=verdict, seen_count=len(records))


def _show_log_for_hash(layout: ProjectLayout, short_hash: str) -> None:
    """Dump the tee log file recorded for a given short hash. Matches
    prefixes so the operator can paste the first 4-8 chars."""
    records = read_history(layout)
    matches = [r for r in records if r.git_hash_short.startswith(short_hash)]
    if not matches:
        click.echo(
            f"No judge invocation found with hash prefix '{short_hash}'. "
            f"Try `agent-factory judges` to see recent hashes."
        )
        return
    if len(matches) > 1:
        click.echo(
            f"Hash prefix '{short_hash}' matches {len(matches)} invocations:"
        )
        for r in matches:
            click.echo(f"  {r.ts}  {r.agent_id}  {r.git_hash_short}  {r.verdict}")
        click.echo("Use a longer prefix.")
        return
    rec = matches[0]
    # tee_log was recorded as an absolute path inside the container
    # (/workspace/agent_logs/...). On the host, that maps to the
    # project's agent_logs/ via the bind-mount.
    tee_log = rec.tee_log
    host_path: Path
    if tee_log.startswith("/workspace/agent_logs/"):
        host_path = layout.log_dir / Path(tee_log).name
    else:
        host_path = Path(tee_log)
        if not host_path.is_absolute():
            host_path = layout.log_dir / tee_log
    if not host_path.is_file():
        click.echo(f"Tee log not found at {host_path}. (recorded as {tee_log})")
        return
    click.echo(
        click.style(
            f"--- judge log for {rec.git_hash_short} "
            f"(agent={rec.agent_id}, verdict={rec.verdict}, "
            f"exit={rec.exit_code}) ---",
            fg="bright_black",
        )
    )
    click.echo(host_path.read_text(encoding="utf-8", errors="replace"))


def _print_table(records: list[JudgeRecord]) -> None:
    """Tabular dump. Right-aligned where the widest value still fits a
    reasonable terminal; verdicts colour-coded."""
    if not records:
        return
    header = (
        f"{'ts':<20}  {'agent':<28}  {'hash':<8}  "
        f"{'model':<22}  {'verdict':<7}  {'exit':>4}  {'dur':>8}"
    )
    click.echo(click.style(header, fg="bright_black"))
    click.echo(click.style("-" * len(header), fg="bright_black"))
    for r in records:
        verdict_colour = {
            "pass": "green",
            "fail": "red",
            "infra-error": "yellow",
        }.get(r.verdict, "white")
        verdict_cell = click.style(f"{r.verdict:<7}", fg=verdict_colour)
        dur_s = r.duration_ms / 1000.0
        click.echo(
            f"{r.ts:<20}  {r.agent_id:<28}  {r.git_hash_short:<8}  "
            f"{r.model:<22}  {verdict_cell}  {r.exit_code:>4}  "
            f"{dur_s:>7.1f}s"
        )


# Seconds between polls when --follow has nothing new to read.
# Short enough to feel live; long enough not to thrash the filesystem.
_FOLLOW_POLL_SECONDS = 1.0


def _tail_history(
    layout: ProjectLayout,
    *,
    agent: str | None,
    verdict: str | None,
    seen_count: int,
) -> None:
    """Poll the JSONL file for new lines. Stops on Ctrl-C.

    Uses record count rather than file offset because the file is
    written by a different process (judge.sh) on a different OS view
    (container) — sticking to a high-level "how many records have I
    seen" comparison is simpler and survives an edited or rotated
    history file."""
    try:
        while True:
            time.sleep(_FOLLOW_POLL_SECONDS)
            records = read_history(layout)
            if len(records) <= seen_count:
                continue
            new = records[seen_count:]
            seen_count = len(records)
            new = filter_records(new, agent=agent, verdict=verdict)
            if new:
                _print_table(new)
    except KeyboardInterrupt:
        click.echo("\nStopping follow.")
