"""The Closed-Loop Director: let the code write itself.

    for i in range(max_iterations):
        prompt     = create_new_ai_coding_prompt(i, base_prompt, execution, evaluation)
        ai_code(prompt)                 # Claude edits context_editable only (enforced)
        execution  = execute()          # execution_command, e.g. pytest
        evaluation = evaluate(execution)
        if evaluation.success: break    # else: feedback flows into the next prompt

Stops on success, max_iterations, stagnation (same failure twice), budget, or agent error.
On failure the editable files are rolled back to their pre-loop state.

CLI:  uv run python -m director_loop.engine examples/software/director.yaml
      PAC_RUNNER=mock uv run python -m director_loop.engine examples/software/director.yaml   # $0 dry run
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import yaml

from adws.adw_modules import git_ops
from adws.adw_modules.cache import PromptCache
from adws.adw_modules.router import Budget, downgrade
from adws.adw_modules.state import RunState
from core.boundaries import EditableCheckpoint, check_bounds, guarded_run
from core.execution import run_command
from core.llm import Runner, get_runner
from core.security import fence_untrusted, resolve_inside
from core.types import (
    AgentRequest,
    AgentResponse,
    DirectorConfig,
    DirectorResult,
    EvaluationResult,
    ExecutionResult,
    IterationRecord,
    StopReason,
    Usage,
)

from .evaluator import Evaluator
from .feedback import extract_failures, failure_signature


def load_config(path: Path) -> DirectorConfig:
    return DirectorConfig.model_validate(yaml.safe_load(path.read_text()))


class Director:
    def __init__(
        self,
        config: DirectorConfig,
        base_dir: Path,
        runner: Runner | None = None,
        state: RunState | None = None,
        stop_on_stagnation: bool = True,
    ) -> None:
        self.config = config
        self.base_dir = base_dir.resolve()
        self.runner = runner or get_runner()
        self.state = state or RunState("director")
        self.stop_on_stagnation = stop_on_stagnation
        self.budget = Budget(config.budget_usd)
        check_bounds(self.base_dir, config.context_editable + config.context_read_only)
        self.evaluator = Evaluator(
            config.evaluator, self.runner, config.evaluator_model, self.base_dir,
            config.context_editable, config.context_read_only, config.context_token_budget,
            cache=PromptCache(self.state.dir.parent.parent / "cache"), log_dir=self.state.dir,
        )
        self._bounds_note = ""

    @classmethod
    def from_file(cls, path: Path, runner: Runner | None = None) -> Director:
        return cls(load_config(path), path.parent, runner)

    # ------------------------------------------------------------------ stage 0: the spec
    def base_prompt(self) -> str:
        """`prompt` is inline text, or a path (relative to the config) to a spec .md."""
        p = self.config.prompt.strip()
        if "\n" not in p and p.endswith(".md"):
            return resolve_inside(self.base_dir, p).read_text()
        return p

    def _bounds(self) -> str:
        ro = ", ".join(self.config.context_read_only) or "(none)"
        return (
            "## Context bounds (enforced in code)\n"
            f"- Editable (the ONLY files you may create or change): {', '.join(self.config.context_editable)}\n"
            f"- Read-only reference (read, never edit): {ro}\n"
            "- Edits to any other file are reverted automatically.\n\n"
            "Make the edits directly with your tools. Do not run commands. "
            "Reply with a 1-3 line summary of what you changed."
        )

    # ------------------------------------------------------------------ stage 1: prompt generation
    def create_new_ai_coding_prompt(
        self, iteration: int, base_prompt: str, execution: ExecutionResult | None, evaluation: EvaluationResult | None
    ) -> str:
        if iteration == 0 or execution is None or evaluation is None:
            return f"{base_prompt}\n\n{self._bounds()}"
        left = self.config.max_iterations - iteration
        failures = extract_failures(execution.output)
        feedback = evaluation.feedback or "(no feedback)"
        if feedback == failures:  # deterministic gate: the feedback IS the output above; don't pay for it twice
            feedback = "The execution command failed; fix the failures shown above."
        feedback += self._bounds_note
        return f"""# Generate the next iteration of code to achieve the user's desired result based on their original instructions and the feedback from the previous attempt.

## This is attempt {iteration + 1}. You have {left} attempt(s) remaining, including this one.

## The user's original instructions
{base_prompt}

## Output of the previous attempt (`{execution.command}`, exit code {execution.exit_code})
{fence_untrusted(failures, "previous_output")}

## Feedback on the previous attempt
{feedback}

{self._bounds()}
"""

    # ------------------------------------------------------------------ stage 2: AI code edit
    def ai_code(self, prompt: str) -> tuple[AgentResponse, list[str]]:
        request = AgentRequest(
            role="coder", prompt=prompt, model=downgrade(self.config.coder_model, self.budget),
            working_dir=str(self.base_dir), editable=self.config.context_editable,
            read_only=self.config.context_read_only, max_budget_usd=self.budget.remaining,
            log_dir=str(self.state.dir),
            metadata={"mock_solution": self.config.mock_solution} if self.config.mock_solution else {},
        )
        response, bad = guarded_run(self.runner, request)
        self._bounds_note = (
            f"\n\nYour edits to {bad} were REVERTED: they are outside the editable context." if bad else ""
        )
        return response, bad

    # ------------------------------------------------------------------ stage 3: execution command
    def execute(self) -> ExecutionResult:
        return run_command(self.config.execution_command, self.base_dir, self.config.execution_timeout_s)

    # ------------------------------------------------------------------ stage 4: evaluator
    def evaluate(self, base_prompt: str, execution: ExecutionResult) -> tuple[EvaluationResult, Usage]:
        return self.evaluator.evaluate(base_prompt, execution, self.budget.remaining)

    # ------------------------------------------------------------------ stage 5: the loop
    def direct(self, keep_on_fail: bool = False) -> DirectorResult:
        cfg = self.config
        checkpoint = EditableCheckpoint(self.base_dir, cfg.context_editable)
        base = self.base_prompt()
        history: list[IterationRecord] = []
        execution: ExecutionResult | None = None
        evaluation: EvaluationResult | None = None
        last_sig: str | None = None
        stop: StopReason = "max_iterations"
        self.state.update(config=cfg.model_dump(), base_dir=str(self.base_dir))

        for i in range(cfg.max_iterations):
            if self.budget.exceeded:
                stop = "budget"
                break
            prompt = self.create_new_ai_coding_prompt(i, base, execution, evaluation)
            self.state.log(f"iter{i}_prompt.md", prompt)
            response, bad = self.ai_code(prompt)
            self.budget.add(response.usage)
            if not response.success:
                self._log(f"iteration {i}: coder failed: {response.output[:300]}")
                stop = "agent_error"
                break
            execution = self.execute()
            evaluation, eval_usage = self.evaluate(base, execution)
            self.budget.add(eval_usage)
            history.append(IterationRecord(
                iteration=i, coder_output=response.output, out_of_bounds=bad, execution=execution,
                evaluation=evaluation, usage=response.usage.add(eval_usage),
            ))
            self.state.log(f"iter{i}_output.txt", execution.output)
            self._log(f"iteration {i}: exit {execution.exit_code}, success={evaluation.success}"
                      + (f", reverted {bad}" if bad else ""))
            if evaluation.success:
                stop = "passed"
                break
            sig = (failure_signature(execution.output) if execution.exit_code != 0
                   else hashlib.sha256((evaluation.feedback or "").encode()).hexdigest()[:16])
            if self.stop_on_stagnation and sig == last_sig:
                stop = "stagnation"
                break
            last_sig = sig

        success = stop == "passed"
        rolled_back = False
        if not success and not keep_on_fail:
            rolled_back = bool(checkpoint.rollback())
        result = DirectorResult(
            success=success, iterations=len(history), stop_reason=stop, rolled_back=rolled_back,
            run_dir=str(self.state.dir), history=history, usage=self.budget.spent,
        )
        self.state.update(result=result.model_dump(exclude={"history"}))
        self._log(f"DONE: {stop}, iterations={len(history)}, rolled_back={rolled_back}, "
                  f"cost=${self.budget.spent.cost_usd:.4f}")
        return result

    def _log(self, line: str) -> None:
        with open(self.state.dir / "director_log.md", "a") as f:
            f.write(f"- {line}\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the closed-loop Director on a director_*.yaml config.")
    ap.add_argument("config", type=Path)
    ap.add_argument("--max-iterations", type=int)
    ap.add_argument("--keep-on-fail", action="store_true", help="don't roll back editable files on failure")
    ap.add_argument("--no-stagnation-stop", action="store_true")
    ap.add_argument("--commit", action="store_true", help="git commit the editable files on success")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    config = load_config(a.config)
    if a.max_iterations:
        config = config.model_copy(update={"max_iterations": a.max_iterations})
    director = Director(config, a.config.parent, stop_on_stagnation=not a.no_stagnation_stop)
    result = director.direct(keep_on_fail=a.keep_on_fail)

    if result.success and a.commit and git_ops.is_repo(director.base_dir):
        git_ops.commit(director.base_dir, config.context_editable, f"director: {a.config.parent.name} passed")
    if a.json:
        print(result.model_dump_json(indent=2))
    else:
        verdict = "PASSED" if result.success else "FAILED"
        print(f"{verdict} after {result.iterations} iteration(s) ({result.stop_reason}); "
              f"cost ${result.usage.cost_usd:.4f}; rolled back: {result.rolled_back}")
        print(f"log: {result.run_dir}/director_log.md")
        if not result.success and result.history:
            print("\nlast feedback:\n" + (result.history[-1].evaluation.feedback or "")[:2000])
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
