from __future__ import annotations

import unittest
from datetime import date, timedelta
from decimal import Decimal

from rules.approval_chain import annual_amount, business_approval_chain
from rules.evaluation import (
    ProcurementFacts,
    evaluate_procurement_rules,
    vendor_review_is_current,
)
from rules.policy import REFERENCE_DATE


class ApprovalChainTests(unittest.TestCase):
    def test_annual_amount_boundaries(self):
        cases = [
            ("999.99", ["Manager"]),
            ("1000", ["Manager"]),
            ("1000.01", ["Department Head", "Procurement"]),
            ("9999.99", ["Department Head", "Procurement"]),
            ("10000", ["Department Head", "Procurement"]),
            ("10000.01", ["Department Head", "Finance", "Procurement"]),
            ("24999.99", ["Department Head", "Finance", "Procurement"]),
            ("25000", ["Department Head", "Finance", "Procurement"]),
            ("25000.01", ["Department Head", "Finance", "CFO", "Procurement"]),
        ]
        for amount, expected_roles in cases:
            with self.subTest(amount=amount):
                self.assertEqual(
                    [approval.role for approval in business_approval_chain(amount)],
                    expected_roles,
                )

    def test_invalid_amounts_fail_explicitly(self):
        for value in ("-0.01", "NaN", "Infinity", "not-money"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    annual_amount(value)


class VendorReviewFreshnessTests(unittest.TestCase):
    def test_exact_365_day_boundary(self):
        self.assertTrue(
            vendor_review_is_current(REFERENCE_DATE - timedelta(days=365))
        )
        self.assertFalse(
            vendor_review_is_current(REFERENCE_DATE - timedelta(days=366))
        )
        self.assertFalse(
            vendor_review_is_current(REFERENCE_DATE + timedelta(days=1))
        )
        self.assertFalse(vendor_review_is_current(None))


class ProcurementRuleTests(unittest.TestCase):
    def facts(self, **overrides) -> ProcurementFacts:
        values = {
            "annual_cost_usd": Decimal("800"),
            "available_budget_usd": Decimal("15000"),
            "data_access_level": "internal_documents",
            "security_review_status": "approved",
            "security_review_date": date(2026, 6, 20),
            "vendor_is_new": False,
            "legal_terms_status": "Approved",
            "stores_data_outside_region": False,
        }
        values.update(overrides)
        return ProcurementFacts(**values)

    def test_budget_equal_is_within_budget_and_overage_escalates(self):
        within = evaluate_procurement_rules(
            self.facts(annual_cost_usd="15000", available_budget_usd="15000")
        )
        over = evaluate_procurement_rules(
            self.facts(annual_cost_usd="15000.01", available_budget_usd="15000")
        )
        self.assertFalse(within.budget_insufficient)
        self.assertEqual(within.rule_floor, "RECOMMEND_APPROVAL")
        self.assertTrue(over.budget_insufficient)
        self.assertEqual(over.rule_floor, "ESCALATE_FINANCE")
        self.assertEqual(
            [approval.role for approval in over.approvals_required].count("Finance"),
            1,
        )

    def test_missing_cost_and_unknown_data_request_clarification(self):
        result = evaluate_procurement_rules(
            self.facts(
                annual_cost_usd=None,
                data_access_level="unknown",
                security_review_status="approved",
                security_review_date=REFERENCE_DATE,
            )
        )
        self.assertEqual(result.rule_floor, "REQUEST_MORE_INFO")
        self.assertEqual(result.missing_information, ("annual cost", "data access level"))

    def test_pii_requires_security_and_privacy(self):
        result = evaluate_procurement_rules(
            self.facts(data_access_level="customer_pii")
        )
        roles = {approval.role for approval in result.approvals_required}
        self.assertEqual(result.rule_floor, "ESCALATE_SECURITY")
        self.assertTrue({"Security", "Privacy"}.issubset(roles))
        self.assertIn("privacy_review_required", {flag.code for flag in result.risk_flags})

    def test_new_vendor_legal_boundary_is_inclusive(self):
        at_boundary = evaluate_procurement_rules(
            self.facts(
                annual_cost_usd="10000",
                vendor_is_new=True,
                legal_terms_status="Unknown",
            )
        )
        below = evaluate_procurement_rules(
            self.facts(
                annual_cost_usd="9999.99",
                vendor_is_new=True,
                legal_terms_status="Approved",
            )
        )
        self.assertIn("Legal", {a.role for a in at_boundary.approvals_required})
        self.assertNotIn("Legal", {a.role for a in below.approvals_required})


if __name__ == "__main__":
    unittest.main()
