"""Pack/tool registry, input auto-detection, and the `python -m core.packs.registry` CLI.

Deterministic: no network, no LLM, nothing from the input is executed. Every report leaves `run_pack`
scrubbed (secrets redacted, control characters stripped, strings capped), whatever the analyzer did.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import yaml

from core.packs.export import render_reports as to_markdown
from core.packs.export import to_json
from core.packs.gcp_sre import logs as sre_logs
from core.packs.gcp_sre import nodetrace, tfgcp
from core.packs.inputs import iter_files, load_structured
from core.packs.mcp_gov import injection, manifest
from core.security import snippet
from core.types import SEVERITY_ORDER, AnalysisReport, Finding

SCRUB_MAX_CHARS = 2_000


class Analyzer(Protocol):
    def __call__(self, path: Path, **opts: Any) -> AnalysisReport: ...


class UnknownInputError(ValueError):
    pass


PACK_TOOLS: dict[str, dict[str, Analyzer]] = {
    "mcp_gov": {"mcp_manifest": manifest.analyze_file, "connector_scan": injection.analyze_file},
    "gcp_sre": {"gcp_tf": tfgcp.analyze_file, "sre_logs": sre_logs.analyze_file, "node_trace": nodetrace.analyze_file},
}
# Extra tools that also run (when no --tool is given) on a file another tool was auto-detected for.
COMPANIONS: dict[tuple[str, str], tuple[tuple[str, Callable[[Path], bool]], ...]] = {
    ("gcp_sre", "sre_logs"): (("node_trace", nodetrace.looks_like_node_trace),),
}
# Tools that consume the same input kind as another (auto-detected) tool.
INPUT_KIND = {"node_trace": "sre_logs"}
TEXT_SUFFIXES = frozenset({".md", ".txt", ".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".bash", ".json", ".yml", ".yaml",
                           ".toml", ".ps1", ".rb", ".go", ".html", ".cfg", ".ini"})
TEXT_NAMES = frozenset({"SKILL", "SKILL.MD", "DOCKERFILE"})


def _load(path: Path) -> Any:
    """Parsed JSON/YAML content, or None when unparseable or too large."""
    try:
        return load_structured(path)
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError):
        return None


def _detect_mcp_gov(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in {".json", ".yml", ".yaml"} and manifest.looks_like_manifest(_load(path)):
        return "mcp_manifest"
    if suffix in TEXT_SUFFIXES or path.name.upper() in TEXT_NAMES:
        return "connector_scan"
    return None


def _detect_gcp_sre(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix == ".json" and tfgcp.looks_like_terraform_json(_load(path)):
        return "gcp_tf"
    if suffix in {".json", ".jsonl", ".ndjson", ".csv", ".log", ".txt"}:
        return "sre_logs" if sre_logs.looks_like_log(path) or nodetrace.looks_like_node_trace(path) else None
    return None


DETECTORS: dict[str, Callable[[Path], str | None]] = {"mcp_gov": _detect_mcp_gov, "gcp_sre": _detect_gcp_sre}


def detect_tool(pack: str, path: Path) -> str:
    """Pick the tool for an input by filename and content; raise UnknownInputError if nothing fits."""
    path = Path(path)
    if pack not in PACK_TOOLS:
        raise ValueError(f"unknown pack {pack!r}; expected one of {sorted(PACK_TOOLS)}")
    if path.is_dir():
        raise UnknownInputError(f"{path} is a directory; use run_pack to analyze every file in it")
    tool = DETECTORS[pack](path)
    if tool is None:
        raise UnknownInputError(f"cannot detect a {pack} tool for {path}")
    return tool


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return snippet(value, SCRUB_MAX_CHARS)
    if isinstance(value, dict):
        return {_scrub(k) if isinstance(k, str) else k: _scrub(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(v) for v in value]
    return value


def scrub_report(report: AnalysisReport) -> AnalysisReport:
    """Enforce the untrusted-text invariant on every string in a report, including metrics and summary."""
    return AnalysisReport.model_validate(_scrub(report.model_dump()))


def _input_error(pack: str, tool: str, path: Path, exc: Exception) -> AnalysisReport:
    return AnalysisReport(
        pack=pack, tool=tool, input=str(path), summary="input could not be analyzed",  # type: ignore[arg-type]
        findings=[Finding(rule_id="INPUT-ERROR", title=f"Could not analyze input: {type(exc).__name__}",
                          severity="low", category="input", resource=str(path), location=str(path),
                          evidence={"error": str(exc)[:500]}, recommendation="Check the file format.")],
    )


def _companions(pack: str, chosen: str, path: Path, explicit_tool: str | None, opts: dict[str, Any]) -> list[AnalysisReport]:
    if explicit_tool is not None:
        return []
    return [PACK_TOOLS[pack][name](path, **opts) for name, applies in COMPANIONS.get((pack, chosen), ()) if applies(path)]


def run_pack(pack: str, input_path: Path, tool: str | None = None, **opts: Any) -> list[AnalysisReport]:
    """Run one tool (given or detected) on a file, or every recognizable file of a directory."""
    input_path = Path(input_path)
    if pack not in PACK_TOOLS:
        raise ValueError(f"unknown pack {pack!r}; expected one of {sorted(PACK_TOOLS)}")
    if tool is not None and tool not in PACK_TOOLS[pack]:
        raise ValueError(f"unknown tool {tool!r} for pack {pack}; expected one of {sorted(PACK_TOOLS[pack])}")
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    if not input_path.is_dir():
        chosen = tool or detect_tool(pack, input_path)
        return [scrub_report(r) for r in
                [PACK_TOOLS[pack][chosen](input_path, **opts), *_companions(pack, chosen, input_path, tool, opts)]]

    reports: list[AnalysisReport] = []
    for file in iter_files(input_path):
        try:
            detected = detect_tool(pack, file)
        except UnknownInputError:
            continue
        if tool is not None and INPUT_KIND.get(tool, tool) != detected:
            continue
        chosen = tool or detected
        try:
            reports.append(PACK_TOOLS[pack][chosen](file, **opts))
            reports.extend(_companions(pack, chosen, file, tool, opts))
        except (ValueError, KeyError, TypeError) as exc:
            reports.append(_input_error(pack, chosen, file, exc))
    return [scrub_report(r) for r in reports]


def _coerce(value: str) -> Any:
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    return {"true": True, "false": False}.get(value.lower(), value)


def parse_opts(pairs: list[str]) -> dict[str, Any]:
    opts: dict[str, Any] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise argparse.ArgumentTypeError(f"--opt expects key=value, got {pair!r}")
        opts[key.replace("-", "_")] = _coerce(value)
    return opts


def render(reports: list[AnalysisReport], fmt: str) -> str:
    return to_json(reports) if fmt == "json" else to_markdown(reports)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.packs.registry", description="Run deterministic domain tools.")
    parser.add_argument("pack", choices=sorted(PACK_TOOLS))
    parser.add_argument("path", type=Path)
    parser.add_argument("--tool", help="tool name (default: auto-detect)")
    parser.add_argument("--format", choices=["md", "json"], default="md")
    parser.add_argument("--out", type=Path, help="write output to FILE instead of stdout")
    parser.add_argument("--fail-on", choices=sorted(SEVERITY_ORDER, key=SEVERITY_ORDER.__getitem__),
                        help="exit 2 if any finding is at or above this severity")
    parser.add_argument("--opt", action="append", default=[], metavar="KEY=VALUE",
                        help="tool option, e.g. --opt allowed_scopes=docs.read --opt lag_threshold=5000")
    args = parser.parse_args(argv)

    try:
        reports = run_pack(args.pack, args.path, args.tool, **parse_opts(args.opt))
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    output = render(reports, args.format)
    if args.out:
        args.out.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output if output.endswith("\n") else output + "\n")
    if args.fail_on and any(r.blocking(args.fail_on) for r in reports):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
