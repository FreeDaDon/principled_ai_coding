"""Run a validation/execution command deterministically: argv (no shell), allowlisted env, timeout.

`{python}` in the command expands to the current interpreter, so configs work inside any venv.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
import time
from pathlib import Path

from .security import safe_subprocess_env
from .types import ExecutionResult


def run_command(command: str, cwd: Path, timeout_s: int = 300) -> ExecutionResult:
    cmd = command.replace("{python}", shlex.quote(sys.executable))
    started = time.monotonic()
    try:
        proc = subprocess.run(shlex.split(cmd), cwd=cwd, env=safe_subprocess_env(), capture_output=True,
                              text=True, timeout=timeout_s, check=False)
        code, output = proc.returncode, proc.stdout + proc.stderr
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        code, output = 124, f"{partial}\nexecution timed out after {timeout_s}s"
    except FileNotFoundError as exc:
        code, output = 127, f"command not found: {exc}"
    return ExecutionResult(command=cmd, exit_code=code, output=output, duration_s=round(time.monotonic() - started, 2))
