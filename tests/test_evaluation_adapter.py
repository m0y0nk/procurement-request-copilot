from __future__ import annotations

import unittest

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

    def test_architecture_b_is_not_claimed_before_phase_four(self):
        case = load_cases()[0]
        with self.assertRaisesRegex(ValueError, "not implemented in Phase 3"):
            run_case(case, "B", "replay")


if __name__ == "__main__":
    unittest.main()
