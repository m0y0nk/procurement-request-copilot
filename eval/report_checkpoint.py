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
DEFAULT_ARCH_B_TRACE = ROOT / "results" / "raw" / "eval_dev_B_live.jsonl"
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


def build_checkpoint(
    arch_a_path: Path = DEFAULT_ARCH_A_TRACE,
    arch_b_path: Path = DEFAULT_ARCH_B_TRACE,
) -> tuple[dict[str, Any], str]:
    architecture_traces = {
        "A": _read_traces(arch_a_path, "A"),
        "B": _read_traces(arch_b_path, "B"),
    }
    traces = [*architecture_traces["A"], *architecture_traces["B"]]
    measured_tokens: dict[str, int] = {}
    for architecture, rows in architecture_traces.items():
        usage = [row.get("token_usage") for row in rows]
        if any(
            not isinstance(item, dict)
            or not isinstance(item.get("total_tokens"), int)
            for item in usage
        ):
            raise ValueError(
                f"Every {architecture} trace must include measured total_tokens"
            )
        measured_tokens[architecture] = sum(
            item["total_tokens"] for item in usage if isinstance(item, dict)
        )
    metrics = score_runs(traces)
    for architecture, total in measured_tokens.items():
        metrics[architecture]["measured_tokens"] = total
    summary = {
        "scope": "Architecture A full dev live run and Architecture B partial dev live run",
        "traces": {
            "A": _display_path(arch_a_path),
            "B": _display_path(arch_b_path),
        },
        "summary": metrics,
    }
    report = render_report(
        summary["summary"],
        split="dev checkpoint",
        mode="live (A full, B partial)",
    )
    report = report.replace(
        "## Per category",
        (
            "## Measured token totals\n\n"
            f"| Architecture | Traces | Provider-reported tokens |\n"
            f"|---|---:|---:|\n"
            f"| A | {metrics['A']['runs']} | {measured_tokens['A']:,} |\n"
            f"| B | {metrics['B']['runs']} | {measured_tokens['B']:,} |\n\n"
            "## Per category"
        ),
        1,
    )
    report = report.replace(
        "## Failure analysis\n\n"
        "See the per-case trace records in `results/raw/`. Interpret this section from the actual traces before packaging results.",
        (
            "## Failure analysis\n\n"
            "Architecture A's only recommendation mismatch is C-003: the live "
            "model returned `REQUEST_MORE_INFO` although code found no missing "
            "required fields. The later deterministic guard preserves the "
            "code-computed recommendation in replay; the original live result "
            "remains a mismatch. Architecture B's four old-prompt cases "
            "returned analyst evidence identifiers outside the canonical "
            "allowlist, causing grounding failures in C-001 through C-004. "
            "The allowlist prompt fix is not represented in these live traces "
            "and has not been verified live."
        ),
        1,
    )
    report = report.replace(
        "## Overall",
        (
            "## Scope\n\n"
            "Architecture A contains the full 22-case dev run. Architecture B "
            "contains only C-001 through C-004 from the pre-allowlist prompt. "
            "The rows are not a completed head-to-head comparison. B's updated "
            "evidence-ID prompt has not been live-verified. The holdout split "
            "has not been run.\n\n"
            "## Overall"
        ),
        1,
    )
    return summary, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate an offline report from committed dev traces."
    )
    parser.add_argument("--arch-a", type=Path, default=DEFAULT_ARCH_A_TRACE)
    parser.add_argument("--arch-b", type=Path, default=DEFAULT_ARCH_B_TRACE)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)

    summary, report = build_checkpoint(args.arch_a, args.arch_b)
    args.summary.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.report.write_text(report, encoding="utf-8")
    print(f"Summary: {args.summary}")
    print(f"Report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
