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
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .llm import Runner
from .security import resolve_inside
from .types import AgentRequest, AgentResponse

IGNORED_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".venv", ".pac", "node_modules"}
MAX_FILE_BYTES = 5_000_000  # larger files are fingerprinted and backed up to disk instead of held in memory

Stat = tuple[int, int, int, int]  # size, mtime_ns, ctime_ns, inode: unchanged means the content is unchanged


@dataclass
class Snapshot:
    """The tree before an agent runs. Every regular file and symlink is tracked, so any change can be undone.

    Content lives in one of three places, cheapest first: `blobs` (tracked in git and unchanged from the index, so
    git already stores it), `files` (in memory), `large` (sha256 plus a backup copy on disk). Symlinks are kept by
    target and never followed. `stats` lets the after-check skip every file whose stat did not change."""

    files: dict[str, bytes] = field(default_factory=dict)  # relative posix path -> content
    large: dict[str, str] = field(default_factory=dict)    # relative posix path -> sha256 of content
    blobs: dict[str, str] = field(default_factory=dict)    # relative posix path -> git blob id
    links: dict[str, str] = field(default_factory=dict)    # relative posix path -> symlink target text
    stats: dict[str, Stat] = field(default_factory=dict)
    backups: tempfile.TemporaryDirectory[str] | None = None

    def paths(self) -> set[str]:
        return set(self.files) | set(self.large) | set(self.blobs) | set(self.links)

    def backup_of(self, rel: str) -> Path:
        assert self.backups is not None, "snapshot was taken without backups"
        return Path(self.backups.name) / self.large[rel]

    def content(self, root: Path, rel: str) -> bytes:
        if rel in self.files:
            return self.files[rel]
        if rel in self.blobs:
            return _git(root, ["cat-file", "blob", self.blobs[rel]]).stdout
        return self.backup_of(rel).read_bytes()

    def matches(self, root: Path, rel: str, path: Path) -> bool:
        """Does the file now at `path` still hold the content this snapshot recorded for `rel`?"""
        if rel in self.files:
            return path.stat().st_size == len(self.files[rel]) and path.read_bytes() == self.files[rel]
        if rel in self.blobs:
            return _git_blob_id(path.read_bytes()) == self.blobs[rel]
        return rel in self.large and _sha256(path) == self.large[rel]

    def close(self) -> None:
        if self.backups is not None:
            self.backups.cleanup()


def _walk(root: Path) -> list[Path]:
    """Regular files and symlinks under root; symlinked directories are listed, never entered. Ignored
    directories are pruned before descent, so a large .venv or node_modules costs nothing."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        base = Path(dirpath)
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        found += [base / d for d in dirnames if (base / d).is_symlink()]
        for name in filenames:
            p = base / name
            if name not in IGNORED_DIRS and (p.is_symlink() or p.is_file()):
                found.append(p)
    return found


def _stat(p: Path) -> Stat:
    s = p.lstat()
    return (s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_ino)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(root: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)


def _git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def clean_tracked_blobs(root: Path) -> dict[str, str]:
    """{relative path: blob id} for regular files tracked in git whose working copy matches the index.
    Empty outside a sha1 git repo. Git's stat cache makes this cheap: nothing unchanged is read."""
    if _git(root, ["rev-parse", "--show-object-format"]).stdout.strip() != b"sha1":
        return {}
    staged = _git(root, ["ls-files", "-s", "-z"])
    dirty = _git(root, ["diff", "--name-only", "--relative", "-z"])
    if staged.returncode != 0 or dirty.returncode != 0:
        return {}
    modified = {p.decode() for p in dirty.stdout.split(b"\0") if p}
    blobs: dict[str, str] = {}
    for entry in staged.stdout.split(b"\0"):
        if not entry:
            continue
        meta, _, path = entry.partition(b"\t")
        mode, blob, stage = meta.split()
        rel = path.decode()
        if mode in (b"100644", b"100755") and stage == b"0" and rel not in modified:
            blobs[rel] = blob.decode()
    return blobs


def snapshot(root: Path) -> Snapshot:
    snap = Snapshot()
    tracked = clean_tracked_blobs(root)
    for p in _walk(root):
        rel = p.relative_to(root).as_posix()
        if p.is_symlink():
            snap.links[rel] = os.readlink(p)
            continue
        snap.stats[rel] = _stat(p)
        if rel in tracked:
            snap.blobs[rel] = tracked[rel]
        elif p.stat().st_size <= MAX_FILE_BYTES:
            snap.files[rel] = p.read_bytes()
        else:
            snap.large[rel] = digest = _sha256(p)
            snap.backups = snap.backups or tempfile.TemporaryDirectory(prefix="pac-snapshot-")
            shutil.copyfile(p, Path(snap.backups.name) / digest)
    return snap


def check_bounds(root: Path, paths: list[str]) -> None:
    """Every context path must resolve inside root. Call it before any agent runs; raises SecurityError."""
    for rel in paths:
        resolve_inside(root, rel)


def changed_files(before: Snapshot, root: Path) -> list[str]:
    """Paths created, deleted or changed since `before`. A file whose stat is unchanged is not read again."""
    changed: set[str] = set()
    seen: set[str] = set()
    for p in _walk(root):
        rel = p.relative_to(root).as_posix()
        seen.add(rel)
        if p.is_symlink():
            if before.links.get(rel) != os.readlink(p):
                changed.add(rel)
        elif rel in before.links or rel not in before.stats:
            changed.add(rel)
        elif before.stats[rel] != _stat(p) and not before.matches(root, rel, p):
            changed.add(rel)
    return sorted(changed | (before.paths() - seen))


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
        elif rel in before.files or rel in before.blobs:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(before.content(root, rel))
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
