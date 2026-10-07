from __future__ import annotations

import unittest
from fastapi.testclient import TestClient
from mock_api.app import app


class MockApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health(self):
        r = self.client.get('/health')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'ok')

    def test_known_vendor(self):
        r = self.client.get('/vendor-risk/BrandBoard')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['security_review_status'], 'not_completed')

    def test_forced_outage(self):
        r = self.client.get('/vendor-risk/NimbusAI')
        self.assertEqual(r.status_code, 503)


if __name__ == '__main__':
    unittest.main()
