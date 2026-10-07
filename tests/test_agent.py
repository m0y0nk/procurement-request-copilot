from __future__ import annotations

import json
import unittest

from agents.single_agent import TOOL_NAMES, run_single_agent
from src.contracts import ProcurementRequest
from src.data_access import get_request
from src.llm import LLMResponse, LLMToolCall, ReplayResponseMissing
from tools.procurement import ProcurementTools


class SingleAgentTests(unittest.TestCase):
    def setUp(self):
        request_data = get_request("REQ-1001")
        request_data.update(
            {
                "request_id": "AGENT-TEST",
                "data_access_level": "customer_pii",
            }
        )
        self.request = ProcurementRequest.model_validate(request_data)
        self.tools = ProcurementTools(
            vendor_base_url="http://127.0.0.1:1",
            timeout_seconds=0.02,
            retry_backoff_seconds=0,
        )
        self.tool_calls = LLMResponse(
            content=None,
            tool_calls=tuple(
                LLMToolCall(id=f"provider-{index}", name=name, arguments={})
                for index, name in enumerate(TOOL_NAMES)
            ),
            finish_reason="tool_calls",
            usage={},
            raw_message={"tool_calls": []},
        )

    @staticmethod
    def _draft(recommendation: str = "USE_EXISTING_TOOL") -> LLMResponse:
        content = json.dumps(
            {
                "recommendation": recommendation,
                "next_step": "Procurement reviewer checks the request.",
            }
        )
        return LLMResponse(
            content=content,
            tool_calls=(),
            finish_reason="stop",
            usage={"total_tokens": 5},
            raw_message={"content": content},
        )

    def _queued_responses(self, responses: list[LLMResponse]):
        def invoke(messages: list[dict[str, object]], **kwargs: object) -> LLMResponse:
            self.assertTrue(messages)
            self.assertIn("mode", kwargs)
            return responses.pop(0)

        return invoke

    def test_rule_floor_overrides_lower_model_recommendation(self):
        invoke = self._queued_responses([self.tool_calls, self._draft()])
        decision, trace = run_single_agent(
            self.request,
            tools=self.tools,
            llm=invoke,
        )

        self.assertEqual(decision.rule_floor, "ESCALATE_SECURITY")
        self.assertEqual(decision.recommendation, "ESCALATE_SECURITY")
        self.assertIn("FLOOR_ENFORCED", {flag.code for flag in decision.risk_flags})
        self.assertEqual(len(decision.tool_statuses), len(TOOL_NAMES))
        self.assertEqual(decision.meta.llm_calls, 2)
        self.assertEqual(len(trace["tool_calls"]), len(TOOL_NAMES))

    def test_invalid_schema_is_repaired_once(self):
        responses = [
            self.tool_calls,
            self._draft("INVALID_RECOMMENDATION"),
            self._draft("ESCALATE_SECURITY"),
        ]
        decision = run_single_agent(
            self.request,
            tools=self.tools,
            llm=self._queued_responses(responses),
        )[0]

        self.assertIsNone(decision.failure_detail)
        self.assertEqual(decision.recommendation, "ESCALATE_SECURITY")
        self.assertEqual(decision.meta.llm_calls, 3)

    def test_replay_miss_fails_closed_and_preserves_floor(self):
        def missing_replay(messages, **kwargs):
            self.assertTrue(messages)
            self.assertIn("mode", kwargs)
            raise ReplayResponseMissing("No recorded response.")

        decision, trace = run_single_agent(
            self.request,
            mode="replay",
            tools=self.tools,
            llm=missing_replay,
        )

        self.assertEqual(decision.recommendation, decision.rule_floor)
        self.assertEqual(decision.rule_floor, "ESCALATE_SECURITY")
        self.assertIn("No recorded response", decision.failure_detail or "")
        self.assertIn("agent_failed_closed", {flag.code for flag in decision.risk_flags})
        self.assertEqual(trace["failure_detail"], "No recorded response.")

    def test_model_context_omits_amounts_and_currency_values(self):
        captured_messages: list[list[dict[str, object]]] = []
        responses = [self.tool_calls, self._draft("ESCALATE_SECURITY")]

        def capture(messages, **kwargs):
            self.assertIn("mode", kwargs)
            captured_messages.append(messages)
            return responses.pop(0)

        run_single_agent(
            self.request,
            tools=self.tools,
            llm=capture,
            additional_untrusted_texts=["Need $25,000 for this purchase."],
        )

        serialized = json.dumps(captured_messages)
        self.assertNotIn("$25,000", serialized)
        self.assertNotIn("$", serialized)
        self.assertNotIn('"available_usd"', serialized)
        self.assertNotIn('"annual_budget_usd"', serialized)
        self.assertIn("amount evaluated by code", serialized)

    def test_reasoning_tokens_are_retained_in_run_metadata_and_trace(self):
        tool_response = LLMResponse(
            content=None,
            tool_calls=self.tool_calls.tool_calls,
            finish_reason="tool_calls",
            usage={"total_tokens": 10, "reasoning_tokens": 6},
            raw_message={"tool_calls": []},
        )
        final_response = LLMResponse(
            content=self._draft().content,
            tool_calls=(),
            finish_reason="stop",
            usage={"total_tokens": 8, "reasoning_tokens": 3},
            raw_message={"content": "draft"},
        )

        decision, trace = run_single_agent(
            self.request,
            tools=self.tools,
            llm=self._queued_responses([tool_response, final_response]),
        )

        self.assertEqual(decision.meta.reasoning_tokens, 9)
        self.assertEqual(trace["token_usage"]["reasoning_tokens"], 9)


if __name__ == "__main__":
    unittest.main()
