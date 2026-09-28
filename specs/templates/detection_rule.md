# Detection Rule: <rule title>
> Ingest this file. Build a detection rule and prove it in isolation against positive and negative fixtures.

## High-Level Objective
- Detect <attack behavior> in <log source> with no alerts on normal traffic.

## Mid-Level Objective
- `rules/<rule_id>.yaml` defines the rule (outcome, threshold, window_seconds, group_by).
- The positive fixture triggers exactly the expected alerts.
- The negative fixture triggers none.
- Log lines are sanitized before parsing or display.

## Implementation Notes
- Treat every log line as untrusted: strip ANSI and control characters, redact secrets.
- Rule logic is deterministic; no LLM in the detection path.
- Rules are tested in isolation: one rule, one pair of fixtures.

## Context

### Beginning context
- src/triage_types.py (read-only)
- fixtures/<positive>.log (read-only)
- fixtures/<negative>.log (read-only)

### Ending context
- src/triage_types.py (read-only)
- fixtures/<positive>.log (read-only)
- fixtures/<negative>.log (read-only)
- rules/<rule_id>.yaml
- tests/test_<rule_id>.py

## Low-Level Tasks
> Ordered from start to finish.

1. Create the rule
```
CREATE rules/<rule_id>.yaml: id, title, outcome, threshold, window_seconds, group_by
```

2. Create the isolated rule tests
```
CREATE tests/test_<rule_id>.py:
    CREATE test_<rule_id>_fires_on_positive, test_<rule_id>_silent_on_negative USE load_rule, evaluate_rule
```
