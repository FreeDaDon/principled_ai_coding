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


def test_commas_inside_strings_and_braces_do_not_split_params():
    assert _split_params("sep: str = ',', n: int") == ["sep", "n"]
    assert _split_params('quote: str = "a,b", q2: str = \'"\'') == ["quote", "q2"]
    assert _split_params('opts: dict = {"a": 1, "b": 2}, c: int') == ["opts", "c"]
    assert _split_params("a: int = max(1, 2), b: tuple[int, int] = (1, 2)") == ["a", "b"]


SPEC = """# T
## High-Level Objective
- x
## Mid-Level Objective
- x
## Implementation Notes
- x
## Context
### Beginning context
- my-module.py
### Ending context
- my-module.py
## Low-Level Tasks
1. One
```
UPDATE my-module.py: CREATE def helper(x) without a return annotation, then CREATE def run(sep: str = ',') -> int
```
2. Two
```
UPDATE my-module.py: CREATE def wide(
    a: int,
    b: str = "x, y",
) -> str
AND class Thing
```
"""


def test_multi_line_signatures_are_read_and_do_not_swallow_the_next_def():
    c = extract_contracts(parse_spec(SPEC))
    assert [(f.name, f.params, f.returns) for f in c.functions] == [("run", ["sep"], "int"), ("wide", ["a", "b"], "str")]


def test_a_non_identifier_module_generates_runnable_tests(tmp_path):
    (tmp_path / "spec.md").write_text(SPEC)
    (tmp_path / "my-module.py").write_text(
        "def run(sep: str = ',') -> int:\n    return 0\n\n\n"
        "def wide(a: int, b: str = 'x, y') -> str:\n    return b\n\n\nclass Thing:\n    pass\n")
    out = tmp_path / "test_contract.py"
    assert main([str(tmp_path / "spec.md"), "--out", str(out)]) == 0
    r = subprocess.run([sys.executable, "-m", "pytest", str(out), "-q", "-p", "no:cacheprovider"],
                       cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(tmp_path)}, capture_output=True, text=True)
    assert r.returncode == 0 and "3 passed" in r.stdout, r.stdout[-2000:]
