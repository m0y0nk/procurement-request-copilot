from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eval.case_models import EvaluationCase, load_cases
from eval.runner import (
    _completed_keys,
    dry_run_projection,
    main,
    run_cases,
    run_resumable_cases,
    write_results,
)
from eval.scoring import score_runs


def _trace(
    case: EvaluationCase,
    architecture: str = "A",
    mode: str = "replay",
) -> dict:
    return {
        "executor_architecture": architecture,
        "executor_mode": mode,
        "decision": {
            "request_id": case.id,
            "recommendation": case.expected.recommendation,
            "approvals_required": [
                {"role": role} for role in case.expected.approvals_required_roles
            ],
            "missing_information": case.expected.missing_information,
            "risk_flags": [{"code": code} for code in case.expected.must_flag],
            "rule_floor": "RECOMMEND_APPROVAL",
            "human_review": {"required": True},
            "evidence": [
                {
                    "tool_call_id": "tool-budget",
                    "record_ref": "Finance",
                }
            ],
            "meta": {
                "llm_calls": 0,
                "tool_calls": 4,
                "latency_ms": 2.5,
            },
        },
        "tool_calls": [
            {
                "tool_call_id": "tool-budget",
                "tool_name": "get_employee_and_budget",
                "status": "success",
                "record_refs": ["Finance"],
            },
            {
                "tool_call_id": "tool-catalog",
                "tool_name": "search_software_catalog",
                "status": "success",
                "record_refs": ["SW010"],
            },
            {
                "tool_call_id": "tool-vendor",
                "tool_name": "get_vendor_status",
                "status": "success",
                "record_refs": ["SignFlow"],
            },
            {
                "tool_call_id": "tool-rules",
                "tool_name": "compute_approval_chain",
                "status": "success",
                "record_refs": ["REQ-1001"],
            },
        ],
    }


class EvaluationRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = next(case for case in load_cases() if case.id == "C-001")

    def test_runner_passes_split_architecture_mode_and_repeat_to_executor(self):
        invocations = []

        def executor(case, architecture, mode):
            invocations.append((case.id, architecture, mode))
            return _trace(case, architecture, mode)

        traces = run_cases(
            [self.case],
            executor=executor,
            split="dev",
            architectures=("A",),
            mode="replay",
            repeats=3,
        )

        self.assertEqual(
            invocations,
            [("C-001", "A", "replay")] * 3,
        )
        self.assertEqual([trace["repeat"] for trace in traces], [1, 2, 3])
        self.assertTrue(all(trace["expected"]["recommendation"] == "USE_EXISTING_TOOL" for trace in traces))

    def test_scorer_checks_recommendation_grounding_and_policy(self):
        traces = run_cases(
            [self.case],
            executor=lambda case, architecture, mode: _trace(
                case, architecture, mode
            ),
            split="dev",
            architectures=("A",),
            repeats=1,
        )

        summary = score_runs(traces)["A"]

        self.assertEqual(summary["recommendation_accuracy"], 1.0)
        self.assertEqual(summary["grounding_rate"], 1.0)
        self.assertEqual(summary["policy_compliance"], 1.0)
        self.assertEqual(summary["failed_cases"], [])

    def test_scorer_reports_mismatches(self):
        def incorrect_executor(case, architecture, mode):
            trace = _trace(case, architecture, mode)
            trace["decision"]["recommendation"] = "REQUEST_MORE_INFO"
            return trace

        traces = run_cases(
            [self.case],
            executor=incorrect_executor,
            split="dev",
            architectures=("A",),
            repeats=1,
        )

        summary = score_runs(traces)["A"]

        self.assertEqual(summary["recommendation_accuracy"], 0.0)
        self.assertEqual(summary["failed_cases"][0]["case_id"], "C-001")
        self.assertIn("recommendation", summary["failed_cases"][0]["reason"])

    def test_results_writer_creates_trace_summary_and_report(self):
        traces = run_cases(
            [self.case],
            executor=lambda case, architecture, mode: _trace(
                case, architecture, mode
            ),
            split="dev",
            architectures=("A",),
            repeats=1,
        )
        with tempfile.TemporaryDirectory() as directory:
            raw_path, summary_path, report_path = write_results(
                traces,
                split="dev",
                mode="replay",
                results_dir=Path(directory),
            )

            self.assertTrue(raw_path.is_file())
            self.assertTrue(summary_path.is_file())
            self.assertTrue(report_path.is_file())
            saved_trace = json.loads(raw_path.read_text(encoding="utf-8"))
            saved_summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_trace["case_id"], "C-001")
            self.assertEqual(saved_summary["split"], "dev")
            self.assertIn("Architecture", report_path.read_text(encoding="utf-8"))

    def test_resume_skips_a_completed_case_architecture_repeat(self):
        invocations = []

        def executor(case, architecture, mode):
            invocations.append((case.id, architecture, mode))
            return _trace(case, architecture, mode)

        with tempfile.TemporaryDirectory() as directory:
            raw_path = Path(directory) / "checkpoint.jsonl"
            run_resumable_cases(
                [self.case],
                executor=executor,
                architecture="A",
                mode="replay",
                repeats=1,
                raw_path=raw_path,
                case_delay_seconds=0,
            )
            resumed = run_resumable_cases(
                [self.case],
                executor=executor,
                architecture="A",
                mode="replay",
                repeats=1,
                raw_path=raw_path,
                case_delay_seconds=0,
            )

        self.assertEqual(invocations, [("C-001", "A", "replay")])
        self.assertEqual(len(resumed), 1)

    def test_resume_discards_only_a_truncated_final_checkpoint_line(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_path = Path(directory) / "checkpoint.jsonl"
            raw_path.write_text(
                '{"case_id":"C-001","architecture":"A","repeat":1}\n'
                '{"case_id":"C-002"',
                encoding="utf-8",
            )

            completed = _completed_keys(raw_path)

            self.assertEqual(completed, {("C-001", "A", 1)})
            self.assertEqual(
                raw_path.read_text(encoding="utf-8"),
                '{"case_id":"C-001","architecture":"A","repeat":1}\n',
            )

    @patch("tools.procurement.requests.get")
    @patch("src.llm.requests.post")
    def test_dry_run_makes_no_http_calls(self, post, get):
        projection = dry_run_projection([self.case], ("A",))

        self.assertEqual(projection["A"]["cases"], 1)
        self.assertEqual(projection["A"]["agent_executions"], 1)
        self.assertEqual(projection["A"]["projected_llm_calls"], 2)
        post.assert_not_called()
        get.assert_not_called()

    @patch("tools.procurement.requests.get")
    @patch("src.llm.requests.post")
    def test_dry_run_cli_makes_no_http_calls(self, post, get):
        with patch("eval.runner.load_cases", return_value=[self.case]):
            result = main(
                [
                    "--split",
                    "dev",
                    "--arch",
                    "A",
                    "--mode",
                    "live",
                    "--dry-run",
                    "--cases",
                    self.case.id,
                ]
            )

        self.assertEqual(result, 0)
        post.assert_not_called()
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
