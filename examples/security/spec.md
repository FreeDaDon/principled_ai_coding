# SSH Auth Log Triage
> Ingest this file, carry out the Low-Level Tasks in order, and produce code that satisfies the High and Mid-Level Objectives.

## High-Level Objective
- Detect SSH brute-force attempts in sshd auth logs with a deterministic rule that is proven against positive and negative fixtures.

## Mid-Level Objective
- Sanitize every log line before parsing or display (untrusted input).
- Parse sshd lines into typed `AuthEvent` models; skip everything else.
- Load YAML detection rules into `DetectionRule`.
- Evaluate a rule with non-overlapping sliding windows per group and emit `Alert` models.
- `tests/test_log_triage.py` passes: the rule fires on `auth_positive.log` and stays silent on `auth_negative.log`.

## Implementation Notes
- sanitize: remove ANSI escapes, drop control characters (tab becomes a space), redact `password|passwd|token|secret|api_key=<value>` as `<key>=[REDACTED]` and AWS keys `AKIA...` as `[REDACTED_AWS_KEY]`, cap at 512 chars.
- Line header: `Mon DD HH:MM:SS host process[pid]: message`; the day may be space-padded. The caller supplies the year.
- Messages: `Failed <method> for [invalid user ]<user> from <ip> port N` is failure; `Accepted <method> for <user> from <ip>` is success; `Invalid user <user> from <ip>` is invalid_user.
- Windows: for each group sorted by time, extend from event i while within window_seconds of event i; alert if count >= threshold and continue after the burst; otherwise advance i by one. Sort alerts by first_seen then key; users sorted and unique.
- No LLM in the detection path. Standard library + pydantic + pyyaml.

## Context

### Beginning context
- src/triage_types.py (read-only)
- rules/ssh_bruteforce.yaml (read-only)
- tests/test_log_triage.py (read-only)
- fixtures/auth_positive.log (read-only)
- fixtures/auth_negative.log (read-only)
- src/log_triage.py

### Ending context
- src/triage_types.py (read-only)
- rules/ssh_bruteforce.yaml (read-only)
- tests/test_log_triage.py (read-only)
- fixtures/auth_positive.log (read-only)
- fixtures/auth_negative.log (read-only)
- src/log_triage.py

## Low-Level Tasks
> Ordered from start to finish.

1. Sanitize untrusted lines
```
UPDATE src/log_triage.py: UPDATE def sanitize(line: str) -> str USE the sanitize rules from Implementation Notes
```

2. Parse sshd lines
```
UPDATE src/log_triage.py:
    UPDATE def parse_line(line: str, year: int) -> AuthEvent | None: sanitize first, match header, then Failed/Accepted/Invalid user
```

3. Load and evaluate rules
```
UPDATE src/log_triage.py:
    UPDATE def load_rule(path: Path) -> DetectionRule: yaml.safe_load, DetectionRule.model_validate
    UPDATE def evaluate_rule(rule: DetectionRule, events: list[AuthEvent]) -> list[Alert] USE the window rules from Implementation Notes
```
