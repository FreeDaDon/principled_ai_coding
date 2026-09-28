"""sshd auth log triage: sanitize, parse, detect."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import yaml
from triage_types import Alert, AuthEvent, DetectionRule

MAX_LINE = 512
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_SECRET_KV = re.compile(r"(?i)\b(password|passwd|token|secret|api_key)=\S+")
_AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_HEADER = re.compile(r"^(\w{3})\s+(\d{1,2}) (\d{2}:\d{2}:\d{2}) (\S+) ([\w-]+)(?:\[\d+\])?: (.*)$")
_FAILED = re.compile(r"^Failed \S+ for (?:invalid user )?(\S+) from (\S+) port \d+")
_ACCEPTED = re.compile(r"^Accepted \S+ for (\S+) from (\S+) port \d+")
_INVALID = re.compile(r"^Invalid user (\S+) from (\S+)")


def sanitize(line: str) -> str:
    """Strip ANSI escapes and control characters, redact secrets, cap length. Logs are untrusted."""
    line = _ANSI.sub("", line)
    line = "".join(" " if ch == "\t" else ch for ch in line if ch == "\t" or not unicodedata.category(ch).startswith("C"))
    line = _SECRET_KV.sub(lambda m: f"{m.group(1)}=[REDACTED]", line)
    line = _AWS_KEY.sub("[REDACTED_AWS_KEY]", line)
    return line[:MAX_LINE]


def parse_line(line: str, year: int) -> AuthEvent | None:
    """Parse one sanitized sshd line into an AuthEvent; None for lines that are not auth outcomes."""
    m = _HEADER.match(sanitize(line).strip())
    if not m:
        return None
    mon, day, clock, host, process, msg = m.groups()
    ts = datetime.strptime(f"{year} {mon} {int(day):02d} {clock}", "%Y %b %d %H:%M:%S")
    for pattern, outcome in ((_FAILED, "failure"), (_ACCEPTED, "success"), (_INVALID, "invalid_user")):
        hit = pattern.match(msg)
        if hit:
            return AuthEvent(timestamp=ts, host=host, process=process, outcome=outcome,  # type: ignore[arg-type]
                             user=hit.group(1), source_ip=hit.group(2))
    return None


def load_rule(path: Path) -> DetectionRule:
    """Load a YAML detection rule into its typed model."""
    return DetectionRule.model_validate(yaml.safe_load(Path(path).read_text()))


def evaluate_rule(rule: DetectionRule, events: list[AuthEvent]) -> list[Alert]:
    """Non-overlapping sliding windows per group; alert when a window holds >= threshold events."""
    groups: dict[str, list[AuthEvent]] = defaultdict(list)
    for e in events:
        if e.outcome == rule.outcome:
            groups[getattr(e, rule.group_by)].append(e)
    alerts: list[Alert] = []
    for key, evs in groups.items():
        evs.sort(key=lambda e: e.timestamp)
        i = 0
        while i < len(evs):
            j = i
            while j + 1 < len(evs) and (evs[j + 1].timestamp - evs[i].timestamp).total_seconds() <= rule.window_seconds:
                j += 1
            if j - i + 1 >= rule.threshold:
                burst = evs[i: j + 1]
                alerts.append(Alert(rule_id=rule.id, key=key, count=len(burst), first_seen=burst[0].timestamp,
                                    last_seen=burst[-1].timestamp, users=sorted({e.user for e in burst})))
                i = j + 1
            else:
                i += 1
    return sorted(alerts, key=lambda a: (a.first_seen, a.key))
