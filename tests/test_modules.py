import pytest

from adws.adw_modules.cache import PromptCache, cache_key, cached_run
from adws.adw_modules.context import build_context, render_files
from adws.adw_modules.router import Budget, BudgetExceeded, downgrade, route, route_role
from adws.adw_modules.state import RunState
from core.llm import MockRunner
from core.types import AgentRequest, Usage


def test_router_and_budget_pressure():
    assert route("mechanical") == "haiku" and route("heavy", "heavy") == "opus"
    b = Budget(1.0)
    assert route_role("architect", "heavy", b) == "opus"
    b.add(Usage(cost_usd=0.85))
    assert b.under_pressure and route_role("architect", "heavy", b) == "sonnet"
    assert downgrade("opus", b) == "sonnet" and downgrade("haiku", b) == "haiku"
    b.add(Usage(cost_usd=0.2))
    assert b.exceeded and b.remaining == 0.0
    with pytest.raises(BudgetExceeded):
        b.check()
    assert Budget(0).remaining is None and not Budget(0).exceeded


def test_context_budget_drops_read_only_by_priority(tmp_path):
    (tmp_path / "edit.py").write_text("e" * 400)
    (tmp_path / "ref1.py").write_text("r" * 400)
    (tmp_path / "ref2.py").write_text("r" * 4000)
    b = build_context(tmp_path, ["edit.py"], ["ref1.py", "ref2.py"], token_budget=300)
    assert list(b.files) == ["edit.py", "ref1.py"] and b.dropped == ["ref2.py"] and not b.over_budget
    assert "Omitted for token budget" in render_files(b)
    assert build_context(tmp_path, ["ref2.py"], [], token_budget=100).over_budget


def test_cache_only_serves_read_only_roles(tmp_path):
    (tmp_path / "a.py").write_text("v1")
    cache = PromptCache(tmp_path / "cache")
    runner = MockRunner()
    judge = AgentRequest(role="evaluator", prompt="Exit code: 0\n", working_dir=str(tmp_path), editable=["a.py"])
    first = cached_run(runner, judge, cache)
    second = cached_run(runner, judge, cache)
    assert not first.cached and second.cached and len(runner.calls) == 1
    (tmp_path / "a.py").write_text("v2")  # context changed -> new key
    assert not cached_run(runner, judge, cache).cached
    coder = AgentRequest(role="coder", prompt="p", working_dir=str(tmp_path), editable=["a.py"])
    cached_run(runner, coder, cache)
    cached_run(runner, coder, cache)
    assert sum(1 for c in runner.calls if c.role == "coder") == 2


def test_cache_key_ignores_volatile_tokens(tmp_path):
    a = AgentRequest(role="architect", prompt="run deadbeef at 2026-09-28T10:00:00Z", working_dir=str(tmp_path))
    b = a.model_copy(update={"prompt": "run  cafebabe at 2026-09-29T11:00:00Z"})
    assert cache_key(a) == cache_key(b)


def test_run_state_is_persisted():
    s = RunState("test")
    s.step("one", ok=True)
    data = (s.dir / "state.json").read_text()
    assert '"workflow": "test"' in data and '"one"' in data


@pytest.mark.parametrize("corrupt", ['{"output": "par', "", "not json", '{"success": "maybe"}'])
def test_a_corrupt_cache_entry_is_a_miss_and_is_rewritten(tmp_path, corrupt):
    cache = PromptCache(tmp_path / "cache")
    request = AgentRequest(role="architect", prompt="plan it", working_dir=str(tmp_path))
    entry = tmp_path / "cache" / f"{cache_key(request)}.json"
    entry.write_text(corrupt)
    runner = MockRunner()
    first = cached_run(runner, request, cache)
    assert not first.cached and len(runner.calls) == 1
    assert cached_run(runner, request, cache).cached and len(runner.calls) == 1  # the rewrite is a valid entry
    assert [p.name for p in (tmp_path / "cache").iterdir()] == [entry.name]      # no temp files left behind
