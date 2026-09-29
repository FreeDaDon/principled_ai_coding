import json
from pathlib import Path

from core.llm import (
    ClaudeRunner,
    MockRunner,
    extract_json,
    parse_stream_json,
    render_template,
    usage_from_result,
)
from core.types import AgentRequest


def req(role, **kw):
    return AgentRequest(role=role, prompt="p", working_dir=kw.pop("working_dir", "."), **kw)


def test_parse_stream_json_takes_last_result():
    raw = "\n".join([
        json.dumps({"type": "system"}), "not json",
        json.dumps({"type": "result", "result": "first"}),
        json.dumps({"type": "result", "result": "done", "total_cost_usd": 0.12,
                    "usage": {"input_tokens": 10, "output_tokens": 5}}),
    ])
    result = parse_stream_json(raw)
    assert result is not None and result["result"] == "done"
    u = usage_from_result(result)
    assert (u.input_tokens, u.output_tokens, u.cost_usd) == (10, 5, 0.12)
    assert parse_stream_json("garbage") is None


def test_extract_json_tolerates_fences_and_prose():
    assert extract_json('Sure:\n```json\n{"success": true, "feedback": null}\n```') == {"success": True, "feedback": None}
    assert extract_json('verdict {"success": false, "feedback": "x"} end') == {"success": False, "feedback": "x"}
    assert extract_json("no json here") is None


def test_role_tool_boundaries_in_command():
    r = ClaudeRunner()
    coder = r.build_command(req("coder"))
    assert coder[coder.index("--tools") + 1] == "Read,Edit,Write,Glob,Grep"
    assert coder[coder.index("--permission-mode") + 1] == "acceptEdits"
    arch = r.build_command(req("architect"))
    assert "Edit" not in arch[arch.index("--tools") + 1]
    judge = r.build_command(req("evaluator", json_schema={"type": "object"}, max_budget_usd=0.5))
    assert judge[judge.index("--tools") + 1] == ""
    assert "--json-schema" in judge and judge[judge.index("--max-budget-usd") + 1] == "0.50"
    assert all("dangerously" not in part for part in coder + arch + judge)
    assert coder[coder.index("--setting-sources") + 1] == "project" and "--strict-mcp-config" in coder


def test_render_template_strips_frontmatter(tmp_path):
    t = tmp_path / "x.md"
    t.write_text("---\ndescription: d\n---\nFix $1 in $2. All: $ARGUMENTS")
    assert render_template(t, ["bug", "app.py"]) == "Fix bug in app.py. All: bug app.py"


def test_shipped_commands_render():
    root = Path(__file__).resolve().parents[1] / ".claude" / "commands"
    names = sorted(p.stem for p in root.glob("*.md"))
    assert names == ["architect", "bluf", "director", "gcp_triage", "heal", "idk", "mcp_review", "spec"]
    for p in root.glob("*.md"):
        assert "$ARGUMENTS" not in render_template(p, ["x"])


def test_mock_coder_applies_solution_on_second_attempt(tmp_path):
    (tmp_path / "solution").mkdir()
    (tmp_path / "solution" / "a.py").write_text("fixed")
    (tmp_path / "a.py").write_text("broken")
    runner = MockRunner()
    r = req("coder", working_dir=str(tmp_path), editable=["a.py"], metadata={"mock_solution": "solution"})
    runner.run(r)
    assert (tmp_path / "a.py").read_text() == "broken"
    runner.run(r)
    assert (tmp_path / "a.py").read_text() == "fixed"
