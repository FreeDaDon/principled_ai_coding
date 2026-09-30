"""Context bounds, enforced in code: an agent may change only its editable files.

    snap = snapshot(root)            # before the agent runs
    ...agent edits...
    bad = out_of_bounds(snap, root, editable)
    restore(snap, root, bad)         # revert anything outside the bounds

`EditableCheckpoint` is the atomic rollback (the Aider `/undo` replacement): it captures the
editable files once, before a loop starts, and puts them back if the loop fails.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .llm import Runner
from .security import resolve_inside
from .types import AgentRequest, AgentResponse

IGNORED_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".venv", ".pac", "node_modules"}
MAX_FILE_BYTES = 5_000_000  # larger files are fingerprinted and backed up to disk instead of held in memory


@dataclass
class Snapshot:
    """The tree before an agent runs. Every regular file and symlink is tracked, so any change can be undone:
    small files in memory, large files as a sha256 plus a backup copy, symlinks by target (never followed)."""

    files: dict[str, bytes] = field(default_factory=dict)  # relative posix path -> content
    large: dict[str, str] = field(default_factory=dict)    # relative posix path -> sha256 of content
    links: dict[str, str] = field(default_factory=dict)    # relative posix path -> symlink target text
    backups: tempfile.TemporaryDirectory[str] | None = None

    def paths(self) -> set[str]:
        return set(self.files) | set(self.large) | set(self.links)

    def state(self, rel: str) -> str | None:
        if rel in self.links:
            return f"link:{self.links[rel]}"
        if rel in self.files:
            return f"file:{hashlib.sha256(self.files[rel]).hexdigest()}"
        return f"file:{self.large[rel]}" if rel in self.large else None

    def backup_of(self, rel: str) -> Path:
        assert self.backups is not None, "snapshot was taken without backups"
        return Path(self.backups.name) / self.large[rel]

    def close(self) -> None:
        if self.backups is not None:
            self.backups.cleanup()


def _walk(root: Path) -> list[Path]:
    """Regular files and symlinks under root; symlinked directories are listed, never entered."""
    return [p for p in root.rglob("*")
            if not any(part in IGNORED_DIRS for part in p.relative_to(root).parts) and (p.is_symlink() or p.is_file())]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(root: Path, backup: bool = True) -> Snapshot:
    """`backup=False` records state only (enough to compare, not to restore large files)."""
    snap = Snapshot()
    for p in _walk(root):
        rel = p.relative_to(root).as_posix()
        if p.is_symlink():
            snap.links[rel] = os.readlink(p)
        elif p.stat().st_size <= MAX_FILE_BYTES:
            snap.files[rel] = p.read_bytes()
        else:
            snap.large[rel] = digest = _sha256(p)
            if backup:
                snap.backups = snap.backups or tempfile.TemporaryDirectory(prefix="pac-snapshot-")
                shutil.copyfile(p, Path(snap.backups.name) / digest)
    return snap


def check_bounds(root: Path, paths: list[str]) -> None:
    """Every context path must resolve inside root. Call it before any agent runs; raises SecurityError."""
    for rel in paths:
        resolve_inside(root, rel)


def changed_files(before: Snapshot, root: Path) -> list[str]:
    after = snapshot(root, backup=False)
    return sorted(rel for rel in before.paths() | after.paths() if before.state(rel) != after.state(rel))


def normalize(paths: list[str]) -> set[str]:
    return {Path(p).as_posix() for p in paths}  # Path() drops "./" prefixes


def out_of_bounds(before: Snapshot, root: Path, editable: list[str]) -> list[str]:
    allowed = normalize(editable)
    return [f for f in changed_files(before, root) if f not in allowed]


def restore(before: Snapshot, root: Path, paths: list[str]) -> None:
    """Put each path back to its snapshot state: rewrite changed files and links, delete created ones.
    The path itself is never followed: a symlink is replaced, not written through."""
    for rel in paths:
        target = resolve_inside(root, Path(rel).parent) / Path(rel).name
        if target.is_symlink() or (target.exists() and (rel in before.links or rel not in before.paths())):
            target.unlink()
        if rel in before.links:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(before.links[rel], target)
        elif rel in before.files:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(before.files[rel])
        elif rel in before.large:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(before.backup_of(rel), target)


class EditableCheckpoint:
    def __init__(self, root: Path, editable: list[str]) -> None:
        self.root = root
        self.state: dict[str, bytes | None] = {}
        for rel in editable:
            p = resolve_inside(root, rel)
            self.state[rel] = p.read_bytes() if p.exists() else None

    def rollback(self) -> list[str]:
        restored = []
        for rel, data in self.state.items():
            p = resolve_inside(self.root, rel)
            current = p.read_bytes() if p.exists() else None
            if current == data:
                continue
            if data is None:
                p.unlink()
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
            restored.append(rel)
        return restored


def guarded_run(runner: Runner, request: AgentRequest) -> tuple[AgentResponse, list[str]]:
    """Run an editing agent and revert every change outside request.editable. Returns (response, reverted)."""
    root = Path(request.working_dir)
    before = snapshot(root)
    try:
        response = runner.run(request)
        bad = out_of_bounds(before, root, request.editable)
        if bad:
            restore(before, root, bad)
    finally:
        before.close()
    return response, bad
