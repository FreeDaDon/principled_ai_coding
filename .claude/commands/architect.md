---
description: Architect a change - read-only analysis producing an ordered edit plan for an editor
argument-hint: <task> [editable files...]
---
# Architect

Task: $ARGUMENTS

You are the architect. Do not edit files.
1. Read the relevant code. Identify the minimal editable set and the read-only references.
2. Write an ordered plan: types and signatures first, then logic, then tests.
3. Each step is `LOCATION: ACTION DETAIL` with action keywords (CREATE, UPDATE, DELETE, ADD, REMOVE, MOVE, REPLACE, MIRROR, APPEND) and full typed signatures.
4. List risks and the validation command that proves the change works.

Reply with the plan only. To execute it automatically with a separate editor model:
`uv run adws/adw_architect_editor.py "<task>" --editable <files> --validate-cmd "<test command>"`
