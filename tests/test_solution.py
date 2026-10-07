from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from src.contracts import ProcurementDecision, ProcurementRequest
from src.data_access import get_request
from src.solution import analyze_request, handle_request
from tools.procurement import ProcurementTools


class SolutionAdapterTests(unittest.TestCase):
    @patch("agents.single_agent.run_single_agent")
    def test_adapter_routes_architecture_a_to_single_agent(self, run_agent):
        expected = ProcurementDecision.model_validate_json(
            Path("src/sample_output.json").read_text(encoding="utf-8")
        )
        run_agent.return_value = (expected, {})

        decision = handle_request("REQ-1001", architecture="single")

        self.assertEqual(decision, expected)
        run_agent.assert_called_once()

    def test_staged_architecture_is_not_misrepresented_as_architecture_b(self):
        with self.assertRaisesRegex(NotImplementedError, "not implemented in Phase 3"):
            handle_request("REQ-1001", architecture="staged")

    def test_missing_vendor_is_reported_once_with_other_missing_fields(self):
        request_data = get_request("REQ-1001")
        request_data.update(
            {
                "request_id": "MISSING-VENDOR",
                "vendor_name": "",
                "annual_cost_usd": None,
                "user_count": None,
                "data_access_level": "unknown",
            }
        )
        decision = analyze_request(
            ProcurementRequest.model_validate(request_data),
            tools=ProcurementTools(
                vendor_base_url="http://127.0.0.1:1",
                timeout_seconds=0.05,
                retry_backoff_seconds=0,
            ),
        )
        self.assertEqual(
            decision.missing_information,
            ["vendor", "annual cost", "user count", "data access level"],
        )
        self.assertEqual(
            len(decision.missing_information),
            len(set(decision.missing_information)),
        )


if __name__ == "__main__":
    unittest.main()
