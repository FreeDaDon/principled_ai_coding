# Lessons → Code

The course transcripts and the syllabus number lessons differently. Both numberings map to the
same code, so neither source is lost.

| Transcript lesson | Syllabus lesson | Principle | Where it lives |
|---|---|---|---|
| 1. Hello AI Coding World | 1. Foundations | KISS; the Big Three (context, model, prompt); Commander of Compute | `adws/adw_doctor.py`, `core/types.py`, `/bluf` |
| 2. Multi-File Editing | 2. Precision Prompting | Big Three bullseye; multi-file context | `core/boundaries.py`, `core/pitfalls.py` |
| 3. Know Your IDKs | 2. Precision Prompting | Information-dense keywords; LOCATION: ACTION DETAIL; type-driven design | `core/idk.py`, `/idk`, `core/types.py` |
| 4. How to Suck at AI Coding | 7. Error Recovery (partly) | Six pitfalls; balance, then boost | `core/pitfalls.py` |
| 5. Spec Based AI Coding | 3. Spec Prompts, 4. Architect/Editor | Plan equals prompt; 5-layer spec; architect mode | `specs/`, `adws/adw_spec_runner.py`, `adws/adw_architect_editor.py`, `/spec`, `/architect` |
| 6. Aider Has a Secret | 5. ADWs | Program your AI coding; three makes a pattern | `adws/`, `adws/adw_version_release.py` |
| 7. Let the Code Write Itself | 6. Director, 7. Self-Healing | Close the loop: prompt → edit → execute → evaluate → feedback | `director_loop/`, `/director`, `/heal` |
| 8. Principled AI Coding | 8. Orchestration | Signal over noise; synthesis of every rule | cost router, token budget, prompt cache, spec-to-tests, `README.md` |

## 1. Foundations (KISS, the Big Three)

- **Principle:** stop writing code line by line; review, curate and command compute. Get the three inputs right (context, model, prompt) before anything clever. "Eat the cost" of a strong model.
- **Code:** `adw_doctor.py` checks that uv, git, python and claude are installed and authenticated. It prints the result BLUF and never prints secret values. Every interface is a typed model in `core/types.py`.

## 2. Multi-file editing and precision prompting

- **Principle:** hit the bullseye with just enough context, the right model and the right prompt. Name the files; keep the editable set small.
- **Code:** a `context_editable` / `context_read_only` split everywhere. `core/boundaries.py` enforces it after every agent call.

## 3. Information-dense keywords (IDKs)

- **Action keywords**, in priority order: CREATE, UPDATE, DELETE, then ADD, REMOVE, MOVE, REPLACE, SAVE, MIRROR, then APPEND, USE, RESOLVE, WRAP, OVERRIDE. Capitalize them. Keep variants close to the root word: create beats build, make or write.
- **Detail keywords:** var, function, class, type, file, default, def. A file extension is what turns a word into a location. A full signature (`CREATE def format_as_str(t: TranscriptAnalysis) -> str`) lets the model infer the body.
- **Shape:** `LOCATION: ACTION DETAIL`. Use `:` to nest and commas to list. APPEND means "at the end"; ADD doesn't say where. What matters more than how.
- **Code:** `core/idk.py` (`score_prompt`, `parse_phrase`, `keyword_density`, `suggestions`) and `/idk`. The spec validator requires every Low-Level Task to start with an action keyword and name a location.

## 4. Pitfalls: balance, then boost

| Pitfall | Detected by `core/pitfalls.py` when… |
|---|---|
| Missing context | the prompt names a file that is not in context |
| Excessive context | the token estimate is over budget, or near-duplicate files (`_v2`, `_vnext`, `_old`) are in context |
| Prompt too high level | there is no concrete location, or vague words ("data", "enhance") with no action keyword |
| Prompt too low level | there are too many words per action at low keyword density |
| Weak model | haiku is used on a heavy task |
| Model overkill | opus is used on a mechanical task |

"First do it, then do it right, then make it fast": fix the balance before you boost with config
and automation.

## 5. Spec prompts and architect mode

- **The five layers:** High-Level Objective, Mid-Level Objective, Implementation Notes, Context (Beginning / Ending, with `(read-only)` markers), and Low-Level Tasks (ordered, each with a title and a fenced, IDK-led prompt). Types come first; later tasks reference names from earlier ones.
- **Architect mode:** a strong model drafts the plan and a second model applies it. Here the architect is Claude with read-only tools and the editor is Claude with edit-only tools; the plan is saved to `.pac/runs/<id>/plan.md`.
- **Code:** `specs/templates/*.md`, `specs/spec_validator.py`, `adws/adw_spec_runner.py` (whole spec or `--per-task`), `adws/adw_architect_editor.py`.

## 6. ADWs: AI Developer Workflows

- **Principle:** you can AI-code programmatically. Script the recurring patterns: "three makes a pattern".
- **Claude equivalent of `Coder.create(...).run(prompt)`:** `core.llm.ClaudeRunner().run(AgentRequest(role="coder", prompt=..., editable=[...], read_only=[...]))`, wrapped in `guarded_run` for enforced bounds.
- **Code:** `adw_version_release.py` does the semver bump in code, groups the changelog from commits, and runs `uv build`, commit and tag. The grouping is one Jev choice per commit subject (added, changed, fixed, other), with the subjects kept verbatim. It falls back to a Claude writer when any answer is under 0.7 confidence, Jev errors, a subject carries an injection marker, or there are more than 50 commits. That is the pattern for a fixed-option judgment: a typed decision first, the agent as the fallback. `adw_spec_runner.py` and `adw_architect_editor.py` are ADWs too.

## 7. The closed-loop Director and self-healing

- **Loop:** `create_new_ai_coding_prompt` → `ai_code` → `execute` → `evaluate` → feedback, up to `max_iterations`.
- **Evaluator:** returns `EvaluationResult{success, feedback}`, parsed as JSON. In `hybrid` (the default) the test exit code gates the LLM judge.
- **Stack-trace hand-off:** `director_loop/feedback.py` extracts pytest failure sections, the last traceback, or lint lines, truncated head and tail, and fenced as untrusted data.
- **Deterministic verification:** nothing counts as success unless the execution command passes. `--commit` commits only after that.
- **Rollback:** the editable files are checkpointed before the loop and restored on failure, replacing Aider's `/undo`. Stagnation detection stops a loop that isn't converging.
- **Limitation, from the course:** if your execution command gives no feedback, the pattern doesn't work. Make it represent the whole behavior (tests, not just a build).

## 8. Principled AI coding: orchestration, signal over noise

The course's recap: keep it simple; manage the Big Three; write prompts from low to high level; use
IDKs; don't go cheap on the model; don't overload context; balance, then boost; great plans make
great prompts; automate repetitive work with ADWs; close the loop with a Director; focus on signal
over noise.

The additions here for running at scale are the cost router and budgets (`router.py`), dynamic
token budgeting (`context.py`), the read-only prompt cache (`cache.py`) and the spec-to-test
generator (`spec_to_tests.py`).

## Aider → Claude command map

| Aider | Here |
|---|---|
| `/add file` | `context_editable` / Ending context (not read-only) |
| `/read-only file` | `context_read_only` / `(read-only)` marker |
| `/drop` | remove it from the config or spec |
| `/undo` | `EditableCheckpoint.rollback()` (automatic on a failed Director run) |
| `/run cmd` | `execution_command` / `--validate-cmd` |
| `/tokens` | `core.pitfalls.estimate_tokens`, `ContextBundle.tokens` |
| `/ask` | architect role (read-only tools) |
| `--architect --editor-model` | `adw_architect_editor.py --architect-model --editor-model` |
| `.aider.conf.yml` `auto-test` + `test-cmd` | Director `execution_command` |
| `Coder.create(...).run(prompt)` | `guarded_run(ClaudeRunner(), AgentRequest(role="coder", ...))` |
