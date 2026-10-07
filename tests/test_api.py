from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from api import create_app
from src.contracts import ProcurementRequest
from src.solution import analyze_request
from tools.procurement import ProcurementTools


class ProcurementApiTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.decisions_path = Path(self.tempdir.name) / "decisions.jsonl"

        def analyzer(request: ProcurementRequest, **kwargs):
            self.assertEqual(kwargs.get("mode"), "replay")
            decision = analyze_request(
                request,
                tools=ProcurementTools(
                    vendor_base_url="http://127.0.0.1:1",
                    timeout_seconds=0.02,
                    retry_backoff_seconds=0,
                ),
            )
            return decision, {"tool_calls": []}

        self.client = TestClient(
            create_app(
                analyzer=analyzer,
                decisions_path=self.decisions_path,
            )
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_health_and_sample_requests(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        response = self.client.get("/api/requests")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json())

    def test_sample_request_analysis_returns_typed_decision(self):
        response = self.client.post(
            "/api/analyze",
            json={"request_id": "REQ-1001", "mode": "replay"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["decision"]["request_id"],
            "REQ-1001",
        )
        self.assertTrue(response.json()["decision"]["human_review"]["required"])

    def test_unknown_sample_request_is_not_found(self):
        response = self.client.post(
            "/api/analyze",
            json={"request_id": "UNKNOWN"},
        )

        self.assertEqual(response.status_code, 404)

    def test_new_request_rejects_blank_employee_and_nonpositive_user_count(self):
        response = self.client.post(
            "/api/analyze",
            json={
                "description": "Internal workflow request.",
                "request": {
                    "requester_id": "   ",
                    "user_count": 0,
                },
                "mode": "replay",
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_reviewer_action_requires_non_whitespace_note_and_persists(self):
        invalid = self.client.post(
            "/api/decisions",
            json={
                "request_id": "REQ-1001",
                "action": "accept",
                "note": "   ",
                "recommendation": "RECOMMEND_APPROVAL",
            },
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertFalse(self.decisions_path.exists())

        saved = self.client.post(
            "/api/decisions",
            json={
                "request_id": "REQ-1001",
                "action": "accept",
                "note": " Reviewed by procurement. ",
                "recommendation": "RECOMMEND_APPROVAL",
            },
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["note"], "Reviewed by procurement.")
        self.assertTrue(self.decisions_path.exists())

        history = self.client.get(
            "/api/decisions",
            params={"request_id": "REQ-1001"},
        )
        self.assertEqual(len(history.json()), 1)


if __name__ == "__main__":
    unittest.main()
