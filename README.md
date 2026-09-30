# Principled AI Coding — Playbook & Toolkit

The eight Principled AI Coding lessons as runnable code on Claude Code: information-dense prompts,
5-layer spec prompts, architect/editor chaining, AI Developer Workflows (ADWs), and the closed-loop
Director that edits, runs, judges and self-heals until the tests pass. There are worked examples for
software, DevOps, SOC and IAM.

The course teaches with Aider. Here, `claude -p` does every job Aider did: coder, architect, editor
and evaluator. A deterministic mock runner lets everything run offline for $0.

```
spec.md ──▶ spec_validator ──▶ editor (or architect ▶ editor) ──▶ execution_command
                                          ▲                              │
                                          └── feedback ◀── evaluator ◀───┘   Director loop
```

## Quickstart

```bash
uv sync
uv run adws/adw_doctor.py                     # environment + Claude auth check
scripts/check.sh                              # ruff + mypy + tests, fully offline

# Director dry run, $0: fails once, feeds the stack trace back, then passes
cp -r examples/software /tmp/sw
PAC_RUNNER=mock uv run python -m director_loop.engine /tmp/sw/director.yaml

# Real run (uses your `claude` login or ANTHROPIC_API_KEY; capped by budget_usd in the config)
uv run python -m director_loop.engine /tmp/sw/director.yaml
```

Run examples on a copy. A successful run rewrites the example's stub, which the example tests
check for (`tests/test_examples.py` asserts that the stubs fail).

## Pick the right tool

| Situation | Use | Lesson |
|---|---|---|
| Quick fix, exploring, unclear solution | interactive Claude Code + `/idk`, `/heal` | 1–4 |
| Medium or large task you can plan end to end (more than 3–5 prompts) | spec prompt: `/spec`, then `adw_spec_runner.py` | 3, 5 |
| Hard design where a planner and an executor help | `adw_architect_editor.py` | 4 (syllabus) / 5 |
| The third time you do the same kind of task ("three makes a pattern") | write an ADW | 6 (syllabus 5) |
| Unattended implementation with a test command that gives real feedback | Director loop | 7 (syllabus 6) |
| Vetting an untrusted AI connector (MCP server, skill, plugin) or triaging a GCP, Kafka or Node.js incident export | domain pack: `adw_domain_pack.py` | beyond the course |

## Layout

| Path | What it is |
|---|---|
| `core/types.py` | Type-driven design: every interface (Spec, DirectorConfig, EvaluationResult, …) as pydantic models |
| `core/idk.py` | Information-dense keywords: vocabulary, `LOCATION: ACTION DETAIL` parser, density score, prompt-level check |
| `core/pitfalls.py` | The six pitfalls (too little or too much context, prompt, model) as a linter |
| `core/llm.py` | `ClaudeRunner` (`claude -p`, least-privilege tools per role) and `MockRunner` |
| `core/packs/` | Domain packs: deterministic analyzers for MCP governance (`mcp_gov`) and GCP SRE (`gcp_sre`) that emit typed findings; registry and CLI. See [docs/packs.md](docs/packs.md) |
| `core/jev.py` | Jev typed decisions (TypeSafe System One): one schema-validated choice in place of an agent call, mock by default, advisory only |
| `core/boundaries.py` | Context bounds enforced in code: out-of-bounds edits are reverted; checkpoint rollback |
| `core/execution.py` | Deterministic command runner (argv, allowlisted env, timeout) |
| `specs/templates/` | 5-layer templates: feature, bugfix, refactor, infra_change, detection_rule, iam_policy, ai_connector_review, gcp_incident |
| `specs/spec_validator.py` | Parses and validates specs (layers, IDK-led tasks, context consistency, density) |
| `specs/spec_to_tests.py` | Spec-to-test generator: pytest contract tests from the spec's signatures (`--llm` for behavioral tests) |
| `adws/` | `adw_doctor`, `adw_spec_runner`, `adw_architect_editor`, `adw_version_release`, `adw_domain_pack` |
| `adws/adw_modules/` | run state, git helpers, context and token budget, cost router and budget, read-only prompt cache |
| `director_loop/` | `engine.py` (5-stage loop), `evaluator.py` (deterministic, llm, hybrid), `feedback.py` (stack-trace hand-off) |
| `.claude/commands/` | `/bluf` `/idk` `/spec` `/architect` `/director` `/heal`, plus the pack reviewers `/mcp_review` `/gcp_triage` |
| `.claude/settings.json` | Permission boundaries: no `.env` or credential reads, no destructive git, cloud or IAM commands |
| `examples/` | software (GovOpp opportunity scorer), devops (Terraform plan guard), security (sshd brute-force rule), iam (least-privilege policy generation and audit) |
| `docs/packs.md` | The two domain packs: every tool and rule id, commands, the agent's role, safety model, how to extend |
| `tests/fixtures/packs/` | Planted issues (fake credentials only) and a clean input per pack |
| `docs/lessons.md` | Each lesson, both numberings, and where it lives in code; Aider-to-Claude command map |

## The Director

A config uses the course's field names:

```yaml
prompt: spec.md                     # inline text or a path to a spec
coder_model: sonnet
evaluator_model: haiku
evaluator: hybrid                   # deterministic | llm | hybrid
max_iterations: 5
execution_command: "{python} -m pytest tests -q -p no:cacheprovider"
context_editable: [src/opportunity_scorer.py]
context_read_only: [src/opportunity_types.py, tests/test_opportunity_scorer.py]
budget_usd: 2.0
```

Each iteration: build the prompt (the spec on the first pass; after that, spec + extracted
failures + judge feedback + tries left) → Claude edits → any change outside `context_editable` is
reverted → run `execution_command` → evaluate.

The loop stops on **passed**, **max_iterations**, **stagnation** (the same failure twice),
**budget**, or **agent_error**. On failure the editable files are rolled back unless you pass
`--keep-on-fail`. Every prompt, output and verdict is logged under `.pac/runs/<run_id>/`.

**Hybrid evaluation** is the default. The test command must exit 0, and only then does the LLM
judge check the spec was actually met. The judge can reject green tests. It can never pass red
ones, and a malformed judge reply counts as a failure.

## Guarantees (enforced in code, covered by tests)

- **Model output is untrusted.** Judge replies are parsed into pydantic models. Paths from configs and models must resolve inside the working directory.
- **Context bounds.** The coder may change only its editable files. A coder that "fixes" failing tests by editing them has that edit reverted and is told why.
- **Least privilege per role.** Coder and editor get Read, Edit, Write, Glob and Grep with no Bash. The architect is read-only. The evaluator and writer get no tools. `--dangerously-skip-permissions` is never used.
- **Untrusted text is fenced.** Command output, logs and commit messages go into prompts inside an `<untrusted>` block, with prompt-injection markers flagged.
- **Allowlisted subprocess environment.** Agents and test commands don't inherit your shell secrets.
- **Isolated agents.** Sub-agents run with `--setting-sources project --strict-mcp-config`, so your personal `~/.claude` CLAUDE.md, hooks and MCP servers don't leak into their context. In testing this cut a trivial call from $0.023 to $0.003.
- **Budgets.** Opus is downgraded to Sonnet at 80% of `budget_usd`, and calls stop at 100%. Each call also passes `--max-budget-usd`.
- **Jev is advisory, never a gate.** A Jev answer can stand in for an agent's fixed-option judgment only above a confidence floor, and the agent path runs on low confidence or any error. Mock and live replies pass the same wire-contract check (declared options only, a distribution that sums to 1); a violation is an error, never a degraded answer. Redirects are refused so the bearer token cannot leave the endpoint.
- **Cache only what is safe to replay.** Only read-only roles (architect, judge) are cached, keyed by the normalized prompt plus the hashes of the context files.

## Beyond the course

- **Dynamic token budgeting.** `context.py` always includes editable files and adds read-only files in priority order until `context_token_budget` is reached. The rest are listed by path only.
- **Multi-model cost router.** `router.py` maps task class to haiku, sonnet or opus, and applies budget pressure.
- **Read-only prompt cache.** `cache.py` stores replies keyed by the normalized prompt and the context file hashes.
- **Spec-to-test generator.** `spec_to_tests.py` builds contract tests from a spec, giving the Director something to close the loop against.
- **Pitfall linter.** `core/pitfalls.py` runs before every spec execution.
- **Jev for fixed-option judgments.** `adw_version_release.py` sorts commit subjects into Added, Changed, Fixed and Other with one Jev choice each ([TypeSafe](https://typesafe.ai) System One, `core/jev.py`) instead of a writer agent. The bullets are the commit subjects verbatim, so the changelog can only say what the commits say. Low confidence, an error, an injection marker or more than 50 commits hands the entry to the writer agent as before. The bump, build, commit and tag never depend on Jev. No other call site qualifies: the rest either generate or edit (coder, editor, architect, spec-to-tests) or act as a gate (the Director's judge, pack `--fail-on`), and a gate stays out of Jev's reach.
- **Domain packs.** `mcp_gov` (AI connector intake: manifest, OAuth scopes, prompt injection, exfiltration) and `gcp_sre` (Terraform/IAM audit, Splunk and Kafka log triage, Node.js stack traces) are deterministic analyzers with stable rule ids. A read-only agent interprets the findings file and returns strict JSON; the workflow only ever writes a report. See [docs/packs.md](docs/packs.md).

```bash
uv run python -m core.packs.registry mcp_gov vendor/connector/ --fail-on high        # exit 2 on a high finding
PAC_RUNNER=mock uv run adws/adw_domain_pack.py --pack gcp_sre --input tests/fixtures/packs/gcp_sre
```

Candidates deliberately left out: parallel best-of-N implementations (they multiply cost; add them
only for high-value tasks), and container sandboxing per run (use your own Docker or Firecracker).
For worktree isolation, a GitHub issue-to-PR flow, and a live control plane, see the sibling
[TAC toolkit](https://github.com/FreeDaDon/tac).

## Environment variables

| Variable | Default | Effect |
|---|---|---|
| `PAC_RUNNER` | `claude` | `mock` = offline deterministic runner |
| `PAC_CACHE` | `1` | `0` disables the prompt cache |
| `PAC_PROJECT_ROOT` | repo root | where `.pac/` run state and cache live |
| `CLAUDE_CODE_PATH` | `claude` | path to the Claude Code CLI |
| `ANTHROPIC_API_KEY` | unset | optional; the `claude` login works without it |
| `JEV_BACKEND` | `mock` | `typesafe`, `openrouter`, or `live` (typesafe first) call real Jev; without the matching key, or on any other value, it stays on mock |
| `TYPESAFE_API_KEY` / `OPENROUTER_API_KEY` | unset | Jev credentials. Read in-process only, never passed to agent or test subprocesses |

## Requirements

Python 3.12 with uv, git, and the `claude` CLI. Terraform, SIEMs and cloud CLIs are not needed:
the examples work on exported artifacts (`terraform show -json`, log files, policy JSON).
