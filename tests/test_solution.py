from __future__ import annotations

import unittest

from src.contracts import ProcurementDecision, ProcurementRequest
from src.data_access import get_request
from src.solution import analyze_request, handle_request
from tools.procurement import ProcurementTools


class SolutionAdapterTests(unittest.TestCase):
    def test_adapter_returns_decision_for_each_architecture(self):
        for architecture in ("single", "staged"):
            with self.subTest(architecture=architecture):
                decision = handle_request("REQ-1001", architecture=architecture)
                self.assertIsInstance(decision, ProcurementDecision)
                self.assertTrue(decision.human_review_required)

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
