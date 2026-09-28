"""Git via argv lists only (no shell). Read helpers plus commit and tag; nothing destructive."""

from __future__ import annotations

import subprocess
from pathlib import Path


def git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def is_repo(cwd: Path) -> bool:
    return git(["rev-parse", "--is-inside-work-tree"], cwd).stdout.strip() == "true"


def is_clean(cwd: Path) -> bool:
    return git(["status", "--porcelain"], cwd).stdout.strip() == ""


def last_tag(cwd: Path) -> str | None:
    r = git(["describe", "--tags", "--abbrev=0"], cwd)
    return r.stdout.strip() if r.returncode == 0 else None


def log_since(cwd: Path, ref: str | None) -> list[str]:
    rng = [f"{ref}..HEAD"] if ref else []
    r = git(["log", "--pretty=%s", *rng], cwd)
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def commit(cwd: Path, paths: list[str], message: str) -> bool:
    if git(["add", "--", *paths], cwd).returncode != 0:
        return False
    return git(["commit", "-m", message, "--", *paths], cwd).returncode == 0


def tag(cwd: Path, name: str) -> bool:
    return git(["tag", name], cwd).returncode == 0
