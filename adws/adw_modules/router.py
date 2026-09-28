"""Multi-model cost router and hard run budget.

Task class -> cheapest model that does it well:
  mechanical (changelog, naming, formatting)   -> haiku
  standard   (judging output, review, docs)    -> sonnet
  heavy      (architecture, implementation)    -> opus when model_set="heavy", else sonnet
At 80% of the run budget, opus is downgraded to sonnet. At 100%, calls stop.
"""

from __future__ import annotations

from typing import Literal

from core.types import ModelName, TaskClass, Usage

ModelSet = Literal["base", "heavy"]

ROUTING: dict[ModelSet, dict[TaskClass, ModelName]] = {
    "base": {"mechanical": "haiku", "standard": "sonnet", "heavy": "sonnet"},
    "heavy": {"mechanical": "haiku", "standard": "sonnet", "heavy": "opus"},
}
ROLE_CLASS: dict[str, TaskClass] = {
    "writer": "mechanical", "evaluator": "standard", "coder": "heavy", "editor": "heavy", "architect": "heavy",
}
PRESSURE_RATIO = 0.8


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    """limit_usd <= 0 means unlimited. Subscription (claude.ai login) runs report cost_usd too."""

    def __init__(self, limit_usd: float) -> None:
        self.limit_usd = limit_usd
        self.spent = Usage()

    def add(self, usage: Usage) -> None:
        self.spent = self.spent.add(usage)

    @property
    def remaining(self) -> float | None:
        return None if self.limit_usd <= 0 else max(self.limit_usd - self.spent.cost_usd, 0.0)

    @property
    def under_pressure(self) -> bool:
        return self.limit_usd > 0 and self.spent.cost_usd >= PRESSURE_RATIO * self.limit_usd

    @property
    def exceeded(self) -> bool:
        return self.limit_usd > 0 and self.spent.cost_usd >= self.limit_usd

    def check(self) -> None:
        if self.exceeded:
            raise BudgetExceeded(f"run budget ${self.limit_usd:.2f} spent (${self.spent.cost_usd:.4f})")


def route(task_class: TaskClass, model_set: ModelSet = "base", budget: Budget | None = None) -> ModelName:
    model = ROUTING[model_set][task_class]
    if budget is not None and budget.under_pressure and model == "opus":
        return "sonnet"
    return model


def route_role(role: str, model_set: ModelSet = "base", budget: Budget | None = None) -> ModelName:
    return route(ROLE_CLASS.get(role, "standard"), model_set, budget)


def downgrade(model: str, budget: Budget) -> str:
    """Apply budget pressure to an explicitly chosen model."""
    return "sonnet" if budget.under_pressure and "opus" in model else model
