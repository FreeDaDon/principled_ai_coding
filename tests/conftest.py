import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = ["software", "devops", "security", "iam"]


@pytest.fixture(autouse=True)
def isolated_runs(tmp_path, monkeypatch):
    """Run state and cache go to a temp dir; every test runs offline."""
    monkeypatch.setenv("PAC_PROJECT_ROOT", str(tmp_path / "pac_home"))
    monkeypatch.setenv("PAC_RUNNER", "mock")
    monkeypatch.delenv("PAC_EXAMPLE_SRC", raising=False)


@pytest.fixture
def example_copy(tmp_path):
    def _copy(name: str) -> Path:
        dst = tmp_path / name
        shutil.copytree(REPO / "examples" / name, dst, ignore=shutil.ignore_patterns("__pycache__"))
        return dst
    return _copy
