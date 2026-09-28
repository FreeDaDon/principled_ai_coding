import os
import subprocess
import sys

import pytest

from specs.spec_to_tests import _return_type, _split_params, extract_contracts, main
from specs.spec_validator import parse_spec

from .conftest import EXAMPLES, REPO


def test_param_and_return_parsing():
    assert _split_params("opps: list[Opportunity], profile: CompanyProfile, min_score: int = 0") == ["opps", "profile", "min_score"]
    assert _split_params("self, a: dict[str, int], *args") == ["a", "args"]
    assert _return_type("list[Alert] USE the window rules") == "list[Alert]"
    assert _return_type("AuthEvent | None: sanitize first") == "AuthEvent | None"
    assert _return_type("dict[str, list[int]]:") == "dict[str, list[int]]"


def test_extracts_software_contracts():
    c = extract_contracts(parse_spec((REPO / "examples/software/spec.md").read_text()))
    assert [(f.module, f.name, f.returns) for f in c.functions] == [
        ("opportunity_scorer", "load_opportunities", "list[Opportunity]"),
        ("opportunity_scorer", "score_opportunity", "ScoredOpportunity"),
        ("opportunity_scorer", "rank_opportunities", "list[ScoredOpportunity]"),
    ]


@pytest.mark.parametrize("name", EXAMPLES)
def test_generated_contracts_pass_on_solution(example_copy, name):
    root = example_copy(name)
    out = root / "tests" / "test_generated_contract.py"
    assert main([str(root / "spec.md"), "--out", str(out)]) == 0
    env = {**os.environ, "PAC_EXAMPLE_SRC": str(root / "solution" / "src")}
    r = subprocess.run([sys.executable, "-m", "pytest", str(out), "-q", "-p", "no:cacheprovider"],
                       cwd=root, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:]
