from __future__ import annotations

import unittest

from pydantic import ValidationError

from src.contracts import ProcurementDecision


class ProcurementDecisionContractTests(unittest.TestCase):
    def payload(self) -> dict:
        return {
            "request_id": "REQ-TEST",
            "recommendation": "REQUEST_MORE_INFO",
            "next_step": "Employee provides the annual cost.",
            "evidence": [
                {
                    "id": "e1",
                    "claim": "The request record has no annual cost.",
                    "source_tool": "get_request",
                    "tool_call_id": "tool-1",
                    "record_ref": "REQ-TEST",
                }
            ],
            "approvals_required": [
                {
                    "role": "Manager",
                    "reason": "Minimum business approval.",
                    "rule_id": "POL-APPROVAL-1",
                }
            ],
            "missing_information": ["annual cost"],
            "risk_flags": [
                {
                    "code": "missing_information",
                    "severity": "medium",
                    "detail": "Annual cost is missing.",
                    "evidence_ids": ["e1"],
                }
            ],
            "rule_floor": "REQUEST_MORE_INFO",
            "human_review": {
                "required": True,
                "reason": "All recommendations require human review.",
            },
            "meta": {
                "architecture": "A",
                "llm_calls": 0,
                "tool_calls": 1,
                "latency_ms": 2.5,
            },
        }

    def test_contract_validates_and_keeps_public_runner_compatibility(self):
        decision = ProcurementDecision.model_validate(self.payload())

        self.assertEqual(decision.required_approvals, ["Manager"])
        self.assertTrue(decision.human_review_required)
        self.assertEqual(decision.telemetry.llm_calls, 0)
        self.assertEqual(
            set(decision.model_dump()),
            {
                "request_id",
                "recommendation",
                "next_step",
                "evidence",
                "approvals_required",
                "missing_information",
                "risk_flags",
                "rule_floor",
                "human_review",
                "meta",
                "tool_statuses",
                "failure_detail",
            },
        )

    def test_contract_rejects_unknown_recommendation(self):
        payload = self.payload()
        payload["recommendation"] = "APPROVE_WITHOUT_REVIEW"

        with self.assertRaises(ValidationError):
            ProcurementDecision.model_validate(payload)

    def test_contract_requires_grounded_evidence_identifiers(self):
        payload = self.payload()
        del payload["evidence"][0]["tool_call_id"]

        with self.assertRaises(ValidationError):
            ProcurementDecision.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
