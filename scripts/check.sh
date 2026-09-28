#!/usr/bin/env bash
# The deterministic gate: lint, types, tests. Run before every commit.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run ruff check .
uv run mypy core adws director_loop specs
uv run pytest -q -p no:cacheprovider
