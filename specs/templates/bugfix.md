# Bugfix: <bug title>
> Ingest this file, reproduce the failure with a test first, then make the smallest fix that passes it.

## High-Level Objective
- <Observed behavior> becomes <expected behavior> without changing any other behavior.

## Mid-Level Objective
- A failing regression test reproduces the bug.
- The fix makes that test pass.
- The existing test suite still passes.

## Implementation Notes
- Paste the stack trace or error output below the first task (stack-trace hand-off).
- Fix the root cause, not the symptom; no broad try/except.
- Do not edit or skip existing tests.

## Context

### Beginning context
- src/<module>.py
- tests/test_<module>.py

### Ending context
- src/<module>.py
- tests/test_<module>.py

## Low-Level Tasks
> Ordered from start to finish.

1. Reproduce the bug
```
UPDATE tests/test_<module>.py:
    APPEND def test_<bug_slug>_regression(): reproduce <input> -> assert <expected>
```

2. Resolve the root cause
```
RESOLVE <error message> IN src/<module>.py: UPDATE def <function_name> so <expected behavior>
```
