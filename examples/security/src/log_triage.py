"""sshd auth log triage: sanitize, parse, detect. (Stub: the Director fills this in.)"""

from __future__ import annotations

from pathlib import Path

from triage_types import Alert, AuthEvent, DetectionRule


def sanitize(line: str) -> str:
    raise NotImplementedError


def parse_line(line: str, year: int) -> AuthEvent | None:
    raise NotImplementedError


def load_rule(path: Path) -> DetectionRule:
    raise NotImplementedError


def evaluate_rule(rule: DetectionRule, events: list[AuthEvent]) -> list[Alert]:
    raise NotImplementedError
