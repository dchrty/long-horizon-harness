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
