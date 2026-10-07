from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from src.contracts import ProcurementDecision
from agents.evaluation import run_case
from eval.case_models import load_cases


class EvaluationAdapterTests(unittest.TestCase):
    def test_architecture_a_trace_honors_vendor_outage_fixture(self):
        case = next(
            case for case in load_cases() if case.fixture.vendor_service_unavailable
        )

        trace = run_case(case, "A", "replay")

        self.assertEqual(trace["case_id"], case.id)
        self.assertEqual(len(trace["tool_calls"]), 6)
        vendor_call = next(
            call
            for call in trace["tool_calls"]
            if call["tool_name"] == "get_vendor_status"
        )
        self.assertEqual(vendor_call["status"], "unavailable")
        self.assertIn(
            "agent_failed_closed",
            {flag["code"] for flag in trace["decision"]["risk_flags"]},
        )

    @patch("agents.staged_agent.run_staged_agent")
    def test_architecture_b_routes_to_staged_agent(self, run_agent):
        case = load_cases()[0]
        decision = ProcurementDecision.model_validate_json(
            Path("src/sample_output.json").read_text(encoding="utf-8")
        )
        run_agent.return_value = (
            decision,
            {"architecture_stages": ["analyst", "reviewer"]},
        )

        trace = run_case(case, "B", "replay")

        self.assertEqual(trace["architecture_stages"], ["analyst", "reviewer"])
        run_agent.assert_called_once()
        self.assertEqual(run_agent.call_args.kwargs["mode"], "replay")


if __name__ == "__main__":
    unittest.main()
