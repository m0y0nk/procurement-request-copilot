from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import requests

from src.ui_api import (
    ANALYSIS_TIMEOUT_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    analysis_error_message,
    api_get,
    api_post,
)


class UIApiTests(unittest.TestCase):
    def test_analysis_error_includes_structured_api_detail(self) -> None:
        response = requests.Response()
        response.status_code = 429
        response._content = (
            b'{"detail":"Per-minute rate limit requires waiting 133.0s."}'
        )
        error = requests.HTTPError(response=response)

        message = analysis_error_message(error)

        self.assertIn("133.0s", message)

    @patch("src.ui_api.requests.post")
    def test_analysis_timeout_allows_slow_live_request(self, post: Mock) -> None:
        response = Mock()
        post.return_value = response

        result = api_post(
            "/api/analyze",
            {"request_id": "REQ-1001"},
            timeout_seconds=ANALYSIS_TIMEOUT_SECONDS,
        )

        self.assertIs(result, response)
        self.assertGreater(ANALYSIS_TIMEOUT_SECONDS, REQUEST_TIMEOUT_SECONDS)
        self.assertEqual(post.call_args.kwargs["timeout"], 600)

    @patch("src.ui_api.requests.post")
    def test_non_analysis_posts_keep_short_timeout(self, post: Mock) -> None:
        response = Mock()
        post.return_value = response

        api_post("/api/decisions", {"request_id": "REQ-1001"})

        self.assertEqual(
            post.call_args.kwargs["timeout"],
            REQUEST_TIMEOUT_SECONDS,
        )

    @patch("src.ui_api.requests.get")
    def test_get_requests_keep_short_timeout(self, get: Mock) -> None:
        response = Mock()
        get.return_value = response

        api_get("/api/requests")

        self.assertEqual(
            get.call_args.kwargs["timeout"],
            REQUEST_TIMEOUT_SECONDS,
        )


if __name__ == "__main__":
    unittest.main()
