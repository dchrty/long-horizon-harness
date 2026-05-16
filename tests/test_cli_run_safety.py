"""Tests for the `agent-factory run` safety check that refuses to start
when another run is already live against the same project.

The hazard we're guarding against:
  - User starts run A (60 min timer).
  - User accidentally starts run B (10 min timer) against the same project.
  - 10 min later, A is still running but B's timer expires and B calls
    stop_agents(layout), which filters by prefix - matching A's containers
    too. A's agents get SIGTERM'd mid-iteration. Silent data loss.

The fix: refuse-to-start by default if `list_running` returns anything;
user must `agent-factory stop` first or pass --force. These tests cover
the three resulting paths.
"""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from agent_factory import cli


def test_run_refuses_when_containers_already_exist(project_dir, tmp_path):
    runner = CliRunner()
    fake_claude = tmp_path / "host-claude"
    fake_claude.mkdir()
    with patch(
        "agent_factory.docker_runner.list_running",
        return_value=["agent-factory-x-1", "agent-factory-x-2"],
    ):
        result = runner.invoke(
            cli.cli,
            [
                "run",
                "1",
                "1",
                "--project",
                str(project_dir),
                "--claude-config",
                str(fake_claude),
            ],
        )
    assert result.exit_code == 2, f"expected exit 2, got {result.exit_code}: {result.output}"
    assert "Refusing to start" in result.output
    # Both existing container names should be enumerated for the user.
    assert "agent-factory-x-1" in result.output
    assert "agent-factory-x-2" in result.output
    # Recovery instructions must point at the two valid paths.
    assert "agent-factory stop" in result.output
    assert "--force" in result.output


def test_run_force_proceeds_past_existing_containers(project_dir, tmp_path):
    """--force should bypass the check and continue into the normal
    remove_existing + launch_agents flow."""
    runner = CliRunner()
    fake_claude = tmp_path / "host-claude"
    fake_claude.mkdir()
    with (
        patch(
            "agent_factory.docker_runner.list_running",
            return_value=["agent-factory-x-1"],
        ),
        patch("agent_factory.docker_runner.remove_existing") as remove_mock,
        patch("agent_factory.docker_runner.launch_agents") as launch_mock,
        patch("agent_factory.docker_runner.stop_agents"),
        patch("agent_factory.cli._monitor_run"),
        patch("agent_factory.repo.init_upstream"),
        # snapshot/render are called for the "Final state" block.
        patch("agent_factory.status.snapshot"),
        patch("agent_factory.status.render", return_value=""),
    ):
        result = runner.invoke(
            cli.cli,
            [
                "run",
                "1",
                "1",
                "--force",
                "--no-build",
                "--project",
                str(project_dir),
                "--claude-config",
                str(fake_claude),
            ],
        )
    assert result.exit_code == 0, f"unexpected non-zero exit: {result.output!r}; exc={result.exception!r}"
    # --force still cleans up exited containers before launching new ones.
    assert remove_mock.called
    assert launch_mock.called


def test_run_proceeds_when_no_existing_containers(project_dir, tmp_path):
    """Default behavior: clean state, run proceeds normally."""
    runner = CliRunner()
    fake_claude = tmp_path / "host-claude"
    fake_claude.mkdir()
    with (
        patch("agent_factory.docker_runner.list_running", return_value=[]),
        patch("agent_factory.docker_runner.remove_existing"),
        patch("agent_factory.docker_runner.launch_agents") as launch_mock,
        patch("agent_factory.docker_runner.stop_agents"),
        patch("agent_factory.cli._monitor_run"),
        patch("agent_factory.repo.init_upstream"),
        patch("agent_factory.status.snapshot"),
        patch("agent_factory.status.render", return_value=""),
    ):
        result = runner.invoke(
            cli.cli,
            [
                "run",
                "1",
                "1",
                "--no-build",
                "--project",
                str(project_dir),
                "--claude-config",
                str(fake_claude),
            ],
        )
    assert result.exit_code == 0, f"unexpected non-zero exit: {result.output!r}; exc={result.exception!r}"
    assert launch_mock.called
