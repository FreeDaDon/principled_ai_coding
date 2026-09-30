#!/usr/bin/env -S uv run
"""ADW: environment diagnostics (Lesson 1). BLUF table of what's ready and what's missing.

Usage:  uv run adws/adw_doctor.py
Exit 1 if a required tool or Claude auth is missing. Secret values are never printed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

REQUIRED = ["uv", "git", "claude"]
OPTIONAL = ["gh", "terraform"]
TIMEOUT_S = 20


def _run(argv: list[str]) -> subprocess.CompletedProcess[str] | None:
    """None when the command hangs or cannot start; the doctor reports that instead of crashing."""
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT_S, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return None


def version(tool: str) -> str | None:
    if not shutil.which(tool):
        return None
    r = _run([tool, "--version"])
    if r is None or r.returncode != 0:
        return None
    lines = (r.stdout or r.stderr).strip().splitlines()
    return lines[0] if lines else "installed"


def claude_auth() -> tuple[bool, str]:
    if os.getenv("ANTHROPIC_API_KEY"):
        return True, "ANTHROPIC_API_KEY is set"
    if not shutil.which("claude"):
        return False, "claude CLI not installed"
    r = _run(["claude", "auth", "status", "--json"])
    if r is None:
        return False, f"`claude auth status` did not answer within {TIMEOUT_S}s"
    try:
        status = json.loads(r.stdout)
    except json.JSONDecodeError:
        return False, "could not read `claude auth status`"
    if status.get("loggedIn"):
        return True, f"logged in via {status.get('authMethod', 'unknown')}"
    return False, "not logged in: run `claude auth login` or export ANTHROPIC_API_KEY"


def main() -> int:
    rows: list[tuple[str, bool, str, bool]] = [("python", sys.version_info >= (3, 12), sys.version.split()[0], True)]
    for tool in REQUIRED + OPTIONAL:
        v = version(tool)
        rows.append((tool, v is not None, v or "not found or not responding", tool in REQUIRED))
    ok, detail = claude_auth()
    rows.append(("claude auth", ok, detail, True))
    runner = os.getenv("PAC_RUNNER", "claude")
    rows.append(("PAC_RUNNER", True, f"{runner} ({'offline, $0' if runner == 'mock' else 'real Claude calls'})", False))

    failed = [name for name, good, _, required in rows if required and not good]
    print("READY" if not failed else f"NOT READY: fix {', '.join(failed)}")
    for name, good, detail, required in rows:
        mark = "ok  " if good else ("FAIL" if required else "skip")
        print(f"  {mark}  {name:<12} {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
