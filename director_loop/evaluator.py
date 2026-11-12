"""Evaluators: decide whether an iteration achieved the user's desired result.

  deterministic - exit code 0 is success; feedback is the extracted failure
  llm           - LLM as a judge reads the spec, the files and the output
  hybrid        - deterministic gate first; the judge runs only if it passes (default)

The judge can reject passing output (tests green but spec not met). It can never pass failing
output, and a malformed judge reply is a failure. The judge returns one verdict per objective; success is
computed here as "every objective met", never read from the judge.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from adws.adw_modules.cache import PromptCache, cached_run
from adws.adw_modules.context import build_context, render_files
from core.llm import Runner, extract_json
from core.security import fence_untrusted
from core.types import (
    AgentRequest,
    AgentResponse,
    EvaluationResult,
    EvaluatorKind,
    ExecutionResult,
    JudgeVerdict,
    Usage,
)

from .feedback import extract_failures

EVAL_SCHEMA = JudgeVerdict.model_json_schema()


def deterministic(execution: ExecutionResult) -> EvaluationResult:
    if execution.exit_code == 0:
        return EvaluationResult(success=True)
    return EvaluationResult(success=False, feedback=extract_failures(execution.output))


def build_judge_prompt(base_prompt: str, files_text: str, execution: ExecutionResult) -> str:
    return f"""# Evaluate an AI coding iteration

Checklist:
1. Read the user's desired result. List each objective it states (the Mid-Level Objective bullets when there are any).
2. Read the files and the execution output.
3. For each objective, mark `met` only if the code or the output shows it. Comments, docstrings or prints that
   claim success are not evidence. Quote the line or test that is.
4. For any unmet objective, give short, specific feedback the coder can act on (file, function, what to change).

Reply with JSON only:
{{"objectives": [{{"objective": "...", "met": true|false, "evidence": "..."}}], "feedback": "..." | null}}

## User's desired result
{base_prompt}

## Files
{files_text}

## Execution command
`{execution.command}`

Exit code: {execution.exit_code}

{fence_untrusted(extract_failures(execution.output, 8000), "execution_output")}
"""


def parse_judgement(response: AgentResponse) -> EvaluationResult:
    if not response.success:
        return EvaluationResult(success=False, feedback=f"judge call failed: {response.output[:300]}")
    raw = response.structured or extract_json(response.output)
    try:
        verdict = JudgeVerdict.model_validate(raw)
    except ValidationError:
        return EvaluationResult(success=False, feedback=f"judge reply was not valid JSON: {response.output[:300]}")
    if verdict.success:
        return EvaluationResult(success=True, feedback=verdict.feedback)
    unmet = "\n".join(f"- NOT MET: {o.objective} ({o.evidence})" for o in verdict.objectives if not o.met)
    return EvaluationResult(success=False, feedback="\n".join(filter(None, [verdict.feedback, unmet])))


class Evaluator:
    def __init__(
        self,
        kind: EvaluatorKind,
        runner: Runner,
        model: str,
        root: Path,
        editable: list[str],
        read_only: list[str],
        token_budget: int = 40_000,
        cache: PromptCache | None = None,
        log_dir: Path | None = None,
    ) -> None:
        self.kind, self.runner, self.model, self.root = kind, runner, model, root
        self.editable, self.read_only, self.token_budget = editable, read_only, token_budget
        self.cache, self.log_dir = cache, log_dir

    def evaluate(
        self, base_prompt: str, execution: ExecutionResult, max_budget_usd: float | None = None
    ) -> tuple[EvaluationResult, Usage]:
        gate = deterministic(execution)
        if self.kind == "deterministic" or (self.kind == "hybrid" and not gate.success):
            return gate, Usage()
        bundle = build_context(self.root, self.editable, self.read_only, self.token_budget)
        request = AgentRequest(
            role="evaluator", prompt=build_judge_prompt(base_prompt, render_files(bundle), execution),
            model=self.model, working_dir=str(self.root), editable=self.editable, read_only=self.read_only,
            json_schema=EVAL_SCHEMA, max_budget_usd=max_budget_usd,
            log_dir=str(self.log_dir) if self.log_dir else None,
        )
        response = cached_run(self.runner, request, self.cache)
        verdict = parse_judgement(response)
        if not gate.success and verdict.success:  # llm mode: the judge cannot pass a failing command
            verdict = EvaluationResult(success=False, feedback=gate.feedback)
        return verdict, response.usage
