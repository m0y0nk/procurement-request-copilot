from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import requests

from tools.procurement import ProcurementTools


class ProcurementToolTests(unittest.TestCase):
    def tools(self) -> ProcurementTools:
        return ProcurementTools(retry_backoff_seconds=0)

    @staticmethod
    def response(payload: dict, status: int = 200) -> Mock:
        response = Mock()
        response.status_code = status
        response.json.return_value = payload
        if status >= 400:
            response.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status}")
        return response

    def test_employee_budget_returns_integer_usd(self):
        tools = self.tools()
        result = tools.get_employee_and_budget("E001")

        self.assertEqual(result.status, "success")
        self.assertEqual(result.data.available_usd, 15000)
        self.assertEqual(result.data.department, "Marketing")
        self.assertEqual(result.data.currency, "USD")
        self.assertEqual(tools.calls[0].tool_call_id, result.tool_call_id)

    def test_catalog_lookup_returns_exact_existing_tool(self):
        tools = self.tools()
        result = tools.search_software_catalog(
            product_name="TaskFlow Pro",
            vendor_name="TaskFlow",
            category="Project Management",
        )

        self.assertEqual(result.status, "success")
        self.assertIn("SW003", [item.software_id for item in result.data.matches])
        self.assertIn("SW003", tools.calls[0].record_refs)

    @patch("tools.procurement.requests.get")
    def test_vendor_assessment_freshness_and_conflict(self, get):
        get.return_value = self.response(
            {
                "security_review_status": "expired",
                "last_review_date": "2025-07-01",
                "risk_level": "medium",
                "processes_personal_data": False,
                "stores_data_outside_region": False,
                "notes": "Reassessment required.",
            }
        )
        tools = self.tools()

        result = tools.get_vendor_status("SignalWatch")

        self.assertEqual(result.status, "success")
        self.assertEqual(result.data.assessment_age_days, 456)
        self.assertFalse(result.data.assessment_current)
        self.assertTrue(result.data.conflicting_evidence)
        self.assertEqual(tools.calls[0].record_refs, ["SignalWatch"])

    @patch("tools.procurement.requests.get")
    def test_pending_and_not_completed_are_equivalent_statuses(self, get):
        get.return_value = self.response(
            {
                "security_review_status": "not_completed",
                "last_review_date": None,
                "risk_level": "medium",
                "processes_personal_data": True,
                "stores_data_outside_region": False,
                "notes": "Onboarding incomplete.",
            }
        )

        result = self.tools().get_vendor_status("BrandBoard")

        self.assertEqual(result.status, "success")
        self.assertFalse(result.data.conflicting_evidence)

    @patch("tools.procurement.requests.get")
    def test_vendor_service_failure_retries_then_is_unavailable(self, get):
        get.side_effect = requests.Timeout("timed out")
        tools = self.tools()

        result = tools.get_vendor_status("PixelCraft")

        self.assertEqual(get.call_count, 2)
        self.assertEqual(result.status, "unavailable")
        self.assertIn("retry", result.reason)
        self.assertEqual(tools.calls[0].status, "unavailable")

    def test_policy_lookup_returns_rule_ids(self):
        tools = self.tools()
        result = tools.lookup_policy("vendor security assessment expired")

        self.assertEqual(result.status, "success")
        self.assertIn("POL-SECURITY", [rule.rule_id for rule in result.data.rules])
        self.assertEqual(tools.calls[0].tool_call_id, result.tool_call_id)

    def test_purchase_history_filters_by_department_and_vendor(self):
        result = self.tools().get_purchase_history(
            department="Engineering",
            vendor_name="CodeMate",
            product_name="CodeMate expansion",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual([item.purchase_id for item in result.data.records], ["PO-2440"])

    @patch("tools.procurement.requests.get")
    def test_approval_chain_returns_deterministic_floor(self, get):
        get.return_value = self.response(
            {
                "security_review_status": "approved",
                "last_review_date": "2026-08-20",
                "risk_level": "medium",
                "processes_personal_data": False,
                "stores_data_outside_region": False,
                "notes": "Approved for source-code use when repository controls are enabled.",
            }
        )
        tools = self.tools()
        result = tools.compute_approval_chain("REQ-1003")

        self.assertEqual(result.status, "success")
        self.assertEqual(result.data.rule_floor, "ESCALATE_SECURITY")
        self.assertIn(
            "Security",
            [approval.role for approval in result.data.approvals_required],
        )
        self.assertEqual(
            [call.tool_name for call in tools.calls],
            ["get_vendor_status", "compute_approval_chain"],
        )


if __name__ == "__main__":
    unittest.main()
