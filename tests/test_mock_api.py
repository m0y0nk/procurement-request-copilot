from __future__ import annotations

import unittest
from urllib.parse import quote
from unittest.mock import patch

from fastapi.testclient import TestClient
import mock_api.app as mock_api
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

    def test_literal_percent_escape_in_vendor_name(self):
        vendor_name = 'Regression%41Vendor'
        record = {'security_review_status': 'approved'}
        with patch.dict(mock_api.DATA, {vendor_name: record}):
            response = self.client.get(f'/vendor-risk/{quote(vendor_name, safe="")}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['vendor_name'], vendor_name)


if __name__ == '__main__':
    unittest.main()
