---
description: Write a 5-layer spec prompt for a task (plan equals prompt)
argument-hint: <what to build> [template: feature|bugfix|refactor|infra_change|detection_rule|iam_policy]
---
# Write a spec prompt

Task: $ARGUMENTS

1. Pick the closest template in `specs/templates/` (default: feature.md) and read it.
2. Read the files the task touches. Decide the smallest editable set; everything else the model needs is read-only.
3. Write `specs/<kebab-name>.md` with exactly these layers:
   - `## High-Level Objective`: one sentence, the outcome.
   - `## Mid-Level Objective`: testable deliverables as bullets.
   - `## Implementation Notes`: libraries, rules, edge cases, "carry out the tasks in order".
   - `## Context` with `### Beginning context` and `### Ending context`; mark references `(read-only)`.
   - `## Low-Level Tasks`: ordered, numbered; each has a title and a fenced prompt that starts with an action keyword and names a file or symbol. Types first. Later tasks reference names from earlier ones.
4. Run `uv run python -m specs.spec_validator specs/<kebab-name>.md` and fix every error and warning.
5. Reply with the spec path, the validator result, and the command to execute it:
   `uv run adws/adw_spec_runner.py specs/<kebab-name>.md --validate-cmd "<test command>" --director-on-fail 3`
