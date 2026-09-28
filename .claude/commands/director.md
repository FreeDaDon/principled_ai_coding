---
description: Run the closed-loop Director on a config until the execution command passes
argument-hint: <path/to/director.yaml> [--max-iterations N]
---
# Director

Run the closed-loop Director and report the outcome.

1. Read `$1` and check: `execution_command` gives real feedback (tests, not just a build), `context_editable` is minimal, `max_iterations` and `budget_usd` are set.
2. Dry run first at $0: `PAC_RUNNER=mock uv run python -m director_loop.engine $ARGUMENTS`
   (If the config has no `mock_solution`, the dry run proves the wiring only.)
3. Real run: `uv run python -m director_loop.engine $ARGUMENTS`
4. Report BLUF: PASSED/FAILED, iterations, stop reason, cost, and the director log path. On failure, show the last feedback and whether the files were rolled back.
