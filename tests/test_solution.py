from __future__ import annotations

import unittest

from src.contracts import ProcurementDecision
from src.solution import handle_request


class SolutionAdapterTests(unittest.TestCase):
    def test_adapter_returns_decision_for_each_architecture(self):
        for architecture in ("single", "staged"):
            with self.subTest(architecture=architecture):
                decision = handle_request("REQ-1001", architecture=architecture)
                self.assertIsInstance(decision, ProcurementDecision)
                self.assertTrue(decision.human_review_required)


if __name__ == "__main__":
    unittest.main()
