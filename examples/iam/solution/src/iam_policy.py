"""Least-privilege IAM policy generation and privilege audit."""

from __future__ import annotations

from pathlib import Path

import yaml
from iam_types import READ_PREFIXES, SEVERITY_ORDER, AccessModel, AuditFinding, Role


def load_access_model(path: Path) -> AccessModel:
    """Load the YAML access model into typed roles."""
    return AccessModel.model_validate(yaml.safe_load(Path(path).read_text()))


def _sid_base(role_name: str) -> str:
    return "".join(part.capitalize() for part in role_name.replace("_", "-").split("-") if part)


def generate_policy(role: Role) -> dict:
    """One Allow statement per Permission; sorted actions/resources; ABAC conditions merged by operator."""
    statements = []
    for i, perm in enumerate(role.permissions, 1):
        stmt: dict = {
            "Sid": f"{_sid_base(role.name)}{i}",
            "Effect": "Allow",
            "Action": sorted(f"{perm.service}:{a}" for a in perm.actions),
            "Resource": sorted(perm.resources),
        }
        if perm.conditions:
            cond: dict[str, dict] = {}
            for c in perm.conditions:
                cond.setdefault(c.operator, {})[c.key] = c.value
            stmt["Condition"] = cond
        statements.append(stmt)
    return {"Version": "2012-10-17", "Statement": statements}


def _as_list(value: str | list[str] | None) -> list[str]:
    return [value] if isinstance(value, str) else list(value or [])


def audit_policy(policy: dict, used_actions: set[str] | None = None) -> list[AuditFinding]:
    """IAM001 wildcards, IAM002 writes on '*', IAM003 unconditioned PassRole, IAM004 unused actions."""
    findings: list[AuditFinding] = []
    for idx, stmt in enumerate(policy.get("Statement", []), 1):
        if stmt.get("Effect") != "Allow":
            continue
        sid = stmt.get("Sid") or f"stmt{idx}"
        actions, resources = _as_list(stmt.get("Action")), _as_list(stmt.get("Resource"))
        for a in actions:
            if a == "*":
                findings.append(AuditFinding(rule_id="IAM001", severity="critical", sid=sid, message="Action '*' grants everything"))
            elif a.endswith(":*"):
                findings.append(AuditFinding(rule_id="IAM001", severity="high", sid=sid, message=f"service wildcard {a}"))
        concrete = [a for a in actions if a != "*" and not a.endswith(":*")]
        writes = [a for a in concrete if not a.split(":", 1)[-1].startswith(READ_PREFIXES)]
        if "*" in resources and writes:
            findings.append(AuditFinding(rule_id="IAM002", severity="medium", sid=sid,
                                         message=f"write actions on Resource '*': {sorted(writes)}"))
        if "iam:PassRole" in concrete and not stmt.get("Condition"):
            findings.append(AuditFinding(rule_id="IAM003", severity="high", sid=sid,
                                         message="iam:PassRole without a Condition"))
        if used_actions is not None:
            unused = sorted(a for a in concrete if a not in used_actions)
            if unused:
                findings.append(AuditFinding(rule_id="IAM004", severity="low", sid=sid, message=f"unused actions: {unused}"))
    return sorted(findings, key=lambda f: (SEVERITY_ORDER[f.severity], f.sid, f.rule_id))
