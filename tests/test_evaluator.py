from core.llm import MockRunner
from core.types import AgentResponse, ExecutionResult
from director_loop.evaluator import Evaluator, deterministic, parse_judgement

FAIL = ExecutionResult(command="pytest", exit_code=1, output="FAILED tests/t.py::test_a\nAssertionError")
PASS = ExecutionResult(command="pytest", exit_code=0, output="3 passed")


def make(kind, handler=None, tmp_path=None):
    runner = MockRunner({"evaluator": handler} if handler else None)
    return Evaluator(kind, runner, "haiku", tmp_path, ["a.py"], []), runner


def test_deterministic():
    assert deterministic(PASS).success
    v = deterministic(FAIL)
    assert not v.success and "test_a" in (v.feedback or "")


def test_hybrid_skips_judge_on_failing_gate(tmp_path):
    ev, runner = make("hybrid", tmp_path=tmp_path)
    verdict, _ = ev.evaluate("spec", FAIL)
    assert not verdict.success and runner.calls == []


def test_hybrid_judge_can_reject_green_tests(tmp_path):
    ev, _ = make("hybrid", lambda r, a: '{"success": false, "feedback": "spec rule 3 not implemented"}', tmp_path)
    verdict, _ = ev.evaluate("spec", PASS)
    assert not verdict.success and verdict.feedback == "spec rule 3 not implemented"


def test_llm_judge_cannot_pass_failing_command(tmp_path):
    ev, runner = make("llm", lambda r, a: '{"success": true, "feedback": null}', tmp_path)
    verdict, _ = ev.evaluate("spec", FAIL)
    assert not verdict.success and len(runner.calls) == 1
    assert "Exit code: 1" in runner.calls[0].prompt and "<untrusted" in runner.calls[0].prompt


def test_malformed_judge_reply_is_failure(tmp_path):
    ev, _ = make("hybrid", lambda r, a: "looks good to me!", tmp_path)
    verdict, _ = ev.evaluate("spec", PASS)
    assert not verdict.success and "not valid JSON" in (verdict.feedback or "")


def test_parse_judgement_prefers_structured_output():
    resp = AgentResponse(output="ignored", success=True, structured={"success": True, "feedback": None})
    assert parse_judgement(resp).success
    assert not parse_judgement(AgentResponse(output="x", success=False)).success
