#!/usr/bin/env -S uv run
"""ADW: architect / editor prompt chaining (Lesson 4 in the syllabus, architect mode in Lesson 5).

  architect (strong model, read-only tools) -> writes an ordered, IDK-dense edit plan
  editor    (fast model, edit-only tools)   -> applies exactly that plan inside the context bounds

Usage:
  uv run adws/adw_architect_editor.py "UPDATE src/app.py: ADD --json flag MIRROR --yaml" --editable src/app.py
  uv run adws/adw_architect_editor.py --spec examples/devops/spec.md --plan-only
"""

from __future__ import annotations

import argparse
from pathlib import Path

from adws.adw_modules.cache import PromptCache, cached_run
from adws.adw_modules.state import RunState
from core.boundaries import check_bounds, guarded_run
from core.execution import run_command
from core.llm import Runner, get_runner
from core.security import SecurityError
from core.types import AgentRequest
from specs.spec_validator import parse_spec


def architect_prompt(task: str, editable: list[str], read_only: list[str]) -> str:
    return f"""# Architect
Read the files, then write a precise, ordered edit plan for an editor model. Do NOT edit anything.

Rules for the plan:
- Types and signatures first, then logic, then tests.
- One step per change, written as LOCATION: ACTION DETAIL with keywords (CREATE, UPDATE, DELETE, ADD, REMOVE, MOVE, REPLACE, MIRROR, APPEND).
- Give full function signatures with types. Name every file and symbol exactly.
- Only touch the editable files.

## Task
{task}

## Editable files
{chr(10).join(f'- {p}' for p in editable)}

## Read-only reference files
{chr(10).join(f'- {p}' for p in read_only) or '- (none)'}

Reply with the plan in markdown only.
"""


def editor_prompt(task: str, plan: str, editable: list[str]) -> str:
    return f"""# Editor
Apply the architect's plan below exactly, step by step. Do not add scope. Do not run commands.
Only create or change these files: {', '.join(editable)}. Edits to any other file are reverted.
Reply with a 1-3 line summary of what you changed.

## Architect plan
{plan}

## Original task (for reference)
{task}
"""


def architect_edit(
    task: str,
    working_dir: Path,
    editable: list[str],
    read_only: list[str],
    architect_model: str = "opus",
    editor_model: str = "sonnet",
    plan_only: bool = False,
    validate_cmd: str | None = None,
    mock_solution: str | None = None,
    runner: Runner | None = None,
) -> int:
    try:
        check_bounds(working_dir, editable + read_only)
    except SecurityError as exc:
        print(f"FAIL: {exc}; nothing was run")
        return 2
    runner = runner or get_runner()
    state = RunState("architect_editor")
    arch = AgentRequest(role="architect", prompt=architect_prompt(task, editable, read_only), model=architect_model,
                        working_dir=str(working_dir), editable=editable, read_only=read_only, log_dir=str(state.dir))
    plan_resp = cached_run(runner, arch, PromptCache())
    state.step("architect", success=plan_resp.success, cached=plan_resp.cached, cost_usd=plan_resp.usage.cost_usd)
    if not plan_resp.success:
        print(f"FAIL: architect call failed: {plan_resp.output[:300]}")
        return 1
    plan_path = state.log("plan.md", plan_resp.output)
    if plan_only:
        print(plan_resp.output)
        print(f"\nPLAN ONLY: saved to {plan_path}")
        return 0

    edit = AgentRequest(role="editor", prompt=editor_prompt(task, plan_resp.output, editable), model=editor_model,
                        working_dir=str(working_dir), editable=editable, read_only=read_only, log_dir=str(state.dir),
                        metadata={"mock_solution": mock_solution} if mock_solution else {})
    edit_resp, reverted = guarded_run(runner, edit)
    state.step("editor", success=edit_resp.success, reverted=reverted, cost_usd=edit_resp.usage.cost_usd)
    if not edit_resp.success:
        print(f"FAIL: editor call failed: {edit_resp.output[:300]}")
        return 1
    if reverted:
        print(f"  reverted out-of-bounds edits: {reverted}")
    cost = plan_resp.usage.cost_usd + edit_resp.usage.cost_usd
    if validate_cmd:
        result = run_command(validate_cmd, working_dir)
        state.step("validate", exit_code=result.exit_code)
        if result.exit_code != 0:
            print(f"FAIL: plan applied but `{validate_cmd}` exit {result.exit_code} (cost ${cost:.4f}). Plan: {plan_path}")
            print(result.output[-2000:])
            return 1
    print(f"DONE: plan applied{' and validated' if validate_cmd else ''} (cost ${cost:.4f}). Plan: {plan_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Architect plans, editor applies.")
    ap.add_argument("task", nargs="?", help="the task prompt (or use --spec)")
    ap.add_argument("--spec", type=Path, help="use a 5-layer spec as the task and its context bounds")
    ap.add_argument("--editable", nargs="*", default=None)
    ap.add_argument("--read-only", nargs="*", default=None)
    ap.add_argument("--working-dir", type=Path)
    ap.add_argument("--architect-model", default="opus")
    ap.add_argument("--editor-model", default="sonnet")
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--validate-cmd")
    ap.add_argument("--mock-solution", help="reference solution dir (PAC_RUNNER=mock only)")
    a = ap.parse_args(argv)

    if a.spec:
        spec = parse_spec(a.spec.read_text())
        task = a.spec.read_text()
        editable = a.editable if a.editable is not None else spec.editable_files
        read_only = a.read_only if a.read_only is not None else spec.read_only_files
        working_dir = a.working_dir or a.spec.parent
    elif a.task and a.editable:
        task, editable, read_only, working_dir = a.task, a.editable, a.read_only or [], a.working_dir or Path.cwd()
    else:
        ap.error("give a task with --editable, or --spec")
    return architect_edit(task, working_dir.resolve(), editable, read_only, a.architect_model, a.editor_model,
                          a.plan_only, a.validate_cmd, a.mock_solution)


if __name__ == "__main__":
    raise SystemExit(main())
