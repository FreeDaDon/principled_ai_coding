#!/usr/bin/env -S uv run
"""ADW: version bump + changelog + build (Lessons 6 and 8: automate the thing you do every release).

Deterministic where it can be (the semver bump is code, not a prompt), AI where it adds value (a
readable changelog entry from raw commit subjects). Nothing is pushed.

Usage:
  uv run adws/adw_version_release.py patch                    # bump + changelog
  uv run adws/adw_version_release.py minor --build --commit --tag
  uv run adws/adw_version_release.py patch --no-ai            # changelog from commit subjects only
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path
from typing import Literal

from adws.adw_modules import git_ops
from core.execution import run_command
from core.llm import Runner, get_runner
from core.security import fence_untrusted
from core.types import AgentRequest

Bump = Literal["patch", "minor", "major"]
_VERSION_RE = re.compile(r'^(version\s*=\s*")(\d+)\.(\d+)\.(\d+)(")', re.MULTILINE)


def bump_version(version: str, kind: Bump) -> str:
    major, minor, patch = (int(x) for x in version.split("."))
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def bump_pyproject(path: Path, kind: Bump) -> tuple[str, str]:
    text = path.read_text()
    m = _VERSION_RE.search(text)
    if not m:
        raise ValueError(f"no `version = \"X.Y.Z\"` in {path}")
    old = ".".join(m.group(2, 3, 4))
    new = bump_version(old, kind)
    path.write_text(text[: m.start()] + f"{m.group(1)}{new}{m.group(5)}" + text[m.end():])
    return old, new


def changelog_entry(commits: list[str], version: str, use_ai: bool, runner: Runner | None, cwd: Path) -> str:
    if not commits:
        return "- No changes recorded since the last tag."
    if not use_ai:
        return "\n".join(f"- {c}" for c in commits)
    runner = runner or get_runner()
    prompt = (
        f"Write the CHANGELOG entry for version {version}. Group bullets under 'Added', 'Changed', 'Fixed' "
        "(omit empty groups). Only state facts present in the commit subjects. Markdown bullets only, no preamble.\n\n"
        + fence_untrusted("\n".join(commits), "commit_subjects")
    )
    resp = runner.run(AgentRequest(role="writer", prompt=prompt, model="haiku", working_dir=str(cwd)))
    return resp.output.strip() if resp.success and resp.output.strip() else "\n".join(f"- {c}" for c in commits)


def prepend_changelog(path: Path, version: str, entry: str, today: date) -> None:
    header = "# Changelog\n\n"
    body = path.read_text().removeprefix(header) if path.exists() else ""
    path.write_text(f"{header}## v{version} - {today.isoformat()}\n\n{entry}\n\n{body}".rstrip() + "\n")


def release(
    root: Path, kind: Bump, use_ai: bool = True, build: bool = False, commit: bool = False, tag: bool = False,
    runner: Runner | None = None,
) -> int:
    pyproject, changelog = root / "pyproject.toml", root / "CHANGELOG.md"
    old, new = bump_pyproject(pyproject, kind)
    commits = git_ops.log_since(root, git_ops.last_tag(root)) if git_ops.is_repo(root) else []
    prepend_changelog(changelog, new, changelog_entry(commits, new, use_ai, runner, root), date.today())
    steps = [f"version {old} -> {new}", f"CHANGELOG.md ({len(commits)} commit(s))"]
    if build:
        result = run_command("uv build", root, timeout_s=600)
        if result.exit_code != 0:
            print(f"FAIL: `uv build` exit {result.exit_code}\n{result.output[-1500:]}")
            return 1
        steps.append("built dist/")
    if commit:
        if not git_ops.commit(root, ["pyproject.toml", "CHANGELOG.md"], f"release: v{new}"):
            print("FAIL: git commit failed")
            return 1
        steps.append("committed")
        if tag:
            if not git_ops.tag(root, f"v{new}"):
                print(f"FAIL: git tag v{new} failed (does it exist?)")
                return 1
            steps.append(f"tagged v{new}")
    print(f"RELEASED v{new}: " + "; ".join(steps) + ". Not pushed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bump version, write changelog, optionally build/commit/tag.")
    ap.add_argument("bump", choices=["patch", "minor", "major"])
    ap.add_argument("--root", type=Path, default=Path.cwd())
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--tag", action="store_true", help="requires --commit")
    a = ap.parse_args(argv)
    if a.tag and not a.commit:
        ap.error("--tag requires --commit")
    return release(a.root.resolve(), a.bump, not a.no_ai, a.build, a.commit, a.tag)


if __name__ == "__main__":
    raise SystemExit(main())
