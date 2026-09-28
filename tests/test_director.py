import json

import pytest

from core.llm import MockRunner
from core.types import DirectorConfig
from director_loop.engine import Director, load_config, main

from .conftest import EXAMPLES


def director_for(path, runner=None, **overrides):
    config = load_config(path / "director.yaml").model_copy(update=overrides)
    return Director(config, path, runner=runner or MockRunner())


@pytest.mark.parametrize("name", EXAMPLES)
def test_loop_fails_then_heals_with_feedback(example_copy, name):
    root = example_copy(name)
    runner = MockRunner()
    result = director_for(root, runner).direct()
    assert result.success and result.stop_reason == "passed" and result.iterations == 2
    assert not result.history[0].evaluation.success
    second_prompt = [c for c in runner.calls if c.role == "coder"][1].prompt
    assert "attempt 2" in second_prompt and "FAILURES" in second_prompt and "<untrusted" in second_prompt
    editable = load_config(root / "director.yaml").context_editable[0]
    assert (root / editable).read_text() == (root / "solution" / editable).read_text()


def test_exhausted_iterations_roll_back(example_copy):
    root = example_copy("software")
    stub = (root / "src/opportunity_scorer.py").read_text()

    def half_fix(request, attempt):
        (root / "src/opportunity_scorer.py").write_text(stub + f"\n# attempt {attempt}\n")
        return "tried"

    result = director_for(root, MockRunner({"coder": half_fix}), max_iterations=2).direct()
    assert not result.success and result.stop_reason in ("max_iterations", "stagnation")
    assert result.rolled_back and (root / "src/opportunity_scorer.py").read_text() == stub


def test_stagnation_stops_early(example_copy):
    root = example_copy("software")
    result = director_for(root, MockRunner({"coder": lambda r, a: "no-op"}), max_iterations=5).direct()
    assert result.stop_reason == "stagnation" and result.iterations == 2


def test_keep_on_fail_leaves_edits(example_copy):
    root = example_copy("software")

    def edit(request, attempt):
        (root / "src/opportunity_scorer.py").write_text("# wip\n")
        return "wip"

    result = director_for(root, MockRunner({"coder": edit}), max_iterations=1).direct(keep_on_fail=True)
    assert not result.success and not result.rolled_back
    assert (root / "src/opportunity_scorer.py").read_text() == "# wip\n"


def test_out_of_bounds_edit_reverted_and_reported(example_copy):
    root = example_copy("software")
    tests_file = root / "tests/test_opportunity_scorer.py"
    original = tests_file.read_text()

    def cheat(request, attempt):
        tests_file.write_text("def test_nothing():\n    assert True\n")
        return "made the tests pass"

    runner = MockRunner({"coder": cheat})
    result = director_for(root, runner, max_iterations=2).direct()
    assert not result.success
    assert result.history[0].out_of_bounds == ["tests/test_opportunity_scorer.py"]
    assert tests_file.read_text() == original
    assert "REVERTED" in [c for c in runner.calls if c.role == "coder"][1].prompt


def test_budget_stop(example_copy):
    from core.types import AgentResponse, Usage

    root = example_copy("software")

    class PricyRunner(MockRunner):
        def run(self, request):
            resp = super().run(request)
            return AgentResponse(output=resp.output, success=True, usage=Usage(cost_usd=1.0))

    result = director_for(root, PricyRunner({"coder": lambda r, a: "x"}), budget_usd=1.0).direct()
    assert result.stop_reason == "budget" and result.iterations == 1


def test_config_paths_must_stay_inside(tmp_path):
    config = DirectorConfig(prompt="x", execution_command="true", context_editable=["../escape.py"])
    with pytest.raises(ValueError):
        Director(config, tmp_path, runner=MockRunner())


def test_inline_prompt_and_cli_json(example_copy, capsys):
    root = example_copy("software")
    assert main([str(root / "director.yaml"), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["success"] and out["stop_reason"] == "passed"
    inline = Director(DirectorConfig(prompt="UPDATE a.py: ADD def f() -> int", execution_command="true",
                                     context_editable=["a.py"]), root, runner=MockRunner())
    assert inline.base_prompt() == "UPDATE a.py: ADD def f() -> int"
