"""Types first: the access model (RBAC roles + ABAC conditions) and audit findings (read-only context)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low"]
SEVERITY_ORDER: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}
READ_PREFIXES = ("Get", "List", "Describe", "Head")


class Condition(BaseModel):
    operator: Literal["StringEquals", "StringLike", "IpAddress", "Bool"]
    key: str                      # e.g. aws:SourceIp, aws:PrincipalTag/team
    value: str | list[str]


class Permission(BaseModel):
    service: str                  # e.g. s3
    actions: list[str] = Field(min_length=1)      # e.g. GetObject
    resources: list[str] = Field(min_length=1)    # ARNs
    conditions: list[Condition] = Field(default_factory=list)


class Role(BaseModel):
    name: str                     # kebab-case, e.g. report-reader
    permissions: list[Permission] = Field(min_length=1)


class AccessModel(BaseModel):
    roles: list[Role]


class AuditFinding(BaseModel):
    rule_id: str                  # IAM001..IAM004
    severity: Severity
    sid: str
    message: str
