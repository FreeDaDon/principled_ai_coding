# Refactor: <refactor title>
> Ingest this file and restructure code without changing behavior. The test suite is the contract.

## High-Level Objective
- Move <responsibility> out of <source file> into <target file> with identical behavior.

## Mid-Level Objective
- <target file> owns <responsibility>.
- <source file> imports from <target file>.
- All existing tests pass unchanged.

## Implementation Notes
- Behavior-preserving only: no new features, no renamed public APIs.
- Keep signatures identical; update imports at every call site.

## Context

### Beginning context
- src/<source>.py
- tests/test_<source>.py (read-only)

### Ending context
- src/<source>.py
- src/<target>.py
- tests/test_<source>.py (read-only)

## Low-Level Tasks
> Ordered from start to finish.

1. Create the new module
```
CREATE src/<target>.py:
    MOVE def <function_a>, def <function_b> FROM src/<source>.py
```

2. Update the old module
```
UPDATE src/<source>.py:
    REMOVE def <function_a>, def <function_b>
    ADD from <target> import <function_a>, <function_b>
```
