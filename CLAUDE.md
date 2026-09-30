# Principled AI Coding toolkit

- Gate before every commit: `scripts/check.sh` (ruff, mypy, pytest). The tests are offline (`PAC_RUNNER=mock`); keep them that way.
- Types first: new interfaces go in `core/types.py` as pydantic models before any logic uses them.
- Prompts and specs use IDKs: `LOCATION: ACTION DETAIL`, capitalized action keywords. Validate specs with `uv run python -m specs.spec_validator <spec>`.
- Model output is untrusted: parse it into a model; malformed = failure. Untrusted text goes into prompts through `core.security.fence_untrusted`.
- Editing agents run through `core.boundaries.guarded_run`. Never add Bash to the coder/editor tools, and never use `--dangerously-skip-permissions`.
- Examples: `src/` holds stubs (they must fail their tests), `solution/src/` the reference implementation. Run the Director on a copy, not in place.
- Import layering: `core` depends on nothing in the repo; `adws/adw_modules` depends on `core`; `director_loop` and the ADW scripts depend on both.
- Jev (`core/jev.py`) is advisory only: a typed choice may replace a full agent call for a fixed-option judgment, confidence-gated, with the agent path as the fallback on low confidence or any `JevError`. Never wire it into a gate (the Director's evaluator, a pack's `--fail-on`, a security check, or any decision to release, commit or merge). `JEV_BACKEND` defaults to `mock`; tests force it. The Jev keys stay out of `SAFE_ENV_KEYS`: Jev runs in-process, so no subprocess needs them.
- Domain packs (`core/packs/`, docs in `docs/packs.md`): analyzers are deterministic, run nothing from their input, and scrub untrusted text (`core.security.snippet`). Findings reach an agent as a file path, never inline, through the read-only `architect` role. Every rule id needs a positive and a negative test in `tests/test_pack_*.py`. Pack fixtures hold fake credentials only.
