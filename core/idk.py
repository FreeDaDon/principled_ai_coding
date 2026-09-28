"""Information-Dense Keywords (IDKs): the prompt vocabulary from "Know Your IDKs".

A good prompt phrase is LOCATION, ACTION, DETAIL:

    UPDATE main.py: REPLACE word count print WITH word_count_bar_chart, MOVE threshold logic after for loop

CLI:  uv run python -m core.idk "UPDATE main.py: ADD format_as_yaml MIRROR format_as_json"
"""

from __future__ import annotations

import json
import re
import sys

from pydantic import BaseModel, Field

from .types import PromptLevel, PromptScore

# Action keywords, in the course's order of importance, plus the syllabus additions.
ACTION_KEYWORDS = [
    "CREATE", "UPDATE", "DELETE",
    "ADD", "REMOVE", "MOVE", "REPLACE", "SAVE", "MIRROR",
    "APPEND", "USE", "RESOLVE", "WRAP", "OVERRIDE",
]
# Detail keywords name *what* is acted on. `def`/`function`/`class` with a full signature let the
# model infer the body.
DETAIL_KEYWORDS = {"var", "function", "class", "type", "file", "default", "def", "interface", "method", "test", "with"}
VAGUE_WORDS = {
    "data", "enhance", "improve", "better", "stuff", "things", "somehow", "nicer", "cleanup", "clean",
    "optimize", "various", "etc", "appropriate", "properly", "robust", "modernize",
}
ACTION_ALIASES = {  # variants far from the root word dilute the signal; suggest the root instead
    "build": "CREATE", "make": "CREATE", "write": "CREATE", "generate": "CREATE", "modify": "UPDATE",
    "change": "UPDATE", "edit": "UPDATE", "fix": "RESOLVE", "insert": "ADD", "drop": "REMOVE", "copy": "MIRROR",
}

_TOKEN_RE = re.compile(r"[A-Za-z_][\w./<>{}-]*(?:\([^)]*\))?|\S")
_LOCATION_RE = re.compile(
    r"[\w<>{}/-]+\.[A-Za-z]{1,5}\b"      # file.ext  (the extension is what makes it an IDK)
    r"|\bdef\s+\w+|\bclass\s+\w+"        # language keywords
    r"|\b[a-z]+(?:_[a-z0-9]+)+\b"        # snake_case identifiers
    r"|\b[a-z]+[A-Z]\w*\b"              # camelCase identifiers
    r"|\b[A-Z][a-z]+[A-Z]\w*\b"          # PascalCase types
    r"|\b\w+\(\)"                        # call-like names
)


class PromptAction(BaseModel):
    action: str
    detail: str


class PromptPhrase(BaseModel):
    location: str | None = None
    actions: list[PromptAction] = Field(default_factory=list)


def tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def is_code_token(tok: str) -> bool:
    return bool(_LOCATION_RE.fullmatch(tok) or _LOCATION_RE.search(tok))


def action_keywords(text: str) -> list[str]:
    """Action keywords in order of appearance. Uppercase marks an IDK; lowercase counts only at the start."""
    found = [t for t in re.findall(r"\b[A-Z]{3,}\b", text) if t in ACTION_KEYWORDS]
    first = first_word(text)
    if first.upper() in ACTION_KEYWORDS and (not found or found[0] != first.upper()):
        found.insert(0, first.upper())
    return found


def first_word(text: str) -> str:
    m = re.match(r"\s*([A-Za-z]+)", text)
    return m.group(1) if m else ""


def starts_with_idk(text: str) -> bool:
    return first_word(text).upper() in ACTION_KEYWORDS


def has_location(text: str) -> bool:
    return bool(_LOCATION_RE.search(text))


def vague_words(text: str) -> list[str]:
    words = {w.lower() for w in re.findall(r"[A-Za-z]+", text)}
    return sorted(words & VAGUE_WORDS)


def keyword_density(text: str) -> float:
    """Share of tokens that carry signal: IDKs, detail keywords, and concrete code locations."""
    toks = [t for t in tokens(text) if re.match(r"\w", t)]
    if not toks:
        return 0.0
    dense = sum(
        1 for t in toks
        if t.upper() in ACTION_KEYWORDS and t.isupper() or t.lower() in DETAIL_KEYWORDS or is_code_token(t)
    )
    return round(dense / len(toks), 3)


def parse_phrase(line: str) -> PromptPhrase:
    """Parse 'LOCATION: ACTION detail, ACTION detail' or 'ACTION LOCATION: ACTION detail'."""
    line = line.strip()
    location = None
    head, sep, body = line.partition(":")
    if sep:
        head_words = head.split()
        if head_words and head_words[0].upper() in ACTION_KEYWORDS and len(head_words) > 1:
            location = " ".join(head_words[1:])
            body = f"{head_words[0]} {body}" if not action_keywords(body) else body
        else:
            location = head.strip()
    else:
        body = line
    actions: list[PromptAction] = []
    parts = re.split(r"\b(" + "|".join(ACTION_KEYWORDS) + r")\b", body)
    for i in range(1, len(parts), 2):
        detail = parts[i + 1].strip(" ,;") if i + 1 < len(parts) else ""
        actions.append(PromptAction(action=parts[i], detail=detail))
    return PromptPhrase(location=location, actions=actions)


def score_prompt(text: str) -> PromptScore:
    """Heuristic Big-Three prompt check: too high (no location, vague), balanced, too low (verbose per action)."""
    words = len(re.findall(r"\S+", text))
    actions = action_keywords(text)
    vague = vague_words(text)
    located = has_location(text)
    density = keyword_density(text)
    level: PromptLevel
    if not located or (vague and not actions):
        level = "too_high"
    elif words / max(len(actions), 1) > 40 and density < 0.3:
        level = "too_low"
    else:
        level = "balanced"
    return PromptScore(
        words=words, idk_count=len(actions), action_keywords=actions, keyword_density=density,
        vague_words=vague, has_location=located, level=level,
    )


def suggestions(text: str) -> list[str]:
    out = []
    first = first_word(text).lower()
    if first in ACTION_ALIASES:
        out.append(f"use {ACTION_ALIASES[first]} instead of '{first}' (keep variants close to the root keyword)")
    score = score_prompt(text)
    if not score.has_location:
        out.append("name a LOCATION: a file with its extension, a def/class, or a unique identifier")
    if score.vague_words:
        out.append(f"replace vague words {score.vague_words} with the concrete change")
    if score.level == "too_low":
        out.append("condense to a mid-level prompt: say what, not how")
    if not score.action_keywords:
        out.append(f"lead with an action keyword: {', '.join(ACTION_KEYWORDS[:6])}...")
    return out


def main(argv: list[str] | None = None) -> int:
    text = " ".join(argv if argv is not None else sys.argv[1:]) or sys.stdin.read()
    score = score_prompt(text)
    report = {
        "score": score.model_dump(),
        "phrase": parse_phrase(text.splitlines()[0] if text.strip() else "").model_dump(),
        "suggestions": suggestions(text),
    }
    print(json.dumps(report, indent=2))
    return 0 if score.level == "balanced" else 1


if __name__ == "__main__":
    raise SystemExit(main())
