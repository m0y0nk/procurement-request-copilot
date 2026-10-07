from __future__ import annotations

import argparse
from importlib import import_module
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Literal
from uuid import uuid4

from eval.case_models import EvaluationCase, load_cases
from eval.scoring import render_report, score_runs
from src.contracts import ArchitectureLabel

ROOT = Path(__file__).resolve().parents[1]
Mode = Literal["live", "replay"]
Split = Literal["dev", "holdout", "all"]
CaseExecutor = Callable[
    [EvaluationCase, ArchitectureLabel, Mode],
    dict[str, Any],
]


def run_cases(
    cases: list[EvaluationCase],
    *,
    executor: CaseExecutor,
    split: Split = "all",
    architectures: tuple[ArchitectureLabel, ...] = ("A", "B"),
    mode: Mode = "replay",
    repeats: int = 3,
) -> list[dict[str, Any]]:
    if split not in {"dev", "holdout", "all"}:
        raise ValueError(f"Unsupported evaluation split: {split!r}.")
    if not architectures or len(set(architectures)) != len(architectures):
        raise ValueError("Select one or more unique architectures.")
    if any(architecture not in {"A", "B"} for architecture in architectures):
        raise ValueError("Architectures must be A or B.")
    if mode not in {"live", "replay"}:
        raise ValueError("Evaluation mode must be 'live' or 'replay'.")
    if repeats < 1:
        raise ValueError("Evaluation repeats must be positive.")

    selected = [case for case in cases if split == "all" or case.split == split]
    traces: list[dict[str, Any]] = []
    for architecture in architectures:
        for case in selected:
            for repeat in range(1, repeats + 1):
                execution = executor(case, architecture, mode)
                if not isinstance(execution, dict):
                    raise TypeError(
                        f"{case.id} / {architecture}: executor must return a trace object."
                    )
                execution = dict(execution)
                decision = execution.get("decision")
                if hasattr(decision, "model_dump"):
                    execution["decision"] = decision.model_dump(mode="json")
                if not isinstance(execution.get("decision"), dict):
                    raise ValueError(
                        f"{case.id} / {architecture}: trace has no structured decision."
                    )
                traces.append(
                    {
                        **execution,
                        "case_id": case.id,
                        "split": case.split,
                        "category": case.category,
                        "architecture": architecture,
                        "repeat": repeat,
                        "mode": mode,
                        "expected": case.expected.model_dump(mode="json"),
                    }
                )
    return traces


def write_results(
    traces: list[dict[str, Any]],
    *,
    split: Split,
    mode: Mode,
    results_dir: Path = ROOT / "results",
) -> tuple[Path, Path, Path]:
    generated_at = datetime.now(UTC)
    experiment_id = (
        f"{generated_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    )
    raw_dir = results_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{experiment_id}.jsonl"
    raw_path.write_text(
        "".join(
            json.dumps(trace, sort_keys=True, ensure_ascii=True) + "\n"
            for trace in traces
        ),
        encoding="utf-8",
    )
    summary = {
        "experiment_id": experiment_id,
        "generated_at": generated_at.isoformat(),
        "split": split,
        "mode": mode,
        "traces": str(raw_path.relative_to(results_dir)),
        "summary": score_runs(traces),
    }
    summary_path = results_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path = results_dir / "report.md"
    report_path.write_text(
        render_report(summary["summary"], split=split, mode=mode),
        encoding="utf-8",
    )
    return raw_path, summary_path, report_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run procurement architecture evaluations.")
    parser.add_argument("--split", choices=("dev", "holdout", "all"), default="all")
    parser.add_argument("--arch", choices=("A", "B", "both"), default="both")
    parser.add_argument("--mode", choices=("live", "replay"), default="replay")
    parser.add_argument("--validate-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cases = load_cases()
    selected_cases = [
        case for case in cases if args.split == "all" or case.split == args.split
    ]
    architectures: tuple[ArchitectureLabel, ...] = (
        ("A", "B") if args.arch == "both" else (args.arch,)
    )
    if args.validate_only:
        print(
            f"Validated {len(selected_cases)} labelled cases for "
            f"split={args.split}, architectures={','.join(architectures)}. "
            "No agent was run."
        )
        return 0

    try:
        agent_module = import_module("agents.evaluation")
    except ModuleNotFoundError as exc:
        if exc.name in {"agents", "agents.evaluation"}:
            print(
                "Agent executors are not implemented yet; complete the agent phases "
                "before running evaluations.",
                file=sys.stderr,
            )
            return 2
        raise
    run_case = getattr(agent_module, "run_case", None)
    if not callable(run_case):
        print(
            "agents.evaluation must expose a callable run_case(case, architecture, mode).",
            file=sys.stderr,
        )
        return 2

    traces = run_cases(
        cases,
        executor=run_case,
        split=args.split,
        architectures=architectures,
        mode=args.mode,
    )
    raw_path, summary_path, report_path = write_results(
        traces,
        split=args.split,
        mode=args.mode,
    )
    print(f"Raw traces: {raw_path}")
    print(f"Summary: {summary_path}")
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
