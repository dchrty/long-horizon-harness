from pathlib import Path

import pytest

from agent_factory import config


def test_discover_minimal(project_dir: Path):
    layout = config.discover(project_dir)
    assert layout.root == project_dir.resolve()
    assert layout.goal_md == project_dir / "GOAL.md"
    assert layout.judge_md is None
    assert layout.seed_dir is None
    assert layout.upstream_repo == project_dir / "upstream.git"
    assert layout.log_dir == project_dir / "agent_logs"


def test_discover_with_judge(project_dir: Path):
    (project_dir / "JUDGE.md").write_text("# judge\n")
    layout = config.discover(project_dir)
    assert layout.judge_md == project_dir / "JUDGE.md"


def test_discover_with_seed(project_dir: Path):
    (project_dir / "seed").mkdir()
    (project_dir / "seed" / "hello.txt").write_text("hi\n")
    layout = config.discover(project_dir)
    assert layout.seed_dir == project_dir / "seed"


def test_discover_missing_goal_md(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match=r"GOAL\.md"):
        config.discover(tmp_path)


def test_discover_missing_dir():
    with pytest.raises(FileNotFoundError):
        config.discover("/this/does/not/exist/anywhere/123")


def test_run_prefix_sanitises_dir_name(tmp_path: Path):
    weird = tmp_path / "Proj!ect@With_Stuff-2025"
    weird.mkdir()
    (weird / "GOAL.md").write_text("x")
    layout = config.discover(weird)
    # Non-[a-zA-Z0-9_] stripped; underscores kept.
    assert layout.run_prefix == "agent-factory-ProjectWith_Stuff2025"
    assert layout.image_tag.endswith(":latest")
