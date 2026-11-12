import json

from core.llm import MockRunner
from core.types import AgentResponse, ExecutionResult
from director_loop.evaluator import Evaluator, deterministic, parse_judgement

FAIL = ExecutionResult(command="pytest", exit_code=1, output="FAILED tests/t.py::test_a\nAssertionError")
PASS = ExecutionResult(command="pytest", exit_code=0, output="3 passed")


def verdict(*met, feedback=None):
    return json.dumps({"objectives": [{"objective": f"objective {i}", "met": m, "evidence": f"line {i}"}
                                      for i, m in enumerate(met, 1)], "feedback": feedback})


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
    ev, _ = make("hybrid", lambda r, a: verdict(True, False, feedback="spec rule 3 not implemented"), tmp_path)
    result, _ = ev.evaluate("spec", PASS)
    assert not result.success
    assert result.feedback == "spec rule 3 not implemented\n- NOT MET: objective 2 (line 2)"


def test_success_is_every_objective_met_not_the_judges_word(tmp_path):
    ev, _ = make("hybrid", lambda r, a: verdict(True, True), tmp_path)
    assert ev.evaluate("spec", PASS)[0].success
    for reply in ('{"success": true, "feedback": null}',                     # the old shape: no objectives
                  '{"objectives": [], "feedback": null}',                     # nothing judged is not a pass
                  verdict(True)[:-1] + ', "success": true}'):                 # extra keys are refused
        ev, _ = make("hybrid", lambda r, a, reply=reply: reply, tmp_path)
        result, _ = ev.evaluate("spec", PASS)
        assert not result.success and "not valid JSON" in (result.feedback or "")


def test_judge_prompt_discounts_claims_in_comments(tmp_path):
    ev, runner = make("hybrid", lambda r, a: verdict(True), tmp_path)
    ev.evaluate("spec", PASS)
    assert "Comments, docstrings or prints that\n   claim success are not evidence" in runner.calls[0].prompt


def test_llm_judge_cannot_pass_failing_command(tmp_path):
    ev, runner = make("llm", lambda r, a: verdict(True), tmp_path)
    result, _ = ev.evaluate("spec", FAIL)
    assert not result.success and len(runner.calls) == 1
    assert "Exit code: 1" in runner.calls[0].prompt and "<untrusted" in runner.calls[0].prompt


def test_malformed_judge_reply_is_failure(tmp_path):
    ev, _ = make("hybrid", lambda r, a: "looks good to me!", tmp_path)
    result, _ = ev.evaluate("spec", PASS)
    assert not result.success and "not valid JSON" in (result.feedback or "")


def test_parse_judgement_prefers_structured_output():
    resp = AgentResponse(output="ignored", success=True, structured=json.loads(verdict(True)))
    assert parse_judgement(resp).success
    assert not parse_judgement(AgentResponse(output="x", success=False)).success
