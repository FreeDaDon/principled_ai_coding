# Feature: <feature name>
> Ingest this file, carry out the Low-Level Tasks in order, and produce code that satisfies the High and Mid-Level Objectives.

## High-Level Objective
- <One sentence: what exists when this is done and who it serves.>

## Mid-Level Objective
- <Concrete, testable deliverable 1.>
- <Concrete, testable deliverable 2.>
- <Tests prove each deliverable.>

## Implementation Notes
- Start with types: define every interface in `src/<module>_types.py` before logic.
- No new dependencies beyond pyproject.toml.
- Comment every public function with one line.
- Carry out the Low-Level Tasks in order.

## Context

### Beginning context
- pyproject.toml (read-only)
- src/<module>_types.py (read-only)
- src/<module>.py

### Ending context
- pyproject.toml (read-only)
- src/<module>_types.py (read-only)
- src/<module>.py
- tests/test_<module>.py

## Low-Level Tasks
> Ordered from start to finish. Each prompt: LOCATION: ACTION DETAIL.

1. Create the core function
```
UPDATE src/<module>.py:
    CREATE def <function_name>(<arg>: <InputType>) -> <OutputType>:
        <one line on the behavior and edge cases>
```

2. Create the tests
```
CREATE tests/test_<module>.py:
    CREATE test_<function_name>_happy_path, test_<function_name>_edge_cases MIRROR the Mid-Level Objective bullets
```
