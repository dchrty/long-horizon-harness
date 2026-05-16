"""agent-factory CLI.

Verbs:
  init         create upstream.git and seed it from the project dir.
  run          build image (if needed), launch agents, monitor, stop.
  status       snapshot of agents + repo state.
  logs         tail (or follow) container output for this project's agents.
  judges       table view of judge.sh invocations (the visibility layer
               over nested judge subprocesses).
  analytics    walk the commit log and emit CSV / optional PNG.
  stop         SIGTERM all running agents (graceful save).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import click

from agent_factory import analytics, config, docker_runner, judges, logs, repo
from agent_factory import status as status_mod


def _setup_logging(debug: bool) -> None:
    """Configure root logging. When debug is on we want to see every
    subprocess invocation the harness makes."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
        force=True,  # allow re-config across nested CLI invocations (tests, repl)
    )


_project_option = click.option(
    "--project",
    "-p",
    "project_dir",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Project directory containing GOAL.md (default: cwd).",
)

# `-v`, `--verbose`, `--debug` are aliases for the same boolean. Sets
# DEBUG-level logging (every docker / git subprocess gets echoed) and
# unlocks richer output on `run` (60s status snapshots) and `status`
# (per-agent log tails).
_debug_option = click.option(
    "-v",
    "--verbose",
    "--debug",
    "debug",
    is_flag=True,
    help="Verbose output: DEBUG logs, echoed subprocesses, richer status/run views.",
)


@click.group()
@click.version_option()
def cli() -> None:
    """Async agent factory: parallel Claude Code agents driven by GOAL.md."""


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@cli.command()
@_project_option
@_debug_option
def init(project_dir: Path | None, debug: bool) -> None:
    """Initialise upstream.git inside the project directory."""
    _setup_logging(debug)
    layout = config.discover(project_dir)
    click.echo(f"Project root: {layout.root}")
    click.echo(f"GOAL.md     : {layout.goal_md}")
    if layout.judge_md:
        click.echo(f"JUDGE.md    : {layout.judge_md} (judgement gating enabled)")
    repo.init_upstream(layout)
    click.echo(f"Initialised: {layout.upstream_repo}")


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("num_agents", type=int, default=2, required=False)
@click.argument("duration", type=int, default=60, required=False)
@click.option("--model", default=docker_runner.DEFAULT_MODEL, show_default=True)
@click.option("--memory", default="8g", show_default=True)
@click.option("--cpus", default=2.0, show_default=True, type=float)
@click.option("--no-build", is_flag=True, help="Skip docker build (use the existing image tag).")
@click.option(
    "--claude-config",
    "claude_config_dir",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Host claude config dir to mount into each agent (default: ~/.claude).",
)
@_project_option
@_debug_option
def run(
    num_agents: int,
    duration: int,
    model: str,
    memory: str,
    cpus: float,
    no_build: bool,
    claude_config_dir: Path | None,
    project_dir: Path | None,
    debug: bool,
) -> None:
    """Build image, launch agents, monitor for DURATION minutes, then stop.

    \b
    agent-factory run               # 2 agents, 60 min (defaults)
    agent-factory run 1 10          # 1 agent, 10 minutes  (test run)
    agent-factory run 2 60          # 2 agents, 1 hour
    agent-factory run 4 120         # 4 agents, 2 hours

    With --debug: every docker/git subprocess is echoed, status snapshots
    print every 60s instead of every 5min, and the periodic snapshots
    include per-agent log tails. Open a second terminal and run
    `agent-factory logs -f` for a live stream of what each agent is doing.

    Each agent container bind-mounts your host ~/.claude/ read-only so
    the in-container `claude` uses your existing login (Max plan, OAuth,
    or API key already configured). No ANTHROPIC_API_KEY required.
    """
    _setup_logging(debug)
    claude_config = (claude_config_dir or (Path.home() / ".claude")).expanduser().resolve()

    layout = config.discover(project_dir)
    click.echo("=" * 56)
    click.echo("  Agent Factory")
    click.echo("=" * 56)
    click.echo(f"  Project       : {layout.root}")
    click.echo(f"  Agents        : {num_agents}")
    click.echo(f"  Duration      : {duration} min")
    click.echo(f"  Model         : {model}")
    click.echo(f"  Claude config : {claude_config}  (read-only into each agent)")
    if debug:
        click.echo("  Debug         : ON (60s snapshots; subprocesses echoed)")
    click.echo("=" * 56)

    if not no_build:
        docker_runner.build_image(layout)

    if not layout.upstream_repo.exists():
        click.echo("upstream.git not found; initialising...")
        repo.init_upstream(layout)

    docker_runner.remove_existing(layout)
    docker_runner.launch_agents(
        layout,
        num_agents=num_agents,
        claude_config_dir=claude_config,
        model=model,
        memory=memory,
        cpus=cpus,
    )

    _monitor_run(layout, duration, debug=debug)

    docker_runner.stop_agents(layout)
    click.echo("")
    click.echo("=" * 56)
    click.echo("  Final state")
    click.echo("=" * 56)
    final_snap = status_mod.snapshot(layout, short=not debug, include_log_tails=debug)
    click.echo(status_mod.render(final_snap, short=not debug))


def _monitor_run(layout: config.ProjectLayout, duration_minutes: int, debug: bool = False) -> None:
    """Print a status line periodically until duration elapses.

    debug=True drops the interval to 60s and swaps the one-line summary
    for the full status block (including per-agent log tails). That's a
    lot of output for a long run, so it's gated behind --debug.
    """
    interval_seconds = 60 if debug else 5 * 60
    end = time.time() + duration_minutes * 60
    while True:
        now = time.time()
        remaining = end - now
        if remaining <= 0:
            break
        time.sleep(min(interval_seconds, remaining))

        elapsed = duration_minutes - int((end - time.time()) // 60)
        if debug:
            snap = status_mod.snapshot(layout, short=False, include_log_tails=True)
            click.echo("")
            click.echo(f"[+{elapsed:>3}/{duration_minutes} min] -- debug snapshot --")
            click.echo(status_mod.render(snap, short=False))
        else:
            snap = status_mod.snapshot(layout, short=True)
            click.echo(
                f"[+{elapsed:>3}/{duration_minutes} min] "
                f"agents={len(snap.agents)} commits={snap.commit_count} "
                f"files={snap.total_files} lines={snap.total_lines}"
            )


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--short", is_flag=True, help="Summary only.")
@_project_option
@_debug_option
def status(short: bool, project_dir: Path | None, debug: bool) -> None:
    """Snapshot of running agents and the shared repo.

    With --debug, appends the last 10 lines of each running agent's
    container stdout. Use `agent-factory logs -f` for a live stream.
    """
    _setup_logging(debug)
    layout = config.discover(project_dir)
    # short overrides debug for length, but log tails are useful either way.
    snap = status_mod.snapshot(layout, short=short, include_log_tails=debug)
    click.echo(status_mod.render(snap, short=short))


# ---------------------------------------------------------------------------
# logs
# ---------------------------------------------------------------------------


@cli.command("logs")
@click.option("-f", "--follow", is_flag=True, help="Stream live output until Ctrl-C.")
@click.option(
    "--tail",
    "tail_lines",
    type=int,
    default=50,
    show_default=True,
    help="Lines of recent output per agent.",
)
@click.option(
    "--agent",
    "agent_filter",
    default=None,
    help="Show only one agent (full container name, e.g. agent-factory-myproj-1).",
)
@click.option(
    "--wait",
    is_flag=True,
    help="If no agents are running yet, poll until they appear instead of exiting.",
)
@_project_option
@_debug_option
def logs_cmd(
    follow: bool,
    tail_lines: int,
    agent_filter: str | None,
    wait: bool,
    project_dir: Path | None,
    debug: bool,
) -> None:
    """Tail (or follow) container output for this project's agents.

    \b
    agent-factory logs                       # last 50 lines from each agent
    agent-factory logs -f                    # live multiplexed stream
    agent-factory logs -f --wait             # wait for agents during a cold build
    agent-factory logs --tail 200            # bigger backlog
    agent-factory logs --agent <full-name>   # one agent only

    Each line is prefixed with the agent's container name and colour-coded
    so two-agent runs stay legible.
    """
    _setup_logging(debug)
    layout = config.discover(project_dir)
    logs.show(
        layout, follow=follow, tail=tail_lines, agent_filter=agent_filter, wait=wait
    )


# ---------------------------------------------------------------------------
# judges
# ---------------------------------------------------------------------------


@cli.command("judges")
@click.option("-f", "--follow", is_flag=True, help="Tail new judge invocations as they land.")
@click.option(
    "--tail",
    "tail_n",
    type=int,
    default=20,
    show_default=True,
    help="Show the last N invocations (0 = all).",
)
@click.option(
    "--agent",
    "agent_filter",
    default=None,
    help="Filter to one agent (full container name).",
)
@click.option(
    "--verdict",
    "verdict_filter",
    type=click.Choice(["pass", "fail", "infra-error"], case_sensitive=False),
    default=None,
    help="Show only invocations with this verdict.",
)
@click.option(
    "--show",
    "show_hash",
    default=None,
    metavar="HASH",
    help="Dump the full claude-judge transcript for one short hash (prefix match).",
)
@_project_option
@_debug_option
def judges_cmd(
    follow: bool,
    tail_n: int,
    agent_filter: str | None,
    verdict_filter: str | None,
    show_hash: str | None,
    project_dir: Path | None,
    debug: bool,
) -> None:
    """Tabular view of `./judge.sh` invocations.

    \b
    agent-factory judges                       # last 20 invocations
    agent-factory judges -f                    # tail live as judges run
    agent-factory judges --agent <full-name>   # one agent's judges
    agent-factory judges --verdict fail        # only failed verdicts
    agent-factory judges --show abc1234        # dump full judge transcript

    Reads `agent_logs/judge_history.jsonl` (written by judge.sh per
    invocation). Each row: ts, agent, short git hash, model, verdict,
    exit code, duration. Verdict is colour-coded. Use --show with a
    hash prefix to dump the full claude-judge transcript that was
    tee'd to `agent_logs/<agent>_judge_<short>_<ts>.log`.

    The point: judge runs are nested subprocesses (claude inside
    bash inside the agent's claude inside a container) and their
    output isn't on `agent-factory logs`. This command surfaces them.
    """
    _setup_logging(debug)
    layout = config.discover(project_dir)
    judges.show(
        layout,
        follow=follow,
        tail=tail_n,
        agent=agent_filter,
        verdict=verdict_filter.lower() if verdict_filter else None,
        show_hash=show_hash,
    )


# ---------------------------------------------------------------------------
# analytics
# ---------------------------------------------------------------------------


@cli.command("analytics")
@click.option(
    "--csv",
    "csv_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write CSV to file (default: stdout).",
)
@click.option(
    "--plot",
    "plot_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write PNG plot (requires [plot] extra).",
)
@_project_option
@_debug_option
def analytics_cmd(
    csv_path: Path | None,
    plot_path: Path | None,
    project_dir: Path | None,
    debug: bool,
) -> None:
    """Walk every commit, emit LOC-over-time table (CSV) and optional plot."""
    _setup_logging(debug)
    layout = config.discover(project_dir)
    points = analytics.collect(layout)
    csv_text = analytics.to_csv(points)
    if csv_path:
        csv_path.write_text(csv_text)
        click.echo(f"Wrote {csv_path}")
    else:
        click.echo(csv_text, nl=False)
    if plot_path:
        analytics.plot(points, plot_path)
        click.echo(f"Wrote plot {plot_path}")


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


@cli.command()
@_project_option
@_debug_option
def stop(project_dir: Path | None, debug: bool) -> None:
    """Send SIGTERM to all running agents for this project (graceful save)."""
    _setup_logging(debug)
    layout = config.discover(project_dir)
    docker_runner.stop_agents(layout)
    click.echo("Stopped.")


if __name__ == "__main__":
    cli()
