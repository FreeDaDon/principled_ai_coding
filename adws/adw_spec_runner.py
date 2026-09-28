#!/usr/bin/env -S uv run
"""ADW: run a 5-layer spec prompt end to end (Lessons 3 and 5: plan equals prompt).

  validate spec -> pitfall check -> editor applies the spec (whole or --per-task) inside the spec's
  context bounds -> run the validation command -> on failure, hand off to the Director loop

Usage:
  uv run adws/adw_spec_runner.py examples/software/spec.md --validate-cmd "{python} -m pytest tests -q"
  uv run adws/adw_spec_runner.py SPEC --per-task --director-on-fail 3
  uv run adws/adw_spec_runner.py SPEC --dry-run          # print the prompts, call nothing
"""

from __future__ import annotations

import argparse
from pathlib import Path

from adws.adw_modules.state import RunState
from core import pitfalls
from core.boundaries import guarded_run
from core.execution import run_command
from core.llm import Runner, get_runner
from core.types import AgentRequest, DirectorConfig, Spec
from director_loop.engine import Director
from specs.spec_validator import parse_spec, validate


def build_prompts(spec: Spec, spec_text: str, per_task: bool) -> list[str]:
    bounds = (
        "\n\n## Context bounds (enforced in code)\n"
        f"- Editable: {', '.join(spec.editable_files)}\n"
        f"- Read-only: {', '.join(spec.read_only_files) or '(none)'}\n"
        "Make the edits directly with your tools. Do not run commands. Reply with a 1-3 line summary."
    )
    if not per_task:
        return [spec_text + bounds]
    header = f"# {spec.title}\n\n## High-Level Objective\n{spec.high_level_objective}\n\n## Implementation Notes\n"
    header += "\n".join(f"- {n}" for n in spec.implementation_notes)
    n = len(spec.low_level_tasks)
    return [f"{header}\n\n## Task {i}/{n}: {t.title}\n```\n{t.prompt}\n```{bounds}"
            for i, t in enumerate(spec.low_level_tasks, 1)]


def run_spec(
    spec_path: Path,
    working_dir: Path,
    model: str = "sonnet",
    per_task: bool = False,
    validate_cmd: str | None = None,
    director_on_fail: int = 0,
    mock_solution: str | None = None,
    runner: Runner | None = None,
    dry_run: bool = False,
) -> int:
    text = spec_path.read_text()
    spec = parse_spec(text)
    report = validate(spec, str(spec_path))
    for issue in report.issues:
        print(f"  {issue.level:<7} {issue.layer}: {issue.message}")
    if not report.ok:
        print(f"FAIL: spec has errors, nothing was run ({spec_path})")
        return 2
    for p in pitfalls.check(text, spec.editable_files, spec.read_only_files, model, "heavy", base_dir=working_dir):
        print(f"  pitfall {p.kind} ({p.severity}): {p.message} -> {p.fix}")

    prompts = build_prompts(spec, text, per_task)
    if dry_run:
        for i, prompt in enumerate(prompts, 1):
            print(f"\n----- prompt {i}/{len(prompts)} -----\n{prompt}")
        return 0

    runner = runner or get_runner()
    state = RunState("spec_runner")
    state.update(spec=str(spec_path), working_dir=str(working_dir), per_task=per_task)
    metadata = {"mock_solution": mock_solution} if mock_solution else {}
    for i, prompt in enumerate(prompts, 1):
        state.log(f"editor_prompt_{i}.md", prompt)
        request = AgentRequest(role="editor", prompt=prompt, model=model, working_dir=str(working_dir),
                               editable=spec.editable_files, read_only=spec.read_only_files,
                               log_dir=str(state.dir), metadata=metadata)
        response, reverted = guarded_run(runner, request)
        state.step(f"editor_{i}", success=response.success, reverted=reverted, cost_usd=response.usage.cost_usd)
        if not response.success:
            print(f"FAIL: editor call {i} failed: {response.output[:300]}")
            return 1
        if reverted:
            print(f"  reverted out-of-bounds edits: {reverted}")

    if not validate_cmd:
        print(f"DONE: applied {len(prompts)} prompt(s); no --validate-cmd given, so nothing was verified. Run: {state.dir}")
        return 0
    execution = run_command(validate_cmd, working_dir)
    state.step("validate", exit_code=execution.exit_code)
    if execution.exit_code == 0:
        print(f"PASSED: spec applied and `{validate_cmd}` is green. Run: {state.dir}")
        return 0
    if director_on_fail <= 0:
        print(f"FAIL: `{validate_cmd}` exit {execution.exit_code}. Re-run with --director-on-fail N to self-heal.")
        print(execution.output[-2000:])
        return 1

    print(f"validation failed (exit {execution.exit_code}); handing off to the Director for {director_on_fail} iteration(s)")
    config = DirectorConfig(prompt=text, coder_model=model, execution_command=validate_cmd,
                            context_editable=spec.editable_files, context_read_only=spec.read_only_files,
                            max_iterations=director_on_fail, mock_solution=mock_solution)
    result = Director(config, working_dir, runner=runner).direct()
    print(f"{'PASSED' if result.success else 'FAIL'}: director {result.stop_reason} after {result.iterations} "
          f"iteration(s); log {result.run_dir}/director_log.md")
    return 0 if result.success else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run a 5-layer spec prompt.")
    ap.add_argument("spec", type=Path)
    ap.add_argument("--working-dir", type=Path, help="default: the spec's directory")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--per-task", action="store_true", help="one editor call per Low-Level Task")
    ap.add_argument("--validate-cmd")
    ap.add_argument("--director-on-fail", type=int, default=0, metavar="N")
    ap.add_argument("--mock-solution", help="reference solution dir (PAC_RUNNER=mock only)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    return run_spec(a.spec, (a.working_dir or a.spec.parent).resolve(), a.model, a.per_task, a.validate_cmd,
                    a.director_on_fail, a.mock_solution, dry_run=a.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
