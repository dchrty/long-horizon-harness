"""Unit tests for docker_runner with Docker mocked."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_factory import config, docker_runner


@pytest.fixture
def layout(project_dir: Path):
    return config.discover(project_dir)


def _ok(stdout: str = "", stderr: str = "", code: int = 0) -> MagicMock:
    res = MagicMock()
    res.returncode = code
    res.stdout = stdout
    res.stderr = stderr
    return res


def test_list_running_parses_names(layout):
    with patch(
        "agent_factory.docker_runner.subprocess.run",
        return_value=_ok(stdout=f"{layout.run_prefix}-1\n{layout.run_prefix}-2\n"),
    ):
        assert docker_runner.list_running(layout) == [
            f"{layout.run_prefix}-1",
            f"{layout.run_prefix}-2",
        ]


def test_list_running_returns_empty_on_failure(layout):
    with patch("agent_factory.docker_runner.subprocess.run", return_value=_ok(code=1)):
        assert docker_runner.list_running(layout) == []


def test_container_status_parses_tab_separated(layout):
    out = f"{layout.run_prefix}-1\t3 minutes ago\n{layout.run_prefix}-2\t5 minutes ago\n"
    with patch("agent_factory.docker_runner.subprocess.run", return_value=_ok(stdout=out)):
        rows = docker_runner.container_status(layout)
    assert rows == [
        {"name": f"{layout.run_prefix}-1", "uptime": "3 minutes ago"},
        {"name": f"{layout.run_prefix}-2", "uptime": "5 minutes ago"},
    ]


def test_launch_agents_builds_correct_docker_run_command(layout, tmp_path):
    captured: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        captured.append(cmd)
        return _ok()

    # Fake a host ~/.claude dir for the mount target check
    fake_claude = tmp_path / "host-claude"
    fake_claude.mkdir()

    with (
        patch("agent_factory.docker_runner._docker_available"),
        patch("agent_factory.docker_runner.subprocess.run", side_effect=fake_run),
    ):
        names = docker_runner.launch_agents(
            layout,
            num_agents=2,
            claude_config_dir=fake_claude,
            model="claude-opus-4-6",
            memory="4g",
            cpus=1,
        )
    assert names == [f"{layout.run_prefix}-1", f"{layout.run_prefix}-2"]
    assert layout.log_dir.is_dir()
    # Inspect the first docker run call
    first = captured[0]
    assert first[0:2] == ["docker", "run"]
    assert "--name" in first and f"{layout.run_prefix}-1" in first
    assert f"{layout.upstream_repo}:/upstream:rw" in first
    assert f"{fake_claude}:/home/agent/.claude:ro" in first
    # No API key gets passed
    assert not any("ANTHROPIC_API_KEY" in arg for arg in first)
    assert f"AGENT_ID={layout.run_prefix}-1" in first
    assert "AGENT_MODEL=claude-opus-4-6" in first
    assert "--memory" in first and "4g" in first


def test_launch_agents_rejects_missing_claude_config(layout, tmp_path):
    missing = tmp_path / "nope"
    with (
        patch("agent_factory.docker_runner._docker_available"),
        patch("agent_factory.docker_runner.subprocess.run"),
    ):
        with pytest.raises(docker_runner.DockerError, match="claude config directory not found"):
            docker_runner.launch_agents(layout, num_agents=1, claude_config_dir=missing)


def test_launch_agents_raises_on_docker_failure(layout, tmp_path):
    fake_claude = tmp_path / "host-claude"
    fake_claude.mkdir()
    with (
        patch("agent_factory.docker_runner._docker_available"),
        patch(
            "agent_factory.docker_runner.subprocess.run",
            return_value=_ok(code=125, stderr="container name in use"),
        ),
    ):
        with pytest.raises(docker_runner.DockerError, match="Failed to start"):
            docker_runner.launch_agents(layout, num_agents=1, claude_config_dir=fake_claude)


def test_stop_agents_sends_sigterm_with_grace(layout):
    with patch("agent_factory.docker_runner.list_running", return_value=[f"{layout.run_prefix}-1"]):
        captured: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            captured.append(cmd)
            return _ok()

        with patch("agent_factory.docker_runner.subprocess.run", side_effect=fake_run):
            docker_runner.stop_agents(layout, grace_seconds=30)
    assert captured[0][0:4] == ["docker", "stop", "-t", "30"]
    assert f"{layout.run_prefix}-1" in captured[0]
