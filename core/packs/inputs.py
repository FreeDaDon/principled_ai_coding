"""Reading pack inputs safely: bounded JSON/YAML loading and a deterministic, non-escaping directory walk.

Inputs are untrusted files. Nothing here executes them; symlinks are never followed, so a connector
directory cannot point the scanner at ~/.ssh or ~/.aws.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "venv", "dist", "__pycache__", ".mypy_cache", ".ruff_cache",
                       ".pytest_cache", ".pac"})
MAX_STRUCTURED_BYTES = 10_000_000  # also bounds YAML alias expansion
DEFAULT_MAX_BYTES = 1_000_000


def load_structured(path: Path) -> Any:
    """Parse a JSON or YAML file (by extension; JSON for anything else). Oversized files raise ValueError."""
    path = Path(path)
    if path.stat().st_size > MAX_STRUCTURED_BYTES:
        raise ValueError(f"{path.name} exceeds {MAX_STRUCTURED_BYTES} bytes")
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yml", ".yaml"}:
        return yaml.safe_load(text)
    return json.loads(text)


def get_field(record: dict[str, Any], dotted: str) -> Any:
    """Look up `a.b.c` as a flat key first, then as a nested path. Missing -> None."""
    if dotted in record:
        return record[dotted]
    current: Any = record
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def is_skipped_file(path: Path) -> bool:
    """Symlinks and .env files are never read."""
    return path.is_symlink() or path.name.lower().startswith(".env")


def iter_files(root: Path) -> Iterator[Path]:
    """Deterministically walk `root`, pruning vendored/ephemeral directories and skipping unsafe files."""
    if root.is_file():
        if not is_skipped_file(root):
            yield root
        return
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not (Path(dirpath) / d).is_symlink())
        for name in sorted(filenames):
            file = Path(dirpath) / name
            if not is_skipped_file(file):
                yield file


def read_text_file(path: Path, max_bytes: int = DEFAULT_MAX_BYTES) -> str | None:
    """File contents, or None for binary / oversized / unreadable files."""
    try:
        if path.stat().st_size > max_bytes:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")
