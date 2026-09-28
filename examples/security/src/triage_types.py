"""Types first: auth events, detection rules and alerts (read-only context)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Outcome = Literal["failure", "success", "invalid_user"]


class AuthEvent(BaseModel):
    timestamp: datetime
    host: str
    process: str
    outcome: Outcome
    user: str
    source_ip: str


class DetectionRule(BaseModel):
    id: str
    title: str
    outcome: Outcome
    threshold: int = Field(ge=1)
    window_seconds: int = Field(ge=1)
    group_by: Literal["source_ip", "user"] = "source_ip"


class Alert(BaseModel):
    rule_id: str
    key: str                 # value of the group_by field
    count: int
    first_seen: datetime
    last_seen: datetime
    users: list[str]
