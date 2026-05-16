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


def test_init_upstream_seeds_judge_sh_with_lf_line_endings(project_dir: Path):
    """Agent containers must see LF-terminated judge.sh. A shebang with
    a trailing CR makes Linux fail with `exec ./judge.sh: no such file
    or directory` when invoked. Regression test for the same bug class
    as docker_runner._materialise_template_dir.

    We force `core.autocrlf=false` on the verification clone so the
    test reflects what agents actually see (containers always have
    autocrlf=false). Without that override, a Windows host with the
    default Git-for-Windows config translates LF -> CRLF on checkout,
    masking what's actually in the upstream objects."""
    (project_dir / "JUDGE.md").write_text("# judge\n")
    layout = config.discover(project_dir)
    repo.init_upstream(layout)

    clone = project_dir / "_check_endings"
    subprocess.run(
        [
            "git",
            "-c",
            "core.autocrlf=false",
            "clone",
            str(layout.upstream_repo),
            str(clone),
        ],
        check=True,
        capture_output=True,
    )
    judge_sh_bytes = (clone / "judge.sh").read_bytes()
    assert b"\r\n" not in judge_sh_bytes, (
        "judge.sh contains CRLF line endings; agents will fail with "
        "`exec ./judge.sh: no such file or directory` on Linux"
    )
    assert b"\r" not in judge_sh_bytes, "judge.sh contains stray CR bytes"
    # The verdicts.json scaffold is JSON (parsers tolerate CRLF) but we
    # write all templates uniformly via write_bytes, so it should also
    # be LF-clean.
    verdicts_bytes = (clone / "verdicts.json").read_bytes()
    assert b"\r" not in verdicts_bytes


def test_init_upstream_snapshots_project_directory(project_dir: Path):
    """Everything in the project root (minus harness state) is seeded verbatim."""
    (project_dir / "sub").mkdir()
    (project_dir / "sub" / "a.txt").write_text("alpha\n")
    (project_dir / "top.txt").write_text("top\n")

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
    assert (clone / "GOAL.md").is_file()


def test_init_upstream_skips_harness_state_and_dev_clutter(project_dir: Path):
    """upstream.git, agent_logs, .venv, __pycache__ etc. must NOT be seeded."""
    (project_dir / "agent_logs").mkdir()
    (project_dir / "agent_logs" / "stale.log").write_text("noise\n")
    (project_dir / ".venv").mkdir()
    (project_dir / ".venv" / "marker").write_text("noise\n")
    (project_dir / "__pycache__").mkdir()
    (project_dir / "__pycache__" / "x.pyc").write_text("noise\n")
    (project_dir / "node_modules").mkdir()
    (project_dir / "node_modules" / "junk").write_text("noise\n")
    (project_dir / "keep.txt").write_text("yes\n")

    layout = config.discover(project_dir)
    repo.init_upstream(layout)

    clone = project_dir / "_check"
    subprocess.run(
        ["git", "clone", str(layout.upstream_repo), str(clone)],
        check=True,
        capture_output=True,
    )
    assert (clone / "keep.txt").is_file()
    assert not (clone / "agent_logs").exists()
    assert not (clone / ".venv").exists()
    assert not (clone / "__pycache__").exists()
    assert not (clone / "node_modules").exists()


def test_init_upstream_refuses_when_repo_exists(project_dir: Path):
    layout = config.discover(project_dir)
    repo.init_upstream(layout)
    with pytest.raises(FileExistsError):
        repo.init_upstream(layout)
