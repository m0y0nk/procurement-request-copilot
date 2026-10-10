from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from eval.scoring import render_report, score_runs

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCH_A_TRACE = (
    ROOT / "results" / "raw" / "eval_dev_A_live_20261008T052140-c0c06f.jsonl"
)
DEFAULT_ARCH_B_TRACES = (
    ROOT / "results" / "raw" / "eval_dev_B_live_20261010T105408-c4e2a0.jsonl",
    ROOT / "results" / "raw" / "eval_dev_B_live_20261010T110325-65f821.jsonl",
    ROOT / "results" / "raw" / "eval_dev_B_live_20261010T110939-1ad22c.jsonl",
    ROOT / "results" / "raw" / "eval_dev_B_live_20261010T113447-46da3b.jsonl",
    ROOT / "results" / "raw" / "eval_dev_B_live_20261010T121522-5e21c2.jsonl",
)
DEFAULT_SUMMARY = ROOT / "results" / "dev_checkpoint_summary.json"
DEFAULT_REPORT = ROOT / "results" / "dev_checkpoint_report.md"


def _read_traces(path: Path, architecture: str) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            trace = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON trace") from exc
        if not isinstance(trace, dict):
            raise ValueError(f"{path}:{line_number}: trace must be a JSON object")
        if trace.get("architecture") != architecture or trace.get("split") != "dev":
            raise ValueError(
                f"{path}:{line_number}: expected architecture {architecture} "
                "and split dev"
            )
        traces.append(trace)
    if not traces:
        raise ValueError(f"No evaluation traces found in {path}")
    return traces


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def _merge_traces(paths: tuple[Path, ...], architecture: str) -> list[dict[str, Any]]:
    latest: dict[tuple[str, str, int], dict[str, Any]] = {}
    for path in paths:
        for trace in _read_traces(path, architecture):
            key = (
                str(trace.get("case_id")),
                str(trace.get("architecture")),
                int(trace.get("repeat", 1)),
            )
            latest[key] = trace
    return list(latest.values())


def build_checkpoint(
    arch_a_path: Path = DEFAULT_ARCH_A_TRACE,
    arch_b_paths: tuple[Path, ...] = DEFAULT_ARCH_B_TRACES,
) -> tuple[dict[str, Any], str]:
    architecture_traces = {
        "A": _read_traces(arch_a_path, "A"),
        "B": _merge_traces(arch_b_paths, "B"),
    }
    case_ids = {
        architecture: {str(trace.get("case_id")) for trace in rows}
        for architecture, rows in architecture_traces.items()
    }
    if case_ids["A"] != case_ids["B"]:
        raise ValueError(
            "Architecture A and B trace case IDs differ: "
            f"A-only={sorted(case_ids['A'] - case_ids['B'])}, "
            f"B-only={sorted(case_ids['B'] - case_ids['A'])}"
        )
    traces = [*architecture_traces["A"], *architecture_traces["B"]]
    measured_tokens: dict[str, int] = {}
    missing_usage_rows: dict[str, int] = {}
    for architecture, rows in architecture_traces.items():
        usage = [row.get("token_usage") for row in rows]
        measured_tokens[architecture] = sum(
            item["total_tokens"]
            for item in usage
            if isinstance(item, dict) and isinstance(item.get("total_tokens"), int)
        )
        missing_usage_rows[architecture] = sum(
            not isinstance(item, dict)
            or not isinstance(item.get("total_tokens"), int)
            for item in usage
        )
    metrics = score_runs(traces)
    b_execution_failures = [
        str(trace["case_id"])
        for trace in architecture_traces["B"]
        if trace.get("failure_detail")
        or trace.get("error")
        or (trace.get("decision") or {}).get("failure_detail")
        or any(
            flag.get("code") == "agent_failed_closed"
            for flag in (trace.get("decision") or {}).get("risk_flags", [])
            if isinstance(flag, dict)
        )
    ]
    for architecture, total in measured_tokens.items():
        metrics[architecture]["measured_tokens"] = total
        metrics[architecture]["missing_usage_rows"] = missing_usage_rows[architecture]
    models = {"A": "openai/gpt-oss-120b", "B": "openai/gpt-oss-120b"}
    summary = {
        "scope": (
            "A and B each have 22 dev rows on GPT-OSS 120B. Holdout has not "
            "been run."
        ),
        "traces": {
            "A": _display_path(arch_a_path),
            "B": [_display_path(path) for path in arch_b_paths],
        },
        "models": models,
        "summary": metrics,
    }
    report = render_report(
        summary["summary"],
        split="dev",
        mode="live (A and B GPT-OSS 120B)",
    )
    report = report.replace(
        "## Per category",
        (
            "## Measured token totals\n\n"
            f"| Architecture | Traces | Provider-reported tokens |\n"
            f"|---|---:|---:|\n"
            f"| A | {metrics['A']['runs']} | {measured_tokens['A']:,} |\n"
            f"| B | {metrics['B']['runs']} | {measured_tokens['B']:,} |\n\n"
            "One B row has no per-case token usage in its trace; the B total "
            "is a trace-reported subtotal.\n\n"
            "## Per category"
        ),
        1,
    )
    report = report.replace(
        "## Overall",
        (
            "## Scope\n\n"
            "Both architectures have one row for each of the same 22 dev "
            "cases and used GPT-OSS 120B. B has "
            f"{metrics['B']['execution_failures']} agent execution failures "
            "where the deterministic fallback was retained; those are listed "
            "below and are not model-generated successes. No holdout run was "
            "performed. The injection category is absent from dev, so the "
            "displayed injection-resistance values are not evidence about "
            "injection cases.\n\n"
            "## Overall"
        ),
        1,
    )
    report = report.replace(
        "## Failure analysis\n\n"
        "See the per-case trace records in `results/raw/`. Interpret this section from the actual traces before packaging results.",
        (
            "## Failure analysis\n\n"
            "A's only recommendation mismatch is C-003; the model requested "
            "more information even though the code found no missing required "
            "fields. B execution failures: "
            + ", ".join(b_execution_failures)
            + ". The scorer lists failed rows even when a deterministic "
            "fallback matches a case label."
        ),
        1,
    )
    return summary, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate an offline report from committed dev traces."
    )
    parser.add_argument("--arch-a", type=Path, default=DEFAULT_ARCH_A_TRACE)
    parser.add_argument(
        "--arch-b",
        type=Path,
        action="append",
        default=None,
        help="B trace file; may be repeated to merge checkpoint files.",
    )
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)

    summary, report = build_checkpoint(
        args.arch_a,
        tuple(args.arch_b) if args.arch_b else DEFAULT_ARCH_B_TRACES,
    )
    args.summary.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.report.write_text(report, encoding="utf-8")
    canonical_summary_path = ROOT / "results" / "summary.json"
    canonical_report_path = ROOT / "results" / "report.md"
    canonical_summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    canonical_report_path.write_text(report, encoding="utf-8")
    print(f"Summary: {args.summary}")
    print(f"Report: {args.report}")
    print(f"Evaluation summary: {canonical_summary_path}")
    print(f"Evaluation report: {canonical_report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
