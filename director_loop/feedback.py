"""Stack-trace hand-off: turn raw execution output into the smallest useful feedback for the coder.

Don't hand-fix a failure; feed the error back. But feed the *signal*: the failing tests, the
assertion diffs and the last traceback, not 3,000 lines of passing output.
"""

from __future__ import annotations

import hashlib
import re

_LINT_RE = re.compile(r"^\S+:\d+:\d+: [A-Z]+\d*\b.*$", re.MULTILINE)
_SIG_RE = re.compile(r"^(?:FAILED|ERROR) \S+|^E\s+\w+(?:Error|Exception)\b.*|^\w+(?:Error|Exception): .*", re.MULTILINE)


def truncate(text: str, max_chars: int) -> str:
    """Keep head and tail: the start of a failure and the final error line both matter."""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return f"{text[:half]}\n[... {len(text) - max_chars} chars omitted ...]\n{text[-half:]}"


def extract_failures(output: str, max_chars: int = 6000) -> str:
    parts: list[str] = []
    if "= FAILURES =" in output or "= ERRORS =" in output:
        start = min(i for i in (output.find("= FAILURES ="), output.find("= ERRORS =")) if i != -1)
        parts.append(output[output.rfind("\n", 0, start) + 1:])
    elif "Traceback (most recent call last)" in output:
        parts.append(output[output.rfind("Traceback (most recent call last)"):])
    elif _LINT_RE.search(output):
        parts.append("\n".join(_LINT_RE.findall(output)))
    else:
        parts.append("\n".join(output.strip().splitlines()[-40:]))
    return truncate("\n".join(parts).strip(), max_chars)


def failure_signature(output: str) -> str:
    """Stable fingerprint of *which* things failed; identical twice in a row means no progress."""
    marks = sorted(set(m.strip() for m in _SIG_RE.findall(output)))
    if not marks:
        tail = output.strip().splitlines()[-20:]
        marks = [re.sub(r"\d+(\.\d+)?", "N", ln) for ln in tail]
    return hashlib.sha256("\n".join(marks).encode()).hexdigest()[:16]
