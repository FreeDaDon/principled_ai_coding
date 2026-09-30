import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = ["software", "devops", "security", "iam"]
PACK_FIXTURES = REPO / "tests" / "fixtures" / "packs"


@pytest.fixture(autouse=True)
def isolated_runs(tmp_path, monkeypatch):
    """Run state and cache go to a temp dir; every test runs offline."""
    monkeypatch.setenv("PAC_PROJECT_ROOT", str(tmp_path / "pac_home"))
    monkeypatch.setenv("PAC_RUNNER", "mock")
    monkeypatch.setenv("JEV_BACKEND", "mock")  # a live JEV_BACKEND or key in the shell must never reach a test
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("PAC_EXAMPLE_SRC", raising=False)


@pytest.fixture
def example_copy(tmp_path):
    def _copy(name: str) -> Path:
        dst = tmp_path / name
        shutil.copytree(REPO / "examples" / name, dst, ignore=shutil.ignore_patterns("__pycache__"))
        return dst
    return _copy


@pytest.fixture
def packs() -> Path:
    """Pack fixtures: planted issues (fake credentials only) plus one clean input per pack."""
    return PACK_FIXTURES
