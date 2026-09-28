"""The six pitfalls from "How to Suck at AI Coding": too little or too much of each of the Big Three.

Balance, then Boost: fix these before tuning anything else.

CLI:  uv run python -m core.pitfalls "UPDATE scorer.py: ..." --editable src/scorer.py --model haiku --task-class heavy
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .idk import score_prompt
from .types import Pitfall, TaskClass

_FILE_RE = re.compile(r"[\w/.-]+\.(?:py|ts|tsx|js|md|json|ya?ml|toml|tf|sql|sh|go|rs|log)\b")
_DUPLICATE_SUFFIX_RE = re.compile(r"(_v\d+|_vnext|_old|_new|_copy|_backup|\.bak)$")


def estimate_tokens(text: str) -> int:
    """~4 chars per token. Good enough to budget context; real usage comes from the CLI result."""
    return max(1, len(text) // 4)


def context_tokens(base_dir: Path, files: list[str]) -> int:
    total = 0
    for rel in files:
        p = base_dir / rel
        if p.is_file():
            total += estimate_tokens(p.read_text(errors="replace"))
    return total


def check(
    prompt: str,
    editable: list[str],
    read_only: list[str] | None = None,
    model: str = "sonnet",
    task_class: TaskClass = "standard",
    token_budget: int = 40_000,
    base_dir: Path | None = None,
) -> list[Pitfall]:
    read_only = read_only or []
    in_context = set(editable) | set(read_only)
    names = {Path(p).name for p in in_context}
    found: list[Pitfall] = []

    missing = sorted({f for f in _FILE_RE.findall(prompt) if f not in in_context and Path(f).name not in names})
    if missing:
        found.append(Pitfall(kind="missing_context", severity="medium",
                             message=f"prompt names files not in context: {missing}",
                             fix="add them as editable or read-only, or ask: could I solve this with these files?"))

    dupes = sorted(p for p in in_context if _DUPLICATE_SUFFIX_RE.search(re.sub(r"\.\w+$", "", Path(p).name)))
    tokens = context_tokens(base_dir, sorted(in_context)) if base_dir else 0
    if tokens > token_budget or dupes:
        why = []
        if tokens > token_budget:
            why.append(f"~{tokens} tokens over the {token_budget} budget")
        if dupes:
            why.append(f"near-duplicate files confuse the model: {dupes}")
        found.append(Pitfall(kind="excessive_context", severity="medium", message="; ".join(why),
                             fix="only add files that need changes; move references to read-only or drop them"))

    score = score_prompt(prompt)
    if score.level == "too_high":
        found.append(Pitfall(kind="prompt_too_high", severity="high",
                             message=f"no concrete location or vague words {score.vague_words}",
                             fix="LOCATION: ACTION DETAIL with information-dense keywords"))
    elif score.level == "too_low":
        found.append(Pitfall(kind="prompt_too_low", severity="low",
                             message=f"{score.words} words for {max(score.idk_count, 1)} action(s)",
                             fix="condense to a mid-level prompt; what > how"))

    tier = next((t for t in ("haiku", "sonnet", "opus") if t in model), "sonnet")
    if task_class == "heavy" and tier == "haiku":
        found.append(Pitfall(kind="weak_model", severity="high", message=f"{model} on a heavy task",
                             fix="don't go cheap on the model: use sonnet or opus"))
    if task_class == "mechanical" and tier == "opus":
        found.append(Pitfall(kind="model_overkill", severity="low", message=f"{model} on a mechanical task",
                             fix="route mechanical work to haiku"))
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check a prompt + context + model for the six pitfalls.")
    ap.add_argument("prompt")
    ap.add_argument("--editable", nargs="*", default=[])
    ap.add_argument("--read-only", nargs="*", default=[])
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--task-class", default="standard", choices=["mechanical", "standard", "heavy"])
    ap.add_argument("--token-budget", type=int, default=40_000)
    ap.add_argument("--base-dir", default=".")
    a = ap.parse_args(argv)
    found = check(a.prompt, a.editable, a.read_only, a.model, a.task_class, a.token_budget, Path(a.base_dir))
    print(json.dumps([p.model_dump() for p in found], indent=2))
    return 1 if any(p.severity == "high" for p in found) else 0


if __name__ == "__main__":
    raise SystemExit(main())
