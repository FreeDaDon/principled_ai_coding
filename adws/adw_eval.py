#!/usr/bin/env -S uv run
"""ADW: measure the Director on the worked examples, so pass rate, iterations and cost are numbers, not claims.

Each example runs on a fresh temp copy. On a live runner the reference solution is deleted from the copy first
(a live coder could read it otherwise); the mock runner keeps it, since copying it is the mock's whole job. One
EvalRecord per example is appended to evals/results.jsonl, and a summary line is printed.

Usage:
  PAC_RUNNER=mock uv run adws/adw_eval.py                         # $0 wiring check
  uv run adws/adw_eval.py --budget-usd 2 --sandbox bwrap          # real Claude calls, about $2 per example cap
  uv run adws/adw_eval.py --examples software iam --coder-model opus
Exit 0 when every example passed, 1 otherwise.
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from adws.adw_modules.state import project_root
from core.llm import MockRunner, Runner, get_runner
from core.types import EvalRecord, Sandbox
from director_loop.engine import Director, load_config

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"
EXAMPLES = sorted(p.parent.name for p in EXAMPLES_DIR.glob("*/director.yaml"))


def eval_example(name: str, runner: Runner, budget_usd: float, coder_model: str | None, sandbox: Sandbox) -> EvalRecord:
    live = not isinstance(runner, MockRunner)
    with tempfile.TemporaryDirectory(prefix=f"pac-eval-{name}-") as tmp:
        root = Path(tmp) / name
        shutil.copytree(EXAMPLES_DIR / name, root, ignore=shutil.ignore_patterns("__pycache__"))
        config = load_config(root / "director.yaml")
        update: dict[str, object] = {"budget_usd": budget_usd, "sandbox": sandbox}
        if coder_model:
            update["coder_model"] = coder_model
        if live and config.mock_solution:
            shutil.rmtree(root / config.mock_solution)
            update["mock_solution"] = None
        config = config.model_copy(update=update)
        result = Director(config, root, runner=runner).direct()
    return EvalRecord(example=name, runner="claude" if live else "mock", coder_model=config.coder_model,
                      success=result.success, stop_reason=result.stop_reason, iterations=result.iterations,
                      cost_usd=round(result.usage.cost_usd, 4), at=datetime.now(UTC).isoformat())


def run_eval(
    examples: list[str], out: Path, budget_usd: float = 2.0, coder_model: str | None = None,
    sandbox: Sandbox = "none", runner: Runner | None = None,
) -> list[EvalRecord]:
    out.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for name in examples:
        record = eval_example(name, runner or get_runner(), budget_usd, coder_model, sandbox)
        with out.open("a") as f:
            f.write(record.model_dump_json() + "\n")
        print(f"  {'PASS' if record.success else 'FAIL'}  {name:<10} {record.stop_reason:<14} "
              f"iterations={record.iterations} cost=${record.cost_usd:.4f}")
        records.append(record)
    return records


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the Director over the examples and log pass rate and cost.")
    ap.add_argument("--examples", nargs="*", choices=EXAMPLES, default=EXAMPLES)
    ap.add_argument("--budget-usd", type=float, default=2.0, help="cap per example")
    ap.add_argument("--coder-model")
    ap.add_argument("--sandbox", choices=["none", "bwrap"], default="none")
    ap.add_argument("--out", type=Path, default=project_root() / "evals" / "results.jsonl")
    a = ap.parse_args(argv)
    records = run_eval(a.examples, a.out, a.budget_usd, a.coder_model, a.sandbox)
    passed = sum(r.success for r in records)
    print(f"{passed}/{len(records)} passed; mean iterations "
          f"{sum(r.iterations for r in records) / len(records):.1f}; total cost ${sum(r.cost_usd for r in records):.4f}; "
          f"log {a.out}")
    return 0 if passed == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
