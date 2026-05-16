import pytest


@pytest.fixture
def project_dir(tmp_path):
    """Create a minimal project directory with GOAL.md."""
    (tmp_path / "GOAL.md").write_text("# test goal\n")
    return tmp_path
