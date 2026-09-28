---
description: Rewrite a prompt with information-dense keywords (LOCATION: ACTION DETAIL)
argument-hint: <prompt to rewrite>
---
# Rewrite with IDKs

Rewrite this prompt so an AI coding assistant can execute it with no ambiguity:

$ARGUMENTS

Rules (Principled AI Coding, "Know Your IDKs"):
1. Run `uv run python -m core.idk "<original prompt>"` and read the score and suggestions.
2. Shape: `LOCATION: ACTION DETAIL`. The location is a file with its extension, a `def`/`class`, or a unique identifier.
3. Actions, in order of preference: CREATE, UPDATE, DELETE, ADD, REMOVE, MOVE, REPLACE, SAVE, MIRROR, APPEND, USE, RESOLVE, WRAP, OVERRIDE. Capitalize them.
4. Use APPEND (not ADD) when the change belongs at the end. Use MIRROR to copy an existing pattern.
5. Give full signatures with types: `CREATE def format_as_yaml(t: Transcript) -> str`.
6. Replace vague words ("data", "enhance", "improve") with the concrete change. What > how.
7. Use `:` to nest and commas to list.

Reply with: the rewritten prompt in a code block, then its `core.idk` score (re-run it), then one line on what changed.
