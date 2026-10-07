from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from src.llm import (
    LLMError,
    LLMRunAborted,
    ReplayResponseMissing,
    invoke,
    invoke_chat,
    live_run_usage,
    request_key,
    reset_live_run_state,
)


class LLMWrapperTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.usage_path = Path(self.tempdir.name) / "usage.json"
        self.replay_path = Path(self.tempdir.name) / "responses.json"
        self.environment = patch.dict(
            os.environ,
            {
                "LLM_USAGE_PATH": str(self.usage_path),
                "LLM_REPLAY_PATH": str(self.replay_path),
                "LLM_MIN_INTERVAL_SECONDS": "0",
                "LLM_MAX_WAIT_SECONDS": "90",
                "LLM_MAX_TOKENS_PER_DAY": "150000",
                "LLM_MAX_TOKENS_PER_RUN": "150000",
                "LLM_MAX_CALLS_PER_RUN": "200",
                "LLM_MAX_TOKENS": "1200",
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        reset_live_run_state()
        self.messages = [
            {"role": "system", "content": "Return a structured result."},
            {"role": "user", "content": "Review the request."},
        ]

    @staticmethod
    def _provider_response(
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        content: str = '{"recommendation":"RECOMMEND_APPROVAL"}',
    ) -> Mock:
        response = Mock()
        response.status_code = status
        response.headers = headers or {}
        response.json.return_value = {
            "choices": [
                {
                    "message": {"content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "total_tokens": 12,
            },
        }
        return response

    def test_replay_returns_matching_recorded_text_and_latency(self):
        replay_file = Path(self.tempdir.name) / "recorded.json"
        replay_file.write_text(
            json.dumps(
                {
                    request_key(self.messages): {
                        "raw_message": {"content": '{"ok":true}'},
                        "finish_reason": "stop",
                        "usage": {"total_tokens": 9},
                        "latency_ms": 234.5,
                    }
                }
            ),
            encoding="utf-8",
        )

        response = invoke_chat(
            self.messages,
            mode="replay",
            replay_path=replay_file,
        )

        self.assertEqual(response.content, '{"ok":true}')
        self.assertEqual(response.latency_ms, 234.5)
        self.assertEqual(response.usage["total_tokens"], 9)

    def test_replay_miss_is_explicit(self):
        replay_file = Path(self.tempdir.name) / "empty.json"
        replay_file.write_text("{}", encoding="utf-8")

        with self.assertRaises(ReplayResponseMissing):
            invoke(self.messages, mode="replay", replay_path=replay_file)

    def test_live_mode_requires_credentials_and_model(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(LLMError, "LLM_MODEL is required"):
                invoke(self.messages, mode="live")

    @patch("src.llm.requests.post")
    def test_live_openai_compatible_response(self, post):
        post.return_value = self._provider_response()

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
        self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], 1200)

    @patch("src.llm.requests.post")
    def test_live_tool_calls_are_parsed_and_forwarded(self, post):
        response = self._provider_response()
        response.json.return_value["choices"][0]["message"] = {
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
        }
        tool_schema = [
            {
                "type": "function",
                "function": {
                    "name": "get_employee_and_budget",
                    "parameters": {"type": "object"},
                },
            }
        ]
        post.return_value = response

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
        replay_file = Path(self.tempdir.name) / "tool_responses.json"
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
    def test_live_transport_errors_do_not_leak_error_details(self, post):
        post.side_effect = requests.Timeout("secret-value-for-test timed out")

        with self.assertRaisesRegex(LLMError, "LLM request timed out") as raised:
            invoke(
                self.messages,
                mode="live",
                provider="openai",
                model="assessment-model",
                api_key="secret-value-for-test",
            )

        self.assertNotIn("secret-value-for-test", str(raised.exception))

    @patch("src.llm.time.sleep")
    @patch("src.llm.requests.post")
    def test_429_retry_after_is_honored(self, post, mocked_sleep):
        post.side_effect = [
            self._provider_response(status=429, headers={"Retry-After": "2"}),
            self._provider_response(),
        ]

        response = invoke_chat(
            self.messages,
            mode="live",
            provider="openai",
            model="assessment-model",
            api_key="test-key",
        )

        self.assertEqual(response.retries, 1)
        self.assertEqual(live_run_usage()["retries"], 1)
        self.assertEqual(mocked_sleep.call_args_list[0].args, (2.0,))
        self.assertEqual(post.call_count, 2)

    @patch("src.llm.requests.post")
    def test_429_wait_above_cap_stops_without_retry(self, post):
        post.return_value = self._provider_response(
            status=429,
            headers={"Retry-After": "120"},
        )

        with self.assertRaisesRegex(LLMRunAborted, "above LLM_MAX_WAIT_SECONDS"):
            invoke_chat(
                self.messages,
                mode="live",
                provider="openai",
                model="assessment-model",
                api_key="test-key",
            )

        self.assertEqual(post.call_count, 1)

    @patch("src.llm.random.uniform", return_value=0)
    @patch("src.llm.time.sleep")
    @patch("src.llm.requests.post")
    def test_5xx_retries_four_times_before_failing(self, post, mocked_sleep, _jitter):
        post.side_effect = [
            self._provider_response(status=503) for _ in range(5)
        ]

        with self.assertRaisesRegex(LLMError, "remained after four retries"):
            invoke_chat(
                self.messages,
                mode="live",
                provider="openai",
                model="assessment-model",
                api_key="test-key",
            )

        self.assertEqual(post.call_count, 5)
        self.assertEqual(mocked_sleep.call_count, 4)
        self.assertEqual(live_run_usage()["retries"], 4)
        self.assertEqual(_jitter.call_count, 4)

    @patch("src.llm.requests.post")
    def test_daily_429_stops_without_retry_or_sleep(self, post):
        post.return_value = self._provider_response(
            status=429,
            headers={"Retry-After": "24h"},
        )

        with self.assertRaisesRegex(LLMRunAborted, "daily rate limit"):
            invoke_chat(
                self.messages,
                mode="live",
                provider="openai",
                model="assessment-model",
                api_key="test-key",
            )

        self.assertEqual(post.call_count, 1)

    @patch("src.llm.time.sleep")
    @patch("src.llm.requests.post")
    def test_minute_429_is_not_misclassified_by_daily_headers(
        self, post, mocked_sleep
    ):
        post.side_effect = [
            self._provider_response(
                status=429,
                headers={
                    "Retry-After": "2",
                    "x-ratelimit-remaining-tokens-day": "100000",
                    "x-ratelimit-reset-tokens-day": "1d",
                },
            ),
            self._provider_response(),
        ]

        invoke_chat(
            self.messages,
            mode="live",
            provider="openai",
            model="assessment-model",
            api_key="test-key",
        )

        self.assertEqual(post.call_count, 2)
        self.assertEqual(mocked_sleep.call_args_list[0].args, (2.0,))

    def test_daily_cap_refuses_start(self):
        today = datetime.now(UTC).date().isoformat()
        self.usage_path.write_text(
            json.dumps({today: {"tokens": 150000}}),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(LLMRunAborted, "already spent"):
            reset_live_run_state()

    @patch("src.llm.requests.post")
    def test_run_token_cap_refuses_before_http_call(self, post):
        with patch.dict(os.environ, {"LLM_MAX_TOKENS_PER_RUN": "10"}):
            with self.assertRaisesRegex(LLMRunAborted, "would exceed per-run token cap"):
                invoke_chat(
                    self.messages,
                    mode="live",
                    provider="openai",
                    model="assessment-model",
                    api_key="test-key",
                )

        post.assert_not_called()

    @patch("src.llm.requests.post")
    def test_run_call_cap_refuses_before_http_call(self, post):
        with patch.dict(os.environ, {"LLM_MAX_CALLS_PER_RUN": "0"}):
            with self.assertRaisesRegex(LLMRunAborted, "Per-run call cap reached"):
                invoke_chat(
                    self.messages,
                    mode="live",
                    provider="openai",
                    model="assessment-model",
                    api_key="test-key",
                )

        post.assert_not_called()

    @patch("src.llm.requests.post")
    def test_circuit_breaker_stops_after_three_consecutive_timeouts(self, post):
        post.side_effect = requests.Timeout("provider timeout")

        for index in range(3):
            with self.subTest(failure=index + 1):
                expected_error = LLMRunAborted if index == 2 else LLMError
                with self.assertRaises(expected_error) as raised:
                    invoke_chat(
                        self.messages,
                        mode="live",
                        provider="openai",
                        model="assessment-model",
                        api_key="test-key",
                    )
                if index == 2:
                    self.assertIn("Circuit breaker", str(raised.exception))

        self.assertEqual(post.call_count, 3)

    @patch("src.llm.requests.post")
    def test_live_cache_hit_avoids_network_and_replays_latency(self, post):
        post.return_value = self._provider_response()
        first = invoke_chat(
            self.messages,
            mode="live",
            provider="openai",
            model="assessment-model",
            api_key="test-key",
        )

        cached = invoke_chat(
            self.messages,
            mode="live",
            provider="openai",
            model="assessment-model",
            api_key="test-key",
        )

        self.assertEqual(post.call_count, 1)
        self.assertTrue(cached.cached)
        self.assertEqual(cached.latency_ms, first.latency_ms)

    @patch("src.llm.time.sleep")
    @patch("src.llm.requests.post")
    def test_rate_limit_headers_throttle_the_next_live_call(self, post, mocked_sleep):
        post.side_effect = [
            self._provider_response(
                headers={
                    "x-ratelimit-remaining-tokens": "0",
                    "x-ratelimit-reset-tokens": "5s",
                }
            ),
            self._provider_response(),
        ]

        invoke_chat(
            self.messages,
            mode="live",
            provider="openai",
            model="assessment-model",
            api_key="test-key",
        )
        invoke_chat(
            [{"role": "user", "content": "a different request"}],
            mode="live",
            provider="openai",
            model="assessment-model",
            api_key="test-key",
        )

        self.assertIn(5.0, [call.args[0] for call in mocked_sleep.call_args_list])
        self.assertEqual(post.call_count, 2)

    @patch("src.llm.requests.post")
    def test_no_cache_forces_a_fresh_live_call(self, post):
        post.return_value = self._provider_response()

        invoke_chat(
            self.messages,
            mode="live",
            provider="openai",
            model="assessment-model",
            api_key="test-key",
        )
        invoke_chat(
            self.messages,
            mode="live",
            provider="openai",
            model="assessment-model",
            api_key="test-key",
            no_cache=True,
        )

        self.assertEqual(post.call_count, 2)

    @patch("src.llm.requests.post")
    def test_success_writes_replay_atomically_with_tool_calls_and_latency(self, post):
        response = self._provider_response()
        response.json.return_value["choices"][0]["message"] = {
            "content": None,
            "tool_calls": [
                {
                    "id": "provider-call-1",
                    "type": "function",
                    "function": {"name": "lookup_policy", "arguments": "{}"},
                }
            ],
        }
        post.return_value = response

        result = invoke_chat(
            self.messages,
            mode="live",
            provider="openai",
            model="assessment-model",
            api_key="test-key",
        )
        record = json.loads(self.replay_path.read_text(encoding="utf-8"))[
            request_key(self.messages)
        ]

        self.assertIn("tool_calls", record["raw_message"])
        self.assertEqual(record["finish_reason"], "stop")
        self.assertEqual(record["usage"]["total_tokens"], 12)
        self.assertEqual(record["latency_ms"], result.latency_ms)
        daily_usage = json.loads(self.usage_path.read_text(encoding="utf-8"))
        self.assertEqual(daily_usage[datetime.now(UTC).date().isoformat()]["tokens"], 12)
        self.assertFalse(any(path.suffix == ".tmp" for path in self.replay_path.parent.iterdir()))
        self.assertNotIn("test-key", self.replay_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
