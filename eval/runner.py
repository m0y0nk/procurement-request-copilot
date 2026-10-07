from __future__ import annotations

import argparse
import csv
from importlib import import_module
import json
from math import ceil
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Literal
from uuid import uuid4

from dotenv import load_dotenv

from eval.case_models import EvaluationCase, load_cases
from eval.scoring import render_report, score_runs
from src.contracts import ArchitectureLabel
from src.llm import LLMRunAborted, reset_live_run_state
from rules.evaluation import ProcurementFacts, evaluate_procurement_rules

ROOT = Path(__file__).resolve().parents[1]
RAW_RESULTS = ROOT / "results" / "raw"
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


def _is_failed_row(row: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return True
    if row.get("failure_detail") or row.get("error"):
        return True
    if row.get("status") in {"failed", "error", "unavailable"}:
        return True
    decision = row.get("decision")
    if isinstance(decision, dict):
        if decision.get("failure_detail") or decision.get("error"):
            return True
        risk_flags = decision.get("risk_flags")
        if isinstance(risk_flags, list):
            for flag in risk_flags:
                if isinstance(flag, dict) and flag.get("code") == "agent_failed_closed":
                    return True
    return False


def _completed_keys(path: Path) -> set[tuple[str, str, int]]:
    if not path.exists():
        return set()
    complete: set[tuple[str, str, int]] = set()
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    offset = 0
    for line_number, line in enumerate(lines, start=1):
        line_start = offset
        offset += len(line)
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            key = (
                str(row["case_id"]),
                str(row["architecture"]),
                int(row["repeat"]),
            )
            if _is_failed_row(row):
                complete.discard(key)
            else:
                complete.add(key)
            if line_number == len(lines) and not line.endswith(b"\n"):
                with path.open("ab") as output:
                    output.write(b"\n")
                    output.flush()
                    os.fsync(output.fileno())
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            if line_number == len(lines) and not line.endswith(b"\n"):
                with path.open("r+b") as output:
                    output.truncate(line_start)
                break
            raise ValueError(
                f"Invalid checkpoint at {path}:{line_number}: {exc}"
            ) from exc
    return complete


def _append_result(path: Path, trace: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(trace, sort_keys=True, ensure_ascii=True) + "\n")
        output.flush()
        os.fsync(output.fileno())


def _load_results(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    latest: dict[tuple[str, str, int], dict[str, Any]] = {}
    ordered_keys: list[tuple[str, str, int]] = []
    with path.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            item = json.loads(line)
            key = (
                str(item.get("case_id")),
                str(item.get("architecture")),
                int(item.get("repeat", 1)),
            )
            if key not in latest:
                ordered_keys.append(key)
            latest[key] = item
    return [latest[k] for k in ordered_keys]


def dry_run_projection(
    cases: list[EvaluationCase],
    architectures: tuple[ArchitectureLabel, ...],
    *,
    repeats: int = 1,
    sample_size: int = 8,
) -> dict[str, dict[str, int | float]]:
    from agents.single_agent import _tool_schemas, build_initial_prompt
    from agents.staged_agent import (
        ANALYST_SYSTEM_PROMPT,
        EvidencePack,
        build_reviewer_prompt,
    )

    if repeats < 1 or sample_size < 1:
        raise ValueError("repeats and sample_size must be positive.")
    projected: dict[str, dict[str, int | float]] = {}
    for architecture in architectures:
        if architecture not in {"A", "B"}:
            raise ValueError(
                f"Dry-run prompt construction is not implemented for architecture {architecture}."
            )
        total_messages = total_calls = total_tokens = executions = 0
        sample_ids = {case.id for case in cases[:sample_size]}
        for case in cases:
            request = case.procurement_request()
            floor = _offline_rule_floor(case, request)
            untrusted_texts = [
                case.request,
                *case.fixture.additional_untrusted_texts,
            ]
            messages = build_initial_prompt(
                request,
                rule_floor=floor,
                additional_untrusted_texts=untrusted_texts,
                **(
                    {"system_prompt": ANALYST_SYSTEM_PROMPT}
                    if architecture == "B"
                    else {}
                ),
            )
            followup_messages = list(messages)
            tool_names = (
                "get_employee_and_budget",
                "search_software_catalog",
                "get_vendor_status",
                "lookup_policy",
                "get_purchase_history",
                "compute_approval_chain",
            )
            synthetic_calls = [
                {
                    "id": f"dry-run-{index}",
                    "type": "function",
                    "function": {"name": name, "arguments": "{}"},
                }
                for index, name in enumerate(tool_names, start=1)
            ]
            followup_messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": synthetic_calls,
                }
            )
            followup_messages.extend(
                {
                    "role": "tool",
                    "tool_call_id": f"dry-run-{index}",
                    "content": "<untrusted_data>"
                    + json.dumps(
                        {
                            "tool_name": name,
                            "estimated_output_tokens": 200,
                        },
                        separators=(",", ":"),
                    )
                    + "</untrusted_data>",
                }
                for index, name in enumerate(tool_names, start=1)
            )
            tool_schema_tokens = (
                len(
                    json.dumps(
                        _tool_schemas(),
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                + 3
            ) // 4
            first_call_tokens = (
                len(json.dumps(messages, separators=(",", ":"))) + 3
            ) // 4 + tool_schema_tokens
            synthetic_tool_reply_tokens = 6 * 200
            final_call_tokens = (
                len(json.dumps(followup_messages, separators=(",", ":"))) + 3
            ) // 4 + synthetic_tool_reply_tokens
            case_repeats = repeats if case.id in sample_ids else 1
            if architecture == "A":
                prompt_messages = len(messages) + len(followup_messages)
                case_calls = 2
                case_tokens = first_call_tokens + final_call_tokens
            else:
                synthetic_events = [
                    {
                        "tool_name": name,
                        "status": "success",
                        "record_refs": [f"dry-run-{index}"],
                        "output": {
                            "status": "success",
                            "data": {"estimated_output_tokens": 200},
                        },
                    }
                    for index, name in enumerate(tool_names, start=1)
                ]
                reviewer_messages = build_reviewer_prompt(
                    request,
                    rule_floor=floor,
                    evidence_pack=EvidencePack(
                        need_summary="Estimated request need.",
                        evidence_ids=[],
                        missing_information=[],
                    ),
                    tool_events=synthetic_events,
                    additional_untrusted_texts=untrusted_texts,
                )
                prompt_messages = (
                    len(messages)
                    + len(followup_messages)
                    + len(reviewer_messages)
                )
                case_calls = 3
                case_tokens = (
                    first_call_tokens
                    + final_call_tokens
                    + (len(json.dumps(reviewer_messages, separators=(",", ":"))) + 3) // 4
                )
            total_messages += prompt_messages * case_repeats
            total_calls += case_calls * case_repeats
            executions += case_repeats
            max_tokens = int(os.getenv("LLM_MAX_TOKENS", "1200"))
            total_tokens += (
                case_tokens + case_calls * max_tokens
            ) * case_repeats
        tokens_per_minute = int(os.getenv("LLM_TOKENS_PER_MINUTE", "8000"))
        requests_per_minute = int(os.getenv("LLM_REQUESTS_PER_MINUTE", "30"))
        daily_token_cap = int(os.getenv("LLM_MAX_TOKENS_PER_DAY", "200000"))
        average_tokens_per_call = total_tokens / total_calls if total_calls else 0
        derived_minimum_gap = max(
            60 / requests_per_minute,
            60 * average_tokens_per_call / tokens_per_minute,
        )
        projected[architecture] = {
            "cases": len(cases),
            "agent_executions": executions,
            "messages": total_messages,
            "projected_llm_calls": total_calls,
            "estimated_tokens_chars_div_4": total_tokens,
            "average_estimated_tokens_per_call": average_tokens_per_call,
            "derived_minimum_gap_seconds": ceil(derived_minimum_gap * 10) / 10,
            "projected_utc_days_at_daily_cap": ceil(
                total_tokens / daily_token_cap
            ),
        }
    return projected


def _csv_rows(filename: str) -> list[dict[str, str]]:
    with (ROOT / "data" / filename).open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def _offline_rule_floor(case: EvaluationCase, request: Any) -> str:
    employees = {row["employee_id"]: row for row in _csv_rows("employees.csv")}
    employee = employees.get(request.requester_id)
    budgets = {
        row["department"]: int(row["available_usd"])
        for row in _csv_rows("department_budgets.csv")
    }
    available_budget = budgets.get(employee["department"]) if employee else None
    registry = next(
        (
            row
            for row in _csv_rows("vendors.csv")
            if row["vendor_name"].casefold() == request.vendor_name.casefold()
        ),
        None,
    )
    vendor_records = json.loads(
        (ROOT / "data" / "vendor_risk.json").read_text(encoding="utf-8")
    )
    vendor = vendor_records.get(request.vendor_name)
    unavailable = (
        case.fixture.vendor_service_unavailable
        or registry is None
        or vendor is None
    )
    missing = [
        label
        for label, value in (
            ("vendor", request.vendor_name),
            ("annual cost", request.annual_cost_usd),
            ("user count", request.user_count),
            ("business purpose", request.business_justification),
            (
                "data access level",
                request.data_access_level
                if request.data_access_level != "unknown"
                else None,
            ),
        )
        if value is None or value == ""
    ]
    service_status = vendor.get("security_review_status") if vendor else None
    service_date = vendor.get("last_review_date") if vendor else None
    normalized_registry_status = (
        "not completed"
        if registry and registry["security_status"].casefold() == "pending"
        else registry["security_status"].casefold()
        if registry
        else ""
    )
    conflict = bool(
        registry
        and vendor
        and (
            normalized_registry_status
            != str(service_status).replace("_", " ").casefold()
            or registry["security_review_date"] != (service_date or "")
        )
    )
    assessment = evaluate_procurement_rules(
        ProcurementFacts(
            annual_cost_usd=request.annual_cost_usd,
            available_budget_usd=available_budget,
            missing_information=tuple(missing),
            data_access_level=request.data_access_level,
            security_review_status=service_status,
            security_review_date=(
                datetime.fromisoformat(service_date).date() if service_date else None
            ),
            conflicting_vendor_evidence=conflict,
            vendor_risk_unavailable=unavailable,
            vendor_is_new=bool(
                registry
                and registry["procurement_status"].casefold() == "new"
            ),
            legal_terms_status=registry["legal_terms_status"] if registry else None,
            stores_data_outside_region=(
                vendor.get("stores_data_outside_region") if vendor else None
            ),
            processes_personal_data=(
                vendor.get("processes_personal_data") if vendor else None
            ),
        )
    )
    return assessment.rule_floor


def _raw_path(
    split: Split,
    architecture: ArchitectureLabel,
    mode: Mode,
    *,
    fresh: bool,
) -> Path:
    base = RAW_RESULTS / f"eval_{split}_{architecture}_{mode}"
    if fresh:
        return base.with_name(
            f"{base.name}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:6]}.jsonl"
        )
    return base.with_suffix(".jsonl")


def _selected_cases(
    cases: list[EvaluationCase],
    *,
    split: Split,
    case_ids: list[str] | None,
    limit: int | None,
) -> list[EvaluationCase]:
    selected = [case for case in cases if split == "all" or case.split == split]
    if case_ids:
        available_ids = {case.id for case in selected}
        unknown = set(case_ids) - available_ids
        if unknown:
            raise ValueError(
                f"Cases not found in selected split {split}: {', '.join(sorted(unknown))}"
            )
        selected = [case for case in selected if case.id in set(case_ids)]
    if limit is not None:
        if limit < 1:
            raise ValueError("--limit must be positive.")
        selected = selected[:limit]
    return selected


def run_resumable_cases(
    cases: list[EvaluationCase],
    *,
    executor: CaseExecutor,
    architecture: ArchitectureLabel,
    mode: Mode,
    repeats: int,
    raw_path: Path,
    resume: bool = True,
    sample_size: int = 8,
    case_delay_seconds: float = 3,
) -> list[dict[str, Any]]:
    if repeats < 1:
        raise ValueError("repeats must be positive.")
    if sample_size < 1:
        raise ValueError("sample_size must be positive.")
    if case_delay_seconds < 0:
        raise ValueError("case_delay_seconds cannot be negative.")
    completed = _completed_keys(raw_path) if resume else set()
    sample_ids = {case.id for case in cases[:sample_size]}
    prior_case_id: str | None = None
    for case in cases:
        case_repeats = repeats if case.id in sample_ids else 1
        for repeat in range(1, case_repeats + 1):
            key = (case.id, architecture, repeat)
            if key in completed:
                prior_case_id = case.id
                continue
            if mode == "live" and prior_case_id is not None and case_delay_seconds:
                if prior_case_id != case.id:
                    time.sleep(case_delay_seconds)
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
            trace = {
                **execution,
                "case_id": case.id,
                "split": case.split,
                "category": case.category,
                "architecture": architecture,
                "repeat": repeat,
                "mode": mode,
                "expected": case.expected.model_dump(mode="json"),
            }
            _append_result(raw_path, trace)
            if not _is_failed_row(trace):
                completed.add(key)
            else:
                completed.discard(key)
            prior_case_id = case.id
    return _load_results(raw_path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run procurement architecture evaluations.")
    parser.add_argument("--split", choices=("dev", "holdout", "all"), default="all")
    parser.add_argument("--arch", choices=("A", "B", "both"), default="both")
    parser.add_argument("--mode", choices=("live", "replay"), default="replay")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--cases", help="Comma-separated case IDs.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--validate-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    load_dotenv(ROOT / ".env", override=False)
    cases = load_cases()
    case_ids = [value.strip() for value in args.cases.split(",") if value.strip()] if args.cases else None
    selected_cases = _selected_cases(
        cases,
        split=args.split,
        case_ids=case_ids,
        limit=args.limit,
    )
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
    if args.repeats < 1:
        raise ValueError("--repeats must be positive.")
    if args.dry_run:
        repeat_sample = int(os.getenv("LLM_REPEAT_SAMPLE", "8"))
        projection = dry_run_projection(
            selected_cases,
            architectures,
            repeats=args.repeats,
            sample_size=repeat_sample,
        )
        print(
            "Dry-run only. No HTTP calls were made. Token values are estimates "
            "from serialized characters divided by four; projected completion "
            "allowance uses LLM_MAX_TOKENS."
        )
        for architecture, estimate in projection.items():
            print(
                f"Architecture {architecture}: {estimate['cases']} cases, "
                f"{estimate['agent_executions']} agent executions, "
                f"{estimate['messages']} prompt messages, "
                f"{estimate['projected_llm_calls']} projected LLM calls, "
                f"{estimate['estimated_tokens_chars_div_4']} estimated tokens, "
                f"{estimate['average_estimated_tokens_per_call']:.1f} estimated "
                f"tokens/call, {estimate['derived_minimum_gap_seconds']:.1f}s "
                f"derived minimum gap, and {estimate['projected_utc_days_at_daily_cap']} "
                "UTC day(s) at the configured daily token cap."
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

    if args.no_cache:
        os.environ["LLM_NO_CACHE"] = "1"
    elif "LLM_NO_CACHE" in os.environ:
        del os.environ["LLM_NO_CACHE"]
    if args.mode == "live":
        try:
            reset_live_run_state()
        except LLMRunAborted as exc:
            print(f"Live run refused: {exc}", file=sys.stderr)
            return 3

    all_traces: list[dict[str, Any]] = []
    raw_paths: list[Path] = []
    repeat_sample = int(os.getenv("LLM_REPEAT_SAMPLE", "8"))
    for architecture in architectures:
        raw_path = _raw_path(
            args.split,
            architecture,
            args.mode,
            fresh=args.fresh,
        )
        raw_paths.append(raw_path)
        try:
            traces = run_resumable_cases(
                selected_cases,
                executor=run_case,
                architecture=architecture,
                mode=args.mode,
                repeats=args.repeats,
                raw_path=raw_path,
                resume=args.resume and not args.fresh,
                sample_size=repeat_sample,
                case_delay_seconds=float(
                    os.getenv("EVAL_CASE_DELAY_SECONDS", "3")
                ),
            )
        except LLMRunAborted as exc:
            print(f"Live evaluation stopped: {exc}", file=sys.stderr)
            print(f"Completed progress is saved in {raw_path}.", file=sys.stderr)
            return 4
        all_traces.extend(traces)
    summary = score_runs(all_traces)
    generated_at = datetime.now(UTC)
    summary_data = {
        "experiment_id": generated_at.strftime("%Y%m%dT%H%M%SZ"),
        "generated_at": generated_at.isoformat(),
        "split": args.split,
        "mode": args.mode,
        "summary": summary,
    }
    results_dir = ROOT / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    summary_path = results_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary_data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path = results_dir / "report.md"
    report_path.write_text(
        render_report(summary, split=args.split, mode=args.mode),
        encoding="utf-8",
    )
    print(f"Raw traces: {', '.join(str(path) for path in raw_paths)}")
    print(f"Summary: {summary_path}")
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
