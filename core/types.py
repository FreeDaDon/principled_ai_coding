"""Type-Driven Design: every interface in the toolkit is declared here before any logic uses it.

Model output is untrusted: anything an LLM returns is parsed into one of these models, and a
parse failure is a failed attempt, never a pass.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ModelName = Literal["haiku", "sonnet", "opus"]
TaskClass = Literal["mechanical", "standard", "heavy"]
Role = Literal["coder", "architect", "editor", "evaluator", "writer"]
EvaluatorKind = Literal["deterministic", "llm", "hybrid"]
PromptLevel = Literal["too_high", "balanced", "too_low"]
StopReason = Literal["passed", "max_iterations", "stagnation", "budget", "agent_error"]


# ----------------------------------------------------------------------------- specs (L3/L5)
class ContextFile(BaseModel):
    path: str
    read_only: bool = False


class LowLevelTask(BaseModel):
    title: str
    prompt: str


class Spec(BaseModel):
    """The 5-layer spec prompt: objective high to low, then the exact files and ordered tasks."""

    title: str
    high_level_objective: str = ""
    mid_level_objectives: list[str] = Field(default_factory=list)
    implementation_notes: list[str] = Field(default_factory=list)
    beginning_context: list[ContextFile] = Field(default_factory=list)
    ending_context: list[ContextFile] = Field(default_factory=list)
    low_level_tasks: list[LowLevelTask] = Field(default_factory=list)

    @property
    def editable_files(self) -> list[str]:
        return [c.path for c in self.ending_context if not c.read_only]

    @property
    def read_only_files(self) -> list[str]:
        seen = {c.path for c in self.ending_context if not c.read_only}
        out: list[str] = []
        for c in self.beginning_context + self.ending_context:
            if c.read_only and c.path not in seen and c.path not in out:
                out.append(c.path)
        return out


class SpecIssue(BaseModel):
    level: Literal["error", "warning"]
    layer: str
    message: str


class SpecReport(BaseModel):
    path: str
    issues: list[SpecIssue] = Field(default_factory=list)
    keyword_density: float = 0.0

    @property
    def ok(self) -> bool:
        return not any(i.level == "error" for i in self.issues)


# ----------------------------------------------------------------------------- prompts (L3/L4)
class PromptScore(BaseModel):
    words: int
    idk_count: int
    action_keywords: list[str]
    keyword_density: float
    vague_words: list[str]
    has_location: bool
    level: PromptLevel


class Pitfall(BaseModel):
    kind: Literal[
        "missing_context", "excessive_context", "prompt_too_high", "prompt_too_low", "weak_model", "model_overkill"
    ]
    severity: Literal["low", "medium", "high"]
    message: str
    fix: str


# ----------------------------------------------------------------------------- agent calls
class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, other: Usage) -> Usage:
        return Usage(**{k: getattr(self, k) + getattr(other, k) for k in Usage.model_fields})


class AgentRequest(BaseModel):
    role: Role
    prompt: str
    model: str = "sonnet"
    working_dir: str
    editable: list[str] = Field(default_factory=list)
    read_only: list[str] = Field(default_factory=list)
    json_schema: dict | None = None
    timeout_s: int = 900
    max_budget_usd: float | None = None
    log_dir: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class AgentResponse(BaseModel):
    output: str
    success: bool
    model: str = ""
    usage: Usage = Field(default_factory=Usage)
    structured: dict | None = None
    cached: bool = False


# ----------------------------------------------------------------------------- director (L6/L7)
class DirectorConfig(BaseModel):
    """Course field names (director_*.yaml), plus budget and the mock hook used for offline runs."""

    model_config = ConfigDict(extra="forbid")

    prompt: str
    coder_model: str = "sonnet"
    evaluator_model: str = "haiku"
    evaluator: EvaluatorKind = "hybrid"
    max_iterations: int = Field(default=5, ge=1, le=20)
    execution_command: str
    context_editable: list[str] = Field(min_length=1)
    context_read_only: list[str] = Field(default_factory=list)
    budget_usd: float = Field(default=2.0, ge=0)
    context_token_budget: int = Field(default=40_000, ge=1_000)
    execution_timeout_s: int = Field(default=300, ge=1)
    mock_solution: str | None = None


class ExecutionResult(BaseModel):
    command: str
    exit_code: int
    output: str
    duration_s: float = 0.0


class EvaluationResult(BaseModel):
    success: bool
    feedback: str | None = None


class IterationRecord(BaseModel):
    iteration: int
    coder_output: str
    out_of_bounds: list[str] = Field(default_factory=list)
    execution: ExecutionResult
    evaluation: EvaluationResult
    usage: Usage = Field(default_factory=Usage)


class DirectorResult(BaseModel):
    success: bool
    iterations: int
    stop_reason: StopReason
    rolled_back: bool = False
    run_dir: str = ""
    history: list[IterationRecord] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
