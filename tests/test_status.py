import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_factory import config, repo
from agent_factory import status as status_mod


def _has_git() -> bool:
    return shutil.which("git") is not None


pytestmark = pytest.mark.skipif(not _has_git(), reason="git not installed")


def test_snapshot_empty_project(project_dir: Path):
    """When upstream.git doesn't exist, snapshot returns zeros and no agents."""
    layout = config.discover(project_dir)
    with patch("agent_factory.status.container_status", return_value=[]):
        snap = status_mod.snapshot(layout)
    assert snap.commit_count == 0
    assert snap.total_files == 0
    assert snap.agents == []


def test_snapshot_after_init(project_dir: Path):
    layout = config.discover(project_dir)
    repo.init_upstream(layout)

    with (
        patch("agent_factory.status.container_status", return_value=[]),
        patch("agent_factory.status._collect_live_work", return_value={}),
    ):
        snap = status_mod.snapshot(layout)

    assert snap.commit_count == 1
    assert snap.total_files >= 1
    assert ".md" in snap.extensions
    assert snap.latest_commit  # non-empty


def test_render_short_includes_summary(project_dir: Path):
    layout = config.discover(project_dir)
    repo.init_upstream(layout)
    with patch("agent_factory.status.container_status", return_value=[]):
        snap = status_mod.snapshot(layout, short=True)
    text = status_mod.render(snap, short=True)
    assert "Agents running: 0" in text
    assert "Commits: 1" in text


def test_render_full_includes_task_locks_section(project_dir: Path):
    layout = config.discover(project_dir)
    repo.init_upstream(layout)
    with (
        patch("agent_factory.status.container_status", return_value=[]),
        patch("agent_factory.status._collect_live_work", return_value={}),
    ):
        snap = status_mod.snapshot(layout, short=False)
    text = status_mod.render(snap, short=False)
    assert "Active Task Locks" in text
    assert "Recent Commits" in text


def test_render_with_mocked_running_agents(project_dir: Path):
    layout = config.discover(project_dir)
    repo.init_upstream(layout)
    agents = [{"name": "agent-factory-x-1", "uptime": "2 minutes ago"}]
    with (
        patch("agent_factory.status.container_status", return_value=agents),
        patch(
            "agent_factory.status._collect_live_work",
            return_value={"agent-factory-x-1": ["M GOAL.md"]},
        ),
    ):
        snap = status_mod.snapshot(layout, short=False)
    text = status_mod.render(snap, short=False)
    assert "Agents running: 1" in text
    assert "agent-factory-x-1" in text
    assert "M GOAL.md" in text


def test_snapshot_with_log_tails(project_dir: Path):
    """include_log_tails=True populates agent_log_tails via _collect_log_tails."""
    layout = config.discover(project_dir)
    repo.init_upstream(layout)
    agents = [{"name": "agent-factory-x-1", "uptime": "2 minutes ago"}]
    with (
        patch("agent_factory.status.container_status", return_value=agents),
        patch("agent_factory.status._collect_live_work", return_value={}),
        patch(
            "agent_factory.status._collect_log_tails",
            return_value={"agent-factory-x-1": ["iter 1", "iter 2"]},
        ),
    ):
        snap = status_mod.snapshot(layout, short=False, include_log_tails=True)
    assert snap.agent_log_tails == {"agent-factory-x-1": ["iter 1", "iter 2"]}


def test_render_includes_log_tails_section(project_dir: Path):
    layout = config.discover(project_dir)
    repo.init_upstream(layout)
    agents = [{"name": "agent-factory-x-1", "uptime": "2 minutes ago"}]
    with (
        patch("agent_factory.status.container_status", return_value=agents),
        patch("agent_factory.status._collect_live_work", return_value={}),
        patch(
            "agent_factory.status._collect_log_tails",
            return_value={"agent-factory-x-1": ["iter 1"]},
        ),
    ):
        snap = status_mod.snapshot(layout, short=False, include_log_tails=True)
    text = status_mod.render(snap, short=False)
    assert "Recent Agent Output" in text
    assert "iter 1" in text


def test_short_render_still_emits_log_tails_if_collected(project_dir: Path):
    """Asking for tails on a short snapshot returns them - they're the
    whole reason to opt in."""
    layout = config.discover(project_dir)
    repo.init_upstream(layout)
    agents = [{"name": "agent-factory-x-1", "uptime": "2 minutes ago"}]
    with (
        patch("agent_factory.status.container_status", return_value=agents),
        patch(
            "agent_factory.status._collect_log_tails",
            return_value={"agent-factory-x-1": ["boot"]},
        ),
    ):
        snap = status_mod.snapshot(layout, short=True, include_log_tails=True)
    text = status_mod.render(snap, short=True)
    assert "boot" in text


def test_collect_log_tails_calls_docker_logs(project_dir: Path):
    """The actual `docker logs --tail N <name>` invocation produces the
    list[str] for each agent. Exercise this path directly so the
    higher-level tests can stay narrow."""
    agents = [{"name": "agent-factory-x-1", "uptime": "2 minutes ago"}]
    fake = type("X", (), {"stdout": "line1\nline2\n", "stderr": ""})()
    with patch("agent_factory.status.subprocess.run", return_value=fake) as srun:
        result = status_mod._collect_log_tails(agents, 7)
    assert result == {"agent-factory-x-1": ["line1", "line2"]}
    invoked_cmd = srun.call_args.args[0]
    assert invoked_cmd[:4] == ["docker", "logs", "--tail", "7"]
    assert invoked_cmd[-1] == "agent-factory-x-1"
