"""Run a validation/execution command deterministically: argv (no shell), allowlisted env, timeout.

`{python}` in the command expands to the current interpreter, so configs work inside any venv.

The command usually runs code an agent just wrote, so by default it gets `exec_subprocess_env`: no model API
key and a throwaway HOME. `sandbox="bwrap"` also cuts the network and hides the real home directory and /tmp;
the working directory stays writable and the interpreter's prefix stays readable.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .security import exec_subprocess_env
from .types import ExecutionResult, Sandbox

SANDBOX_HOME = "/tmp"  # noqa: S108 - a fresh tmpfs inside the sandbox, not the host /tmp


def bwrap_prefix(cwd: Path) -> list[str]:
    """bubblewrap argv: read-only root, empty home and /tmp, writable cwd, readable interpreter, no network."""
    work = str(cwd.resolve())
    argv = ["bwrap", "--ro-bind", "/", "/", "--tmpfs", str(Path.home()), "--tmpfs", "/tmp",  # noqa: S108
            "--bind", work, work]
    for prefix in dict.fromkeys([sys.prefix, sys.base_prefix]):
        argv += ["--ro-bind", prefix, prefix]
    return argv + ["--dev", "/dev", "--proc", "/proc", "--unshare-net", "--die-with-parent", "--chdir", work]


def run_command(
    command: str, cwd: Path, timeout_s: int = 300, sandbox: Sandbox = "none", env: dict[str, str] | None = None,
) -> ExecutionResult:
    """`env` overrides the agent-code environment; pass it only for commands the operator wrote (e.g. `uv build`)."""
    cmd = command.replace("{python}", shlex.quote(sys.executable))
    argv = shlex.split(cmd)
    started = time.monotonic()
    if sandbox == "bwrap" and not shutil.which("bwrap"):
        return ExecutionResult(command=cmd, exit_code=126, output="sandbox 'bwrap' requested but bwrap is not installed")
    with tempfile.TemporaryDirectory(prefix="pac-home-") as home:
        if env is None:
            env = exec_subprocess_env(SANDBOX_HOME if sandbox == "bwrap" else home)
        if sandbox == "bwrap":
            argv = bwrap_prefix(cwd) + argv
        try:
            proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout_s, check=False)
            code, output = proc.returncode, proc.stdout + proc.stderr
        except subprocess.TimeoutExpired as exc:
            partial = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            code, output = 124, f"{partial}\nexecution timed out after {timeout_s}s"
        except FileNotFoundError as exc:
            code, output = 127, f"command not found: {exc}"
    return ExecutionResult(command=cmd, exit_code=code, output=output, duration_s=round(time.monotonic() - started, 2))
