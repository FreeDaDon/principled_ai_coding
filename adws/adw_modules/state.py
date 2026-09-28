"""Run state: one directory per run under .pac/runs/<run_id>/ with an atomically written state.json.

Every agent prompt and raw output for the run is logged next to it, so any run can be audited.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def project_root() -> Path:
    return Path(os.getenv("PAC_PROJECT_ROOT") or Path(__file__).resolve().parents[2])


def new_run_id() -> str:
    return secrets.token_hex(4)


def run_dir(run_id: str) -> Path:
    path = project_root() / ".pac" / "runs" / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


class RunState:
    def __init__(self, workflow: str, run_id: str | None = None) -> None:
        self.run_id = run_id or new_run_id()
        self.dir = run_dir(self.run_id)
        self.data: dict[str, Any] = {"run_id": self.run_id, "workflow": workflow,
                                     "started_at": datetime.now(UTC).isoformat(), "steps": []}

    def step(self, name: str, **fields: Any) -> None:
        self.data["steps"].append({"name": name, "at": datetime.now(UTC).isoformat(), **fields})
        self.save()

    def update(self, **fields: Any) -> None:
        self.data.update(fields)
        self.save()

    def save(self) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix=".state.")
        with os.fdopen(fd, "w") as f:
            json.dump(self.data, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.dir / "state.json")

    def log(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(text)
        return path
