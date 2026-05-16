"""Multiplexed `docker logs` view for this project's agents.

Two modes:

- snapshot: read the last N lines from each container with `docker logs
  --tail N`, print them serially, prefixed and color-coded by agent.
- follow:   spawn one reader thread per container running `docker logs
  -f --tail N`, interleave their stdout under a single lock so lines
  don't tear. Daemon threads + a small `join` poll loop keep Ctrl-C
  responsive on Windows (where `Thread.join()` blocks signal delivery).

The colour cycle is `click.style`-based, so it degrades gracefully on
terminals without ANSI support and respects `NO_COLOR`.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time

import click

from agent_factory.config import ProjectLayout
from agent_factory.docker_runner import list_running

log = logging.getLogger(__name__)

# Picked for legibility on both light and dark terminals; cycled by
# agent index so two-agent runs stay easy to distinguish at a glance.
_AGENT_COLORS = ("cyan", "green", "yellow", "magenta", "blue", "red", "white")

# Single lock guarding stdout so concurrent threads don't interleave
# mid-line. click.echo is line-oriented, which is what we want.
_stdout_lock = threading.Lock()


def show(
    layout: ProjectLayout,
    follow: bool,
    tail: int,
    agent_filter: str | None = None,
    wait: bool = False,
) -> None:
    """Print recent or live container output for this project's agents.

    `agent_filter` matches an agent name exactly (e.g. agent-factory-myproj-1).
    `wait` polls for agents to appear instead of exiting when none are
    running yet - useful during the first build of a cold run, where you
    want to start `logs -f --wait` before the container is up.
    """
    agents = _resolve_agents(layout, wait=wait)
    if not agents:
        click.echo("No running agents for this project.")
        return

    if agent_filter:
        if agent_filter not in agents:
            click.echo(
                f"No running agent named '{agent_filter}'. Running agents: {', '.join(agents)}"
            )
            return
        agents = [agent_filter]

    if follow:
        _follow(agents, tail)
    else:
        _snapshot(agents, tail)


# Seconds between polls when --wait is set and no agents are running yet.
# Short enough to feel responsive when the first container comes up;
# long enough that we don't hammer `docker ps`.
_WAIT_POLL_SECONDS = 2.0


def _resolve_agents(layout: ProjectLayout, wait: bool) -> list[str]:
    """Get the current running agent list. If wait=True and the list is
    empty, poll until agents appear (or Ctrl-C). Returns the agent list
    (possibly empty if wait=False)."""
    agents = list_running(layout)
    if agents or not wait:
        return agents
    click.echo(
        click.style(
            f"No running agents yet. Polling every {_WAIT_POLL_SECONDS:.0f}s "
            "(Ctrl-C to stop)...",
            fg="bright_black",
        )
    )
    try:
        while not agents:
            time.sleep(_WAIT_POLL_SECONDS)
            agents = list_running(layout)
    except KeyboardInterrupt:
        click.echo("\nStopping wait.")
        return []
    click.echo(
        click.style(f"Found {len(agents)} agent(s); streaming.", fg="bright_black")
    )
    return agents


def _color_for(index: int) -> str:
    return _AGENT_COLORS[index % len(_AGENT_COLORS)]


def _write(prefix: str, color: str, line: str) -> None:
    """Atomic prefixed write. Threads serialize on `_stdout_lock`."""
    with _stdout_lock:
        click.echo(click.style(f"{prefix:>32} |", fg=color) + " " + line)


def _snapshot(agents: list[str], tail: int) -> None:
    """Read last N lines from each agent serially."""
    for idx, agent in enumerate(agents):
        color = _color_for(idx)
        log.debug("docker logs --tail %d %s", tail, agent)
        proc = subprocess.run(
            ["docker", "logs", "--tail", str(tail), agent],
            capture_output=True,
            text=True,
            check=False,
        )
        # `docker logs` writes container stdout to its stdout and stderr to
        # its stderr by default. Merge so we see everything in order.
        combined = (proc.stdout or "") + (proc.stderr or "")
        if not combined.strip():
            _write(agent, color, "(no output yet)")
            continue
        for line in combined.splitlines():
            _write(agent, color, line)


def _follow(agents: list[str], tail: int) -> None:
    """Spawn one reader thread per agent; stream until Ctrl-C."""
    click.echo(click.style(f"Following {len(agents)} agent(s). Ctrl-C to stop.", fg="bright_black"))
    threads: list[threading.Thread] = []
    procs: list[subprocess.Popen[str]] = []
    for idx, agent in enumerate(agents):
        color = _color_for(idx)
        proc = subprocess.Popen(
            ["docker", "logs", "-f", "--tail", str(tail), agent],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # merge so we don't miss container stderr
            text=True,
            bufsize=1,
        )
        procs.append(proc)
        t = threading.Thread(target=_stream_one, args=(agent, color, proc), daemon=True)
        t.start()
        threads.append(t)

    # Poll-style join so SIGINT is responsive on Windows.
    try:
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(timeout=0.5)
    except KeyboardInterrupt:
        click.echo("\nStopping follow.")
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()


def _stream_one(agent: str, color: str, proc: subprocess.Popen[str]) -> None:
    """Drain a long-running `docker logs -f` until the process ends."""
    assert proc.stdout is not None
    try:
        for raw in proc.stdout:
            _write(agent, color, raw.rstrip("\n"))
    except Exception as exc:
        # Log + exit the thread on any failure - we don't want one
        # misbehaving container to take down the whole follow view.
        log.debug("reader thread for %s exiting: %s", agent, exc)
