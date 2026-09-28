"""Policy checks over `terraform show -json` plan output. (Stub: the Director fills this in.)"""

from __future__ import annotations

from pathlib import Path

from plan_types import DEFAULT_PROTECTED, Finding


def load_plan(path: Path) -> dict:
    raise NotImplementedError


def check_plan(plan: dict, protected_types: frozenset[str] = DEFAULT_PROTECTED) -> list[Finding]:
    raise NotImplementedError


def exit_code(findings: list[Finding]) -> int:
    raise NotImplementedError
