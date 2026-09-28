import os
import subprocess
import sys

import pytest

from .conftest import EXAMPLES, REPO


def run_tests(name: str, src: str | None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "PAC_EXAMPLE_SRC"}
    if src:
        env["PAC_EXAMPLE_SRC"] = src
    return subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"],
                          cwd=REPO / "examples" / name, env=env, capture_output=True, text=True)


@pytest.mark.parametrize("name", EXAMPLES)
def test_solution_passes_example_tests(name):
    r = run_tests(name, str(REPO / "examples" / name / "solution" / "src"))
    assert r.returncode == 0, r.stdout[-2000:]


@pytest.mark.parametrize("name", EXAMPLES)
def test_stub_fails_example_tests(name):
    assert run_tests(name, None).returncode == 1
