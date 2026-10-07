from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from src.llm import LLMError, ReplayResponseMissing, invoke, request_key


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
        self.assertEqual(post.call_args.kwargs["timeout"], 30.0)

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
