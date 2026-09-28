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
from dataclasses import dataclass, field
from pathlib import Path

from .llm import Runner
from .security import resolve_inside
from .types import AgentRequest, AgentResponse

IGNORED_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".venv", ".pac", "node_modules"}
MAX_FILE_BYTES = 5_000_000


@dataclass
class Snapshot:
    files: dict[str, bytes] = field(default_factory=dict)  # relative posix path -> content

    def digest(self, rel: str) -> str | None:
        data = self.files.get(rel)
        return hashlib.sha256(data).hexdigest() if data is not None else None


def _walk(root: Path) -> list[Path]:
    out = []
    for p in root.rglob("*"):
        if any(part in IGNORED_DIRS for part in p.relative_to(root).parts):
            continue
        if p.is_file() and not p.is_symlink() and p.stat().st_size <= MAX_FILE_BYTES:
            out.append(p)
    return out


def snapshot(root: Path) -> Snapshot:
    return Snapshot({p.relative_to(root).as_posix(): p.read_bytes() for p in _walk(root)})


def changed_files(before: Snapshot, root: Path) -> list[str]:
    after = snapshot(root)
    keys = set(before.files) | set(after.files)
    return sorted(k for k in keys if before.files.get(k) != after.files.get(k))


def normalize(paths: list[str]) -> set[str]:
    return {Path(p).as_posix() for p in paths}  # Path() drops "./" prefixes


def out_of_bounds(before: Snapshot, root: Path, editable: list[str]) -> list[str]:
    allowed = normalize(editable)
    return [f for f in changed_files(before, root) if f not in allowed]


def restore(before: Snapshot, root: Path, paths: list[str]) -> None:
    """Put each path back to its snapshot state: rewrite modified/deleted files, delete created ones."""
    for rel in paths:
        target = resolve_inside(root, rel)
        if rel in before.files:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(before.files[rel])
        elif target.exists():
            target.unlink()


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
    response = runner.run(request)
    bad = out_of_bounds(before, root, request.editable)
    if bad:
        restore(before, root, bad)
    return response, bad
