"""Read-only prompt cache ("semantic" in the practical sense: normalized prompt + context state).

Key: sha256 of role, model, normalized prompt (whitespace collapsed, run ids and timestamps
removed) and the hashes of the context files. Only non-mutating roles are cached: replaying a
coder's text would not replay its edits, so coder/editor calls are never cached.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from core.llm import Runner
from core.types import AgentRequest, AgentResponse

from .state import project_root

CACHEABLE_ROLES = {"architect", "evaluator"}
_VOLATILE = [re.compile(r"\b[0-9a-f]{8}\b"), re.compile(r"\d{4}-\d{2}-\d{2}T[\d:.+Z-]+")]


def normalize(prompt: str) -> str:
    for pat in _VOLATILE:
        prompt = pat.sub("<v>", prompt)
    return re.sub(r"\s+", " ", prompt).strip()


def cache_key(request: AgentRequest) -> str:
    h = hashlib.sha256()
    h.update(f"{request.role}\0{request.model}\0{normalize(request.prompt)}\0".encode())
    root = Path(request.working_dir)
    for rel in sorted(request.editable + request.read_only):
        p = root / rel
        h.update(rel.encode() + b"\0" + (hashlib.sha256(p.read_bytes()).digest() if p.is_file() else b"-"))
    return h.hexdigest()


class PromptCache:
    def __init__(self, directory: Path | None = None) -> None:
        self.dir = directory or project_root() / ".pac" / "cache"
        self.dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def enabled() -> bool:
        return os.getenv("PAC_CACHE", "1") != "0"

    def get(self, key: str) -> AgentResponse | None:
        p = self.dir / f"{key}.json"
        if not p.exists():
            return None
        resp = AgentResponse.model_validate_json(p.read_text())
        return resp.model_copy(update={"cached": True, "usage": resp.usage.model_copy(update={"cost_usd": 0.0})})

    def put(self, key: str, response: AgentResponse) -> None:
        (self.dir / f"{key}.json").write_text(json.dumps(response.model_dump()))


def cached_run(runner: Runner, request: AgentRequest, cache: PromptCache | None) -> AgentResponse:
    """Run through the cache when the role is read-only; always run mutating roles."""
    if cache is None or request.role not in CACHEABLE_ROLES or not PromptCache.enabled():
        return runner.run(request)
    key = cache_key(request)
    hit = cache.get(key)
    if hit is not None:
        return hit
    response = runner.run(request)
    if response.success:
        cache.put(key, response)
    return response
