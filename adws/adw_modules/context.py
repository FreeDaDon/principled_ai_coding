"""Context assembly with a dynamic token budget ("don't overload your context").

Editable files are always included (the agent must see what it changes). Read-only files are
included in the order given (earlier = higher priority) until the budget is spent; the rest are
listed by path only, so the model knows they exist without paying for them.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from core.pitfalls import estimate_tokens
from core.security import resolve_inside


class ContextBundle(BaseModel):
    files: dict[str, str] = Field(default_factory=dict)   # path -> content
    dropped: list[str] = Field(default_factory=list)      # read-only files left out for budget
    tokens: int = 0
    over_budget: bool = False                             # editable files alone exceed the budget


def _read(root: Path, rel: str) -> str:
    p = resolve_inside(root, rel)
    return p.read_text(errors="replace") if p.is_file() else "(file does not exist yet)"


def build_context(root: Path, editable: list[str], read_only: list[str], token_budget: int) -> ContextBundle:
    bundle = ContextBundle()
    for rel in editable:
        text = _read(root, rel)
        bundle.files[rel] = text
        bundle.tokens += estimate_tokens(text)
    bundle.over_budget = bundle.tokens > token_budget
    for rel in read_only:
        text = _read(root, rel)
        cost = estimate_tokens(text)
        if bundle.tokens + cost > token_budget:
            bundle.dropped.append(rel)
            continue
        bundle.files[rel] = text
        bundle.tokens += cost
    return bundle


def render_files(bundle: ContextBundle) -> str:
    parts = [f"### {path}\n```\n{text}\n```" for path, text in bundle.files.items()]
    if bundle.dropped:
        parts.append("Omitted for token budget (read-only, exist on disk): " + ", ".join(bundle.dropped))
    return "\n\n".join(parts)
