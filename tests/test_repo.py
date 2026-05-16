import shutil
import subprocess
from pathlib import Path

import pytest

from agent_factory import config, repo


def _has_git() -> bool:
    return shutil.which("git") is not None


pytestmark = pytest.mark.skipif(not _has_git(), reason="git not installed")


def test_init_upstream_creates_bare_and_seeds_goal(project_dir: Path):
    layout = config.discover(project_dir)
    repo.init_upstream(layout)

    assert (layout.upstream_repo / "HEAD").is_file()
    assert (layout.upstream_repo / "objects").is_dir()

    # Clone it and confirm seeded files exist
    clone = project_dir / "_check"
    subprocess.run(
        ["git", "clone", str(layout.upstream_repo), str(clone)],
        check=True,
        capture_output=True,
    )
    assert (clone / "GOAL.md").is_file()
    assert (clone / "current_tasks").is_dir()
    assert not (clone / "JUDGE.md").exists()
    assert not (clone / "judge.sh").exists()
    assert not (clone / "verdicts.json").exists()


def test_init_upstream_seeds_judge_artifacts_when_judge_md_present(project_dir: Path):
    (project_dir / "JUDGE.md").write_text("# judge\n")
    layout = config.discover(project_dir)
    repo.init_upstream(layout)

    clone = project_dir / "_check"
    subprocess.run(
        ["git", "clone", str(layout.upstream_repo), str(clone)],
        check=True,
        capture_output=True,
    )
    assert (clone / "GOAL.md").is_file()
    assert (clone / "JUDGE.md").is_file()
    assert (clone / "judge.sh").is_file()
    assert (clone / "verdicts.json").is_file()
    # verdicts.json is a valid empty scaffold
    import json

    data = json.loads((clone / "verdicts.json").read_text())
    assert data == {"version": 1, "verdicts": []}


def test_init_upstream_copies_seed_directory(project_dir: Path):
    seed = project_dir / "seed"
    seed.mkdir()
    (seed / "sub").mkdir()
    (seed / "sub" / "a.txt").write_text("alpha\n")
    (seed / "top.txt").write_text("top\n")

    layout = config.discover(project_dir)
    repo.init_upstream(layout)

    clone = project_dir / "_check"
    subprocess.run(
        ["git", "clone", str(layout.upstream_repo), str(clone)],
        check=True,
        capture_output=True,
    )
    assert (clone / "sub" / "a.txt").read_text() == "alpha\n"
    assert (clone / "top.txt").read_text() == "top\n"


def test_init_upstream_refuses_when_repo_exists(project_dir: Path):
    layout = config.discover(project_dir)
    repo.init_upstream(layout)
    with pytest.raises(FileExistsError):
        repo.init_upstream(layout)
