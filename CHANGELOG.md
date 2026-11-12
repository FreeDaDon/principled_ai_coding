# Changelog

## v0.2.0 - 2026-11-12

### Security
- Execution commands (the code an agent wrote) run without `ANTHROPIC_API_KEY` and with a throwaway `HOME`; `sandbox: bwrap` also cuts the network and hides the home directory
- Every agent call passes `--restricted` and a `--settings` deny policy, so the policy holds on scratch copies without `.claude/`
- A live runner refuses to start next to a reference solution (Director, spec runner, architect/editor)
- Commit gate enforced: `.githooks/pre-commit` and the `commit_gate.py` Claude Code hook; `--no-verify` is denied
- Narrowed the `uv run` allowlist so it no longer bypasses the Bash deny list

### Added
- `adws/adw_eval.py` and the manual `live-eval` workflow: pass rate, iterations and cost per example, logged to `evals/results.jsonl`
- MIT `LICENSE`

### Changed
- The judge returns a verdict per objective with evidence; success is computed in code as every objective met
- Stagnation stops on any repeated failure, so A-B-A oscillation no longer runs to `max_iterations`
- Edit-bounds snapshots keep clean git-tracked files as blob ids and skip re-reading files whose stat is unchanged
- `/spec` lists all eight templates

### Commits since the start
- Make the architect/editor mock dry run apply the reference solution (#10)
- Stop the prompt-cache key from masking plain 8-digit numbers (#9)
- Make adw_doctor report a hanging or silent tool instead of crashing (#8)
- Fix spec_to_tests on string defaults, multi-line defs and hyphenated modules (#7)
- Track large files and symlinks in the edit-bounds snapshot (#6)
- Check context paths before any agent runs; treat a corrupt cache as a miss (#5)
- Fail closed in the mcp_gov release gate: no silent skips or crashes (#4)
- Group release changelog with Jev, falling back to the writer agent (#3)
- Add Jev typed-decision client (mock by default, advisory only) (#2)
- Add CI workflow running the scripts/check.sh gate (#1)
- Add mcp_gov and gcp_sre domain packs
- Add Principled AI Coding playbook and toolkit
