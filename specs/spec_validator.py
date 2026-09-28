"""Parse and validate 5-layer spec prompts ("plan equals prompt").

Layers, exactly as the course names them:
  ## High-Level Objective
  ## Mid-Level Objective
  ## Implementation Notes
  ## Context            (### Beginning context / ### Ending context; mark references "(read-only)")
  ## Low-Level Tasks    (ordered; each "1. Title" followed by a fenced, IDK-led prompt)

CLI:  uv run python -m specs.spec_validator specs/templates/*.md examples/*/spec.md [--json]
Exit 1 if any spec has errors.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from core.idk import ACTION_ALIASES, first_word, has_location, keyword_density, starts_with_idk, vague_words
from core.types import ContextFile, LowLevelTask, Spec, SpecIssue, SpecReport

LAYERS = {
    "high-level objective": "high_level_objective",
    "mid-level objective": "mid_level_objectives",
    "mid-level objectives": "mid_level_objectives",
    "implementation notes": "implementation_notes",
    "context": "context",
    "low-level tasks": "low_level_tasks",
}
MIN_DENSITY = 0.25


def _sections(text: str, level: str) -> dict[str, str]:
    """Split markdown into {heading (lowercase): body} at the given heading level, ignoring fenced code."""
    out: dict[str, list[str]] = {}
    current: str | None = None
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else re.match(rf"^{level}\s+(.+?)\s*$", line)
        if m:
            current = m.group(1).strip().lower()
            out[current] = []
        elif current is not None:
            out[current].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def _bullets(body: str) -> list[str]:
    return [re.sub(r"^\s*[-*]\s+", "", ln).strip() for ln in body.splitlines() if re.match(r"^\s*[-*]\s+", ln)]


def _prose(body: str) -> str:
    lines = [re.sub(r"^\s*[-*]\s+", "", ln).strip() for ln in body.splitlines()]
    return " ".join(ln for ln in lines if ln and not ln.startswith(">"))


def _context_files(body: str) -> list[ContextFile]:
    files = []
    for item in _bullets(body):
        read_only = bool(re.search(r"\((read-?only)\)", item, re.IGNORECASE))
        path = re.sub(r"\(.*?\)", "", item).strip().strip("`").strip()
        if path:
            files.append(ContextFile(path=path, read_only=read_only))
    return files


def _tasks(body: str) -> list[LowLevelTask]:
    tasks: list[LowLevelTask] = []
    title: str | None = None
    fence: list[str] | None = None
    prompt: str | None = None

    def flush() -> None:
        if title is not None:
            tasks.append(LowLevelTask(title=title, prompt=(prompt or title).strip()))

    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            if fence is None:
                fence = []
            else:
                if prompt is None:
                    prompt = "\n".join(fence)
                fence = None
            continue
        if fence is not None:
            fence.append(line)
            continue
        m = re.match(r"^\s*\d+\.\s+(.+)$", line)
        if m:
            flush()
            title, prompt = m.group(1).strip(), None
    flush()
    return tasks


def parse_spec(text: str) -> Spec:
    title_m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    raw = _sections(text, "##")
    sec = {LAYERS[k]: v for k, v in raw.items() if k in LAYERS}
    ctx = _sections(sec.get("context", ""), "###")
    return Spec(
        title=title_m.group(1).strip() if title_m else "",
        high_level_objective=_prose(sec.get("high_level_objective", "")),
        mid_level_objectives=_bullets(sec.get("mid_level_objectives", "")),
        implementation_notes=_bullets(sec.get("implementation_notes", "")),
        beginning_context=_context_files(next((v for k, v in ctx.items() if k.startswith("beginning")), "")),
        ending_context=_context_files(next((v for k, v in ctx.items() if k.startswith("ending")), "")),
        low_level_tasks=_tasks(sec.get("low_level_tasks", "")),
    )


def validate(spec: Spec, path: str = "<spec>") -> SpecReport:
    issues: list[SpecIssue] = []

    def err(layer: str, msg: str) -> None:
        issues.append(SpecIssue(level="error", layer=layer, message=msg))

    def warn(layer: str, msg: str) -> None:
        issues.append(SpecIssue(level="warning", layer=layer, message=msg))

    if not spec.title:
        err("title", "missing '# Title'")
    if not spec.high_level_objective:
        err("high_level_objective", "missing High-Level Objective")
    elif vague_words(spec.high_level_objective):
        warn("high_level_objective", f"vague words {vague_words(spec.high_level_objective)}")
    if not spec.mid_level_objectives:
        err("mid_level_objectives", "missing Mid-Level Objective bullets")
    if not spec.implementation_notes:
        err("implementation_notes", "missing Implementation Notes bullets")
    if not spec.beginning_context:
        err("context", "missing Beginning context files")
    if not spec.ending_context:
        err("context", "missing Ending context files")
    elif not spec.editable_files:
        err("context", "Ending context has no editable files (everything is read-only)")

    all_prompts = "\n".join(t.prompt for t in spec.low_level_tasks)
    ending = {c.path for c in spec.ending_context}
    for c in spec.beginning_context:
        if not c.read_only and c.path not in ending and not re.search(rf"DELETE\s+{re.escape(c.path)}", all_prompts):
            err("context", f"{c.path} is in Beginning context but not Ending context (and no task DELETEs it)")

    if not spec.low_level_tasks:
        err("low_level_tasks", "missing Low-Level Tasks")
    for i, task in enumerate(spec.low_level_tasks, 1):
        layer = f"low_level_tasks[{i}]"
        if not starts_with_idk(task.prompt):
            alias = ACTION_ALIASES.get(first_word(task.prompt).lower())
            hint = f" (use {alias})" if alias else ""
            err(layer, f"prompt must start with an action keyword (CREATE, UPDATE, ...){hint}: {task.title!r}")
        if not has_location(task.prompt):
            err(layer, f"prompt names no file, def/class or identifier: {task.title!r}")
        if vague_words(task.prompt):
            warn(layer, f"vague words {vague_words(task.prompt)}")

    density = keyword_density(all_prompts) if all_prompts else 0.0
    if spec.low_level_tasks and density < MIN_DENSITY:
        warn("low_level_tasks", f"keyword density {density} < {MIN_DENSITY}: use more IDKs and concrete names")
    return SpecReport(path=path, issues=issues, keyword_density=density)


def validate_file(path: str | Path) -> SpecReport:
    return validate(parse_spec(Path(path).read_text()), str(path))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate 5-layer spec prompts.")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    reports = [validate_file(p) for p in a.paths]
    if a.json:
        print(json.dumps([r.model_dump() | {"ok": r.ok} for r in reports], indent=2))
    else:
        for r in reports:
            print(f"{'PASS' if r.ok else 'FAIL'}  {r.path}  (density {r.keyword_density})")
            for i in r.issues:
                print(f"  {i.level:<7} {i.layer}: {i.message}")
    return 0 if all(r.ok for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
