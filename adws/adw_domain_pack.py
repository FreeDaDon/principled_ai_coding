#!/usr/bin/env -S uv run
"""ADW: domain pack workflow (mcp_gov, gcp_sre). Deterministic analysis, agent interpretation, reports.

  analyze (core.packs, no LLM) -> findings.json + report.md
  interpret (read-only architect role; findings passed as a FILE PATH, never inlined) -> strict-JSON assessment
  report (report.md = findings + assessment; assessment.json) -> gate on --fail-on

Ship policy: propose only. The workflow writes reports under .pac/runs/<id>/ and nothing else. The agent has
read-only tools, the input tree is checked for changes afterwards, and every action that proposes a change is
forced to `requires_human_approval`. A human reviews the report and acts.

Usage:
  uv run adws/adw_domain_pack.py --pack mcp_gov --input vendor/connector/ --fail-on high
  uv run adws/adw_domain_pack.py --pack gcp_sre --input exports/ --no-agent      # deterministic only
  PAC_RUNNER=mock uv run adws/adw_domain_pack.py --pack gcp_sre --input tests/fixtures/packs/gcp_sre
Exit 0 = done, 1 = the workflow failed (bad input, agent error, malformed assessment, input changed),
2 = findings at or above --fail-on (the report is still written).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from pydantic import ValidationError

from adws.adw_modules.state import RunState
from core.llm import MockRunner, Runner, extract_json, get_runner, render_template
from core.packs import export
from core.packs.inputs import iter_files
from core.packs.registry import PACK_TOOLS, parse_opts, run_pack
from core.security import escape_markdown
from core.types import SEVERITY_ORDER, AgentAssessment, AgentRequest, AgentResponse, AnalysisReport

COMMANDS_DIR = Path(__file__).resolve().parents[1] / ".claude" / "commands"
PACK_COMMANDS = {"mcp_gov": "mcp_review", "gcp_sre": "gcp_triage"}
SHIP_POLICY = "propose_only"
FINDINGS_FILE = "findings.json"


def build_prompt(pack: str, findings_path: Path) -> str:
    """The slash command with the findings file path filled in. Finding text is never part of the prompt."""
    return render_template(COMMANDS_DIR / f"{PACK_COMMANDS[pack]}.md", [str(findings_path)])


def parse_assessment(response: AgentResponse) -> AgentAssessment:
    """Model output is untrusted: it must parse into AgentAssessment or the step fails."""
    raw = response.structured or extract_json(response.output)
    if raw is None:
        raise ValueError("agent reply contained no JSON object")
    try:
        return AgentAssessment.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"agent reply does not match the assessment schema: {exc.error_count()} error(s)") from exc


def enforce_approval(assessment: AgentAssessment) -> tuple[AgentAssessment, int]:
    """Fail closed: any action that proposes a change requires a human, whatever the agent said."""
    forced = 0
    actions = []
    for action in assessment.prioritized_actions:
        if action.proposed_change.strip() and not action.requires_human_approval:
            action = action.model_copy(update={"requires_human_approval": True})
            forced += 1
        actions.append(action)
    return assessment.model_copy(update={"prioritized_actions": actions}), forced


def render_assessment(assessment: AgentAssessment) -> str:
    """Markdown for the agent's assessment; every field is model output and gets escaped."""
    lines = [f"## Agent assessment: risk **{assessment.risk_rating}**", "", escape_markdown(assessment.summary), ""]
    if assessment.prioritized_actions:
        lines += ["| Priority | Action | Human approval | Findings |", "|---|---|---|---|"]
        for a in sorted(assessment.prioritized_actions, key=lambda x: x.priority):
            lines.append(f"| {a.priority} | {escape_markdown(a.title)} | {'required' if a.requires_human_approval else 'no'} "
                         f"| {escape_markdown(', '.join(a.finding_refs))} |")
        lines += ["", "### Proposed changes (text for a human; nothing was applied)"]
        lines += [f"- {a.priority} {escape_markdown(a.title)}: {escape_markdown(a.proposed_change)}"
                  for a in assessment.prioritized_actions if a.proposed_change.strip()]
    if assessment.false_positives:
        lines += ["", "### Likely false positives"]
        lines += [f"- {escape_markdown(fp.finding_ref)}: {escape_markdown(fp.reason)}" for fp in assessment.false_positives]
    return "\n".join(lines) + "\n"


def mock_assessment(request: AgentRequest, attempt: int) -> str:
    """Deterministic stand-in for the agent (PAC_RUNNER=mock): one action per critical/high rule id."""
    data = json.loads((Path(request.working_dir) / request.read_only[0]).read_text())
    findings = [f for r in data["reports"] for f in r["findings"]]
    worst = max((f["severity"] for f in findings), key=lambda s: SEVERITY_ORDER[s], default="info")
    actions = []
    for rule_id in sorted({f["rule_id"] for f in findings if f["severity"] in ("critical", "high")}):
        first = next(f for f in findings if f["rule_id"] == rule_id)
        actions.append({"title": f"Address {rule_id}", "priority": "P1" if first["severity"] == "critical" else "P2",
                        "rationale": first["title"], "finding_refs": [rule_id], "requires_human_approval": True,
                        "proposed_change": first["recommendation"]})
    return json.dumps({"risk_rating": worst if worst in ("critical", "high", "medium") else "low",
                       "summary": f"Mock assessment: {len(findings)} finding(s), worst severity {worst}.",
                       "prioritized_actions": actions, "false_positives": []})


def tree_fingerprint(path: Path) -> list[tuple[str, int, int]]:
    """(relative path, size, mtime) of every readable file under the input; used to prove nothing was edited."""
    root = path if path.is_dir() else path.parent
    return [(p.relative_to(root).as_posix(), p.stat().st_size, p.stat().st_mtime_ns) for p in iter_files(path)]


def run_workflow(
    pack: str,
    input_path: Path,
    tool: str | None = None,
    opts: dict[str, object] | None = None,
    model: str = "sonnet",
    use_agent: bool = True,
    fail_on: str | None = None,
    runner: Runner | None = None,
) -> int:
    state = RunState(f"pack_{pack}")
    state.update(pack=pack, input=str(input_path), ship_policy=SHIP_POLICY)
    before = tree_fingerprint(input_path) if input_path.exists() else []
    try:
        reports: list[AnalysisReport] = run_pack(pack, input_path, tool, **(opts or {}))
    except (ValueError, FileNotFoundError) as exc:
        print(f"FAIL: {exc}")
        return 1
    if not reports:
        print(f"FAIL: no recognizable {pack} inputs at {input_path}")
        return 1
    findings_path = state.log(FINDINGS_FILE, export.to_json(reports))
    report_md = export.render_reports(reports)
    report_path = state.log("report.md", report_md)
    total = sum(len(r.findings) for r in reports)
    state.step("analyze", tools=[r.tool for r in reports], findings=total)
    print(f"analyzed {len(reports)} report(s), {total} finding(s): {report_path}")

    if use_agent:
        request = AgentRequest(
            role="architect", prompt=build_prompt(pack, findings_path), model=model, working_dir=str(state.dir),
            read_only=[FINDINGS_FILE], json_schema=AgentAssessment.model_json_schema(), log_dir=str(state.dir))
        state.log("interpret_prompt.md", request.prompt)
        response = (runner or get_runner()).run(request)
        state.step("interpret", success=response.success, cost_usd=response.usage.cost_usd)
        if not response.success:
            print(f"FAIL: interpretation failed: {response.output[:300]}\n  deterministic report kept: {report_path}")
            return 1
        try:
            assessment, forced = enforce_approval(parse_assessment(response))
        except ValueError as exc:
            print(f"FAIL: {exc}\n  deterministic report kept: {report_path}")
            return 1
        if input_path.exists() and tree_fingerprint(input_path) != before:
            print(f"FAIL: the input changed during interpretation; ship policy is {SHIP_POLICY}. Discard this run.")
            return 1
        state.log("assessment.json", assessment.model_dump_json(indent=2))
        state.log("report.md", report_md + "\n" + render_assessment(assessment))
        state.step("assess", risk=assessment.risk_rating, actions=len(assessment.prioritized_actions), approval_forced=forced)
        print(f"assessment: risk {assessment.risk_rating}, {len(assessment.prioritized_actions)} action(s), "
              f"{forced} forced to require human approval")

    blocked = [f for r in reports for f in r.blocking(fail_on)] if fail_on else []
    if blocked:
        print(f"GATE: {len(blocked)} finding(s) at or above {fail_on}. Report: {report_path}")
        return 2
    print(f"DONE: report only, nothing was applied ({SHIP_POLICY}). Report: {report_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run a domain pack: analyze, interpret, report. Never applies changes.")
    ap.add_argument("--pack", required=True, choices=sorted(PACK_TOOLS))
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--tool")
    ap.add_argument("--opt", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--no-agent", action="store_true", help="deterministic analysis only")
    ap.add_argument("--fail-on", choices=sorted(SEVERITY_ORDER, key=SEVERITY_ORDER.__getitem__))
    a = ap.parse_args(argv)
    runner = MockRunner({"architect": mock_assessment}) if os.getenv("PAC_RUNNER") == "mock" else None
    return run_workflow(a.pack, a.input.resolve(), a.tool, parse_opts(a.opt), a.model, not a.no_agent, a.fail_on, runner)


if __name__ == "__main__":
    raise SystemExit(main())
