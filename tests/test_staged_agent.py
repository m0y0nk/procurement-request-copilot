from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from agents.single_agent import TOOL_NAMES
from agents.staged_agent import run_staged_agent
from src.contracts import ProcurementRequest
from src.data_access import get_request
from src.llm import LLMResponse, LLMToolCall
from tools.procurement import ProcurementTools


class StagedAgentTests(unittest.TestCase):
    def setUp(self):
        request_data = get_request("REQ-1001")
        request_data.update(
            {
                "request_id": "C-001",
                "requester_id": "E004",
                "data_access_level": "internal_documents",
            }
        )
        self.request = ProcurementRequest.model_validate(request_data)
        self.tools = ProcurementTools(retry_backoff_seconds=0)
        self.tool_responses = LLMResponse(
            content=None,
            tool_calls=tuple(
                LLMToolCall(
                    id=f"provider-{index}",
                    name=name,
                    arguments={},
                )
                for index, name in enumerate(TOOL_NAMES)
            ),
            finish_reason="tool_calls",
            usage={"total_tokens": 10, "reasoning_tokens": 2},
            raw_message={"tool_calls": []},
        )

    @patch("tools.procurement.requests.get")
    def test_stages_tools_then_evidence_pack_then_restricted_reviewer(self, get):
        vendor_response = Mock()
        vendor_response.status_code = 200
        vendor_response.json.return_value = {
            "security_review_status": "approved",
            "last_review_date": "2026-06-20",
            "risk_level": "low",
            "processes_personal_data": True,
            "stores_data_outside_region": False,
            "notes": "Current assessment.",
        }
        get.return_value = vendor_response
        evidence_pack = json.dumps(
            {
                "need_summary": "Finance needs signing capacity.",
                "tool_results": list(TOOL_NAMES),
                "evidence_ids": ["e-budget", "e-catalog-1"],
                "missing_information": [],
            }
        )
        reviewer = json.dumps(
            {
                "recommendation": "RECOMMEND_APPROVAL",
                "next_step": "Privacy reviewer checks the request.",
            }
        )
        responses = [
            self.tool_responses,
            self._response(evidence_pack),
            self._response(reviewer),
        ]
        calls = []

        def invoke(messages, **kwargs):
            calls.append((messages, kwargs))
            return responses.pop(0)

        decision, trace = run_staged_agent(
            self.request,
            tools=self.tools,
            llm=invoke,
        )

        self.assertEqual(decision.meta.architecture, "B")
        self.assertEqual(decision.recommendation, "USE_EXISTING_TOOL")
        self.assertEqual(decision.rule_floor, "RECOMMEND_APPROVAL")
        self.assertEqual(decision.meta.llm_calls, 3)
        self.assertEqual(
            [call["stage"] for call in trace["llm_calls"]],
            ["analyst", "analyst", "reviewer"],
        )
        self.assertEqual(
            [name for name in TOOL_NAMES],
            [call["tool_name"] for call in trace["tool_calls"]],
        )
        self.assertEqual(len(calls[0][1]["tools"]), len(TOOL_NAMES))
        self.assertIsNone(calls[1][1]["tools"])
        self.assertIsNone(calls[2][1]["tools"])
        self.assertIn("Code-computed minimum outcome: RECOMMEND_APPROVAL", calls[2][0][1]["content"])
        allowed_ids = json.dumps(
            sorted(item.id for item in decision.evidence),
            separators=(",", ":"),
        )
        self.assertIn(
            f"Allowed evidence IDs (code-generated): {allowed_ids}",
            calls[0][0][0]["content"],
        )
        self.assertIn("Tool record references", calls[0][0][0]["content"])
        self.assertEqual(trace["analyst_evidence_pack"]["evidence_ids"], ["e-budget", "e-catalog-1"])
        self.assertEqual(trace["ungrounded_evidence_count"], 0)

    def test_floor_and_ungrounded_analyst_references_are_guarded(self):
        responses = [
            self.tool_responses,
            self._response(
                json.dumps(
                    {
                        "need_summary": "Need signing service.",
                        "tool_results": list(TOOL_NAMES),
                        "evidence_ids": ["E004", "Finance", "C-001"],
                        "missing_information": ["made up field"],
                    }
                )
            ),
            self._response(
                json.dumps(
                    {
                        "recommendation": "RECOMMEND_APPROVAL",
                        "next_step": "Security reviewer checks vendor controls.",
                    }
                )
            ),
        ]
        decision, trace = run_staged_agent(
            self.request,
            tools=ProcurementTools(
                vendor_base_url="http://127.0.0.1:1",
                timeout_seconds=0.02,
                retry_backoff_seconds=0,
            ),
            llm=lambda messages, **kwargs: responses.pop(0),
        )

        self.assertEqual(decision.rule_floor, "ESCALATE_SECURITY")
        self.assertEqual(decision.recommendation, "ESCALATE_SECURITY")
        self.assertIn("FLOOR_ENFORCED", {flag.code for flag in decision.risk_flags})
        self.assertIn(
            "ungrounded_evidence_dropped",
            {flag.code for flag in decision.risk_flags},
        )
        self.assertEqual(trace["ungrounded_evidence_count"], 3)
        self.assertEqual(trace["analyst_evidence_pack"]["evidence_ids"], [])
        self.assertEqual(trace["analyst_evidence_pack"]["missing_information"], [])

    @patch("tools.procurement.requests.get")
    def test_missing_information_guard_applies_to_reviewer_recommendation(self, get):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "security_review_status": "approved",
            "last_review_date": "2026-06-20",
            "risk_level": "low",
            "processes_personal_data": True,
            "stores_data_outside_region": False,
            "notes": "Current assessment.",
        }
        get.return_value = response
        request_data = get_request("REQ-1010")
        request_data["request_id"] = "C-003"
        request = ProcurementRequest.model_validate(request_data)
        evidence_pack = json.dumps(
            {
                "need_summary": "Finance training package.",
                "tool_results": list(TOOL_NAMES),
                "evidence_ids": ["e-budget"],
                "missing_information": [],
            }
        )
        responses = [
            self.tool_responses,
            self._response(evidence_pack),
            self._response(
                json.dumps(
                    {
                        "recommendation": "REQUEST_MORE_INFO",
                        "next_step": "Privacy reviewer checks the request.",
                    }
                )
            ),
        ]

        decision, _ = run_staged_agent(
            request,
            tools=ProcurementTools(retry_backoff_seconds=0),
            llm=lambda messages, **kwargs: responses.pop(0),
        )

        self.assertEqual(decision.missing_information, [])
        self.assertEqual(decision.recommendation, "RECOMMEND_APPROVAL")
        self.assertIn(
            "unsupported_request_more_info",
            {flag.code for flag in decision.risk_flags},
        )

    @staticmethod
    def _response(content: str) -> LLMResponse:
        return LLMResponse(
            content=content,
            tool_calls=(),
            finish_reason="stop",
            usage={"total_tokens": 5},
            raw_message={"content": content},
        )


if __name__ == "__main__":
    unittest.main()
