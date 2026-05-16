"""agent-factory CLI.

Verbs:
  init         create upstream.git and seed it from the project dir.
  run          build image (if needed), launch agents, monitor, stop.
  status       snapshot of agents + repo state.
  analytics    walk the commit log and emit CSV / optional PNG.
  stop         SIGTERM all running agents (graceful save).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import click

from agent_factory import analytics, config, docker_runner, repo
from agent_factory import status as status_mod


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )


_project_option = click.option(
    "--project",
    "-p",
    "project_dir",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Project directory containing GOAL.md (default: cwd).",
)
_verbose_option = click.option("-v", "--verbose", is_flag=True, help="Debug logging.")


@click.group()
@click.version_option()
def cli() -> None:
    """Async agent factory: parallel Claude Code agents driven by GOAL.md."""


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@cli.command()
@_project_option
@_verbose_option
def init(project_dir: Path | None, verbose: bool) -> None:
    """Initialise upstream.git inside the project directory."""
    _setup_logging(verbose)
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
@_verbose_option
def run(
    num_agents: int,
    duration: int,
    model: str,
    memory: str,
    cpus: float,
    no_build: bool,
    claude_config_dir: Path | None,
    project_dir: Path | None,
    verbose: bool,
) -> None:
    """Build image, launch agents, monitor for DURATION minutes, then stop.

    \b
    agent-factory run               # 2 agents, 60 min (defaults)
    agent-factory run 1 10          # 1 agent, 10 minutes  (test run)
    agent-factory run 2 60          # 2 agents, 1 hour
    agent-factory run 4 120         # 4 agents, 2 hours

    Each agent container bind-mounts your host ~/.claude/ read-only so
    the in-container `claude` uses your existing login (Max plan, OAuth,
    or API key already configured). No ANTHROPIC_API_KEY required.
    """
    _setup_logging(verbose)
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

    _monitor_run(layout, duration)

    docker_runner.stop_agents(layout)
    click.echo("")
    click.echo("=" * 56)
    click.echo("  Final state")
    click.echo("=" * 56)
    click.echo(status_mod.render(status_mod.snapshot(layout, short=True), short=True))


def _monitor_run(layout: config.ProjectLayout, duration_minutes: int) -> None:
    """Print a status line every 5 minutes until duration elapses."""
    interval_minutes = 5
    end = time.time() + duration_minutes * 60
    while True:
        now = time.time()
        remaining = end - now
        if remaining <= 0:
            break
        sleep_for = min(interval_minutes * 60, remaining)
        time.sleep(sleep_for)

        snap = status_mod.snapshot(layout, short=True)
        elapsed = duration_minutes - int((end - time.time()) // 60)
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
@_verbose_option
def status(short: bool, project_dir: Path | None, verbose: bool) -> None:
    """Snapshot of running agents and the shared repo."""
    _setup_logging(verbose)
    layout = config.discover(project_dir)
    snap = status_mod.snapshot(layout, short=short)
    click.echo(status_mod.render(snap, short=short))


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
@_verbose_option
def analytics_cmd(
    csv_path: Path | None,
    plot_path: Path | None,
    project_dir: Path | None,
    verbose: bool,
) -> None:
    """Walk every commit, emit LOC-over-time table (CSV) and optional plot."""
    _setup_logging(verbose)
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
@_verbose_option
def stop(project_dir: Path | None, verbose: bool) -> None:
    """Send SIGTERM to all running agents for this project (graceful save)."""
    _setup_logging(verbose)
    layout = config.discover(project_dir)
    docker_runner.stop_agents(layout)
    click.echo("Stopped.")


if __name__ == "__main__":
    cli()
