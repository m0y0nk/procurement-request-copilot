from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from src.llm import LLMError, ReplayResponseMissing, invoke, invoke_chat, request_key


class LLMWrapperTests(unittest.TestCase):
    def setUp(self):
        self.messages = [
            {"role": "system", "content": "Return a structured result."},
            {"role": "user", "content": "Review the request."},
        ]

    def test_replay_returns_matching_recorded_text(self):
        with tempfile.TemporaryDirectory() as directory:
            replay_file = Path(directory) / "responses.json"
            replay_file.write_text(
                json.dumps({request_key(self.messages): {"content": '{"ok":true}'}}),
                encoding="utf-8",
            )

            response = invoke(
                self.messages,
                mode="replay",
                replay_path=replay_file,
            )

        self.assertEqual(response, '{"ok":true}')

    def test_replay_miss_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            replay_file = Path(directory) / "responses.json"
            replay_file.write_text("{}", encoding="utf-8")

            with self.assertRaises(ReplayResponseMissing):
                invoke(self.messages, mode="replay", replay_path=replay_file)

    def test_live_mode_requires_credentials_and_model(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(LLMError, "LLM_MODEL is required"):
                invoke(self.messages, mode="live")

    @patch("src.llm.requests.post")
    def test_live_openai_compatible_response(self, post):
        response = Mock()
        response.json.return_value = {
            "choices": [{"message": {"content": '{"recommendation":"RECOMMEND_APPROVAL"}'}}]
        }
        post.return_value = response

        content = invoke(
            self.messages,
            mode="live",
            provider="openai",
            model="assessment-model",
            api_key="test-key",
            base_url="https://llm.example.test/v1",
        )

        self.assertEqual(content, '{"recommendation":"RECOMMEND_APPROVAL"}')
        self.assertEqual(
            post.call_args.args[0],
            "https://llm.example.test/v1/chat/completions",
        )
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            "Bearer test-key",
        )
        self.assertEqual(post.call_args.kwargs["timeout"], 30.0)

    @patch("src.llm.requests.post")
    def test_live_tool_calls_are_parsed_and_forwarded(self, post):
        response = Mock()
        response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "get_employee_and_budget",
                                    "arguments": '{"employee_id":"E001"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        }
        post.return_value = response
        tool_schema = [
            {
                "type": "function",
                "function": {
                    "name": "get_employee_and_budget",
                    "parameters": {"type": "object"},
                },
            }
        ]

        result = invoke_chat(
            self.messages,
            mode="live",
            provider="openai",
            model="assessment-model",
            api_key="test-key",
            tools=tool_schema,
        )

        self.assertEqual(result.tool_calls[0].name, "get_employee_and_budget")
        self.assertEqual(result.tool_calls[0].arguments, {"employee_id": "E001"})
        self.assertEqual(result.usage["prompt_tokens"], 10)
        self.assertEqual(post.call_args.kwargs["json"]["tools"], tool_schema)

    def test_replay_can_supply_tool_call_responses(self):
        with tempfile.TemporaryDirectory() as directory:
            replay_file = Path(directory) / "responses.json"
            replay_file.write_text(
                json.dumps(
                    {
                        request_key(self.messages): {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "function": {
                                        "name": "get_employee_and_budget",
                                        "arguments": {"employee_id": "E001"},
                                    },
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = invoke_chat(
                self.messages,
                mode="replay",
                replay_path=replay_file,
            )

        self.assertEqual(result.tool_calls[0].arguments["employee_id"], "E001")

    @patch("src.llm.requests.post")
    def test_live_transport_errors_are_reported(self, post):
        post.side_effect = requests.Timeout("timed out")

        with self.assertRaisesRegex(LLMError, "LLM request failed"):
            invoke(
                self.messages,
                mode="live",
                provider="openai",
                model="assessment-model",
                api_key="test-key",
            )


if __name__ == "__main__":
    unittest.main()
