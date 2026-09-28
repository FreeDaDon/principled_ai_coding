"""Least-privilege IAM policy generation and privilege audit. (Stub: the Director fills this in.)"""

from __future__ import annotations

from pathlib import Path

from iam_types import AccessModel, AuditFinding, Role


def load_access_model(path: Path) -> AccessModel:
    raise NotImplementedError


def generate_policy(role: Role) -> dict:
    raise NotImplementedError


def audit_policy(policy: dict, used_actions: set[str] | None = None) -> list[AuditFinding]:
    raise NotImplementedError
