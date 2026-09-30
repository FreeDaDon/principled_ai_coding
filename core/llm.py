"""The Claude replacement for Aider's `Coder`: one function call = one focused agent.

Runners:
  ClaudeRunner - the real `claude -p` CLI (stream-json, timeout, process-group kill)
  MockRunner   - deterministic offline runner (PAC_RUNNER=mock); tests and dry runs cost $0

Each role gets the narrowest tool set that can do its job:
  coder/editor -> Read, Edit, Write, Glob, Grep (no Bash)  acceptEdits
  architect    -> Read, Glob, Grep                          read-only
  evaluator    -> no tools                                  judge only
  writer       -> no tools                                  text only
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .security import resolve_inside, safe_subprocess_env
from .types import AgentRequest, AgentResponse, Role, Usage

CLAUDE_PATH = os.getenv("CLAUDE_CODE_PATH", "claude")

ROLE_TOOLS: dict[Role, list[str]] = {
    "coder": ["Read", "Edit", "Write", "Glob", "Grep"],
    "editor": ["Read", "Edit", "Write", "Glob", "Grep"],
    "architect": ["Read", "Glob", "Grep"],
    "evaluator": [],
    "writer": [],
}
EDITING_ROLES: set[Role] = {"coder", "editor"}


# ----------------------------------------------------------------------------- templates
def render_template(path: Path, args: list[str]) -> str:
    """Render a .claude/commands template: strip frontmatter, substitute $1..$9 and $ARGUMENTS."""
    text = path.read_text()
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            text = text[end + 5:]
    for i in range(9, 0, -1):
        text = text.replace(f"${i}", args[i - 1] if i <= len(args) else "")
    return text.replace("$ARGUMENTS", " ".join(args))


# ----------------------------------------------------------------------------- output parsing
def parse_stream_json(raw: str) -> dict | None:
    """Return the final `result` message of a `claude -p --output-format stream-json` run."""
    result = None
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(msg, dict) and msg.get("type") == "result":
            result = msg
    return result


def usage_from_result(result: dict) -> Usage:
    u = result.get("usage") or {}
    return Usage(
        input_tokens=int(u.get("input_tokens", 0) or 0),
        output_tokens=int(u.get("output_tokens", 0) or 0),
        cache_read_input_tokens=int(u.get("cache_read_input_tokens", 0) or 0),
        cache_creation_input_tokens=int(u.get("cache_creation_input_tokens", 0) or 0),
        cost_usd=float(result.get("total_cost_usd", 0.0) or 0.0),
    )


def extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of model text (tolerates ```json fences and prose around it)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    start = text.find("{")
    if start != -1:
        candidates.append(text[start: text.rfind("}") + 1])
    for c in candidates:
        try:
            value = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


# ----------------------------------------------------------------------------- runners
class Runner(Protocol):
    def run(self, request: AgentRequest) -> AgentResponse: ...


class ClaudeRunner:
    def build_command(self, request: AgentRequest) -> list[str]:
        tools = ROLE_TOOLS[request.role]
        cmd = [CLAUDE_PATH, "-p", "--model", request.model, "--output-format", "stream-json", "--verbose"]
        # Isolate agents from the operator's personal ~/.claude config (CLAUDE.md, hooks, MCP servers):
        # deterministic context, and a ~7x cheaper floor per call. Project settings still apply.
        cmd += ["--setting-sources", "project", "--strict-mcp-config"]
        cmd += ["--tools", ",".join(tools)]
        if tools:
            cmd += ["--allowedTools", ",".join(tools)]
        cmd += ["--permission-mode", "acceptEdits" if request.role in EDITING_ROLES else "dontAsk"]
        if request.json_schema is not None:
            cmd += ["--json-schema", json.dumps(request.json_schema)]
        if request.max_budget_usd is not None:
            cmd += ["--max-budget-usd", f"{max(request.max_budget_usd, 0.01):.2f}"]
        return cmd

    def run(self, request: AgentRequest) -> AgentResponse:
        cmd = self.build_command(request)
        log_dir = Path(request.log_dir) if request.log_dir else None
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            cwd=request.working_dir, env=safe_subprocess_env(), start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(input=request.prompt, timeout=request.timeout_s)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            return AgentResponse(output=f"agent timed out after {request.timeout_s}s", success=False,
                                 model=request.model)
        if log_dir:
            (log_dir / f"{request.role}_raw.jsonl").write_text(stdout)
        result = parse_stream_json(stdout)
        if result is None:
            return AgentResponse(output=f"no result from claude (exit {proc.returncode}): {stderr[-500:]}",
                                 success=False, model=request.model)
        structured = result.get("structured_output")
        return AgentResponse(
            output=str(result.get("result", "")),
            success=not result.get("is_error", False),
            model=request.model,
            usage=usage_from_result(result),
            structured=structured if isinstance(structured, dict) else None,
        )


MockHandler = Callable[[AgentRequest, int], str]


def _mock_coder(request: AgentRequest, attempt: int) -> str:
    """First attempt changes nothing (so the loop sees a real failure); later attempts copy the
    reference solution over the editable files. Deterministic stand-in for a coding agent."""
    if attempt == 1:
        return "mock: first attempt, no changes"
    return mock_apply_solution(request, attempt)


def mock_apply_solution(request: AgentRequest, attempt: int) -> str:
    """Copy the reference solution over the editable files on every call. For single-shot workflows
    (architect/editor) that have no retry loop for a failing first attempt to exercise."""
    solution = request.metadata.get("mock_solution")
    if not solution:
        return "mock: no reference solution, no changes"
    root = Path(request.working_dir)
    copied = []
    for rel in request.editable:
        src = resolve_inside(root, Path(solution) / rel)
        if src.exists():
            dst = resolve_inside(root, rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            copied.append(rel)
    return f"mock: applied reference solution to {copied}"


def _mock_architect(request: AgentRequest, attempt: int) -> str:
    steps = "\n".join(f"{i}. UPDATE {p}: implement the spec tasks" for i, p in enumerate(request.editable, 1))
    return f"# Plan (mock)\n\n{steps or '1. No editable files given'}\n"


def _mock_evaluator(request: AgentRequest, attempt: int) -> str:
    passed = "Exit code: 0\n" in request.prompt
    return json.dumps({"success": passed, "feedback": None if passed else "mock judge: execution failed"})


def _mock_writer(request: AgentRequest, attempt: int) -> str:
    return "- Maintenance release (mock changelog entry)"


DEFAULT_MOCK_HANDLERS: dict[Role, MockHandler] = {
    "coder": _mock_coder,
    "editor": _mock_coder,
    "architect": _mock_architect,
    "evaluator": _mock_evaluator,
    "writer": _mock_writer,
}


class MockRunner:
    """Handlers get (request, attempt) where attempt counts calls per role family (coder+editor share)."""

    def __init__(self, handlers: dict[Role, MockHandler] | None = None) -> None:
        self.handlers = {**DEFAULT_MOCK_HANDLERS, **(handlers or {})}
        self.calls: list[AgentRequest] = []

    def run(self, request: AgentRequest) -> AgentResponse:
        self.calls.append(request)
        family = EDITING_ROLES if request.role in EDITING_ROLES else {request.role}
        attempt = sum(1 for c in self.calls if c.role in family)
        output = self.handlers[request.role](request, attempt)
        structured = None
        if request.json_schema is not None:
            structured = extract_json(output)
        return AgentResponse(output=output, success=True, model=f"mock-{request.model}", structured=structured)


def get_runner() -> Runner:
    return MockRunner() if os.getenv("PAC_RUNNER", "claude") == "mock" else ClaudeRunner()
