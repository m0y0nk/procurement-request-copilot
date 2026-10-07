from __future__ import annotations

import csv
import json
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from eval.case_models import load_cases
from rules.approval_chain import business_approval_chain
from rules.evaluation import ProcurementFacts, evaluate_procurement_rules
from guards.injection import scan_untrusted_texts
from src.contracts import ProcurementRequest
from src.data_access import get_request
from tools.procurement import ProcurementTools

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def _csv_rows(filename: str) -> list[dict[str, str]]:
    with (DATA_DIR / filename).open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def _vendor_facts(case):
    vendor_name = case.fixture.overrides.get(
        "vendor_name",
        get_request(case.fixture.base_request_id)["vendor_name"],
    )
    if not vendor_name or case.fixture.vendor_service_unavailable:
        return None
    risk = json.loads((DATA_DIR / "vendor_risk.json").read_text(encoding="utf-8"))
    vendor_risk = risk.get(vendor_name)
    if vendor_risk is None or vendor_risk.get("force_error"):
        return None
    registry = next(
        row
        for row in _csv_rows("vendors.csv")
        if row["vendor_name"].casefold() == vendor_name.casefold()
    )
    service_status = vendor_risk["security_review_status"].casefold()
    registry_status = registry["security_status"].casefold()
    status_aliases = {"pending": "not_completed", "unknown": "not_completed"}
    conflicting = status_aliases.get(registry_status, registry_status) != status_aliases.get(
        service_status, service_status
    )
    return {
        "security_review_status": service_status,
        "security_review_date": (
            date.fromisoformat(vendor_risk["last_review_date"])
            if vendor_risk.get("last_review_date")
            else None
        ),
        "conflicting_vendor_evidence": conflicting,
        "vendor_is_new": registry["procurement_status"].casefold() == "new",
        "legal_terms_status": registry["legal_terms_status"],
        "stores_data_outside_region": vendor_risk.get("stores_data_outside_region"),
        "processes_personal_data": vendor_risk.get("processes_personal_data"),
        "notes": [registry["notes"], vendor_risk.get("notes", "")],
    }


class EvaluationCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = load_cases()
        cls.by_id = {case.id: case for case in cls.cases}

    def test_case_set_has_balanced_dev_and_holdout_splits(self):
        dev_count = sum(case.split == "dev" for case in self.cases)
        holdout_count = sum(case.split == "holdout" for case in self.cases)

        self.assertGreaterEqual(dev_count / len(self.cases), 0.35)
        self.assertGreaterEqual(holdout_count / len(self.cases), 0.35)

    def test_threshold_labels_match_deterministic_approval_tiers(self):
        for case in self.cases:
            if case.category != "Approval threshold boundaries":
                continue
            amount = Decimal(str(case.fixture.overrides["annual_cost_usd"]))
            expected_tier = {
                approval.role for approval in business_approval_chain(amount)
            }
            self.assertTrue(
                expected_tier.issubset(case.expected.approvals_required_roles),
                case.id,
            )

    def test_unknown_data_class_requests_clarification_not_security(self):
        for case_id in ("C-004", "C-026"):
            case = self.by_id[case_id]
            self.assertEqual(case.expected.recommendation, "REQUEST_MORE_INFO")
            self.assertIn("data access level", case.expected.missing_information)
            self.assertIn("security_review_required", case.expected.must_not_flag)

    def test_vendor_unavailability_requires_manual_review_and_legal(self):
        for case_id in ("C-029", "C-030"):
            case = self.by_id[case_id]
            self.assertEqual(case.expected.recommendation, "ESCALATE_SECURITY")
            self.assertIn("Security", case.expected.approvals_required_roles)
            self.assertIn("Legal", case.expected.approvals_required_roles)
            self.assertIn("vendor_risk_unavailable", case.expected.must_flag)

    def test_all_labels_match_policy_rules_and_starter_data(self):
        tools = ProcurementTools()
        employee_rows = {row["employee_id"]: row for row in _csv_rows("employees.csv")}
        budget_rows = {
            row["department"]: row for row in _csv_rows("department_budgets.csv")
        }

        for case in self.cases:
            with self.subTest(case_id=case.id):
                request_data = get_request(case.fixture.base_request_id).copy()
                request_data.update(case.fixture.overrides)
                request = ProcurementRequest.model_validate(request_data)
                department = employee_rows[request.requester_id]["department"]
                available_budget = int(budget_rows[department]["available_usd"])
                vendor = _vendor_facts(case)
                missing = [
                    label
                    for label, value in (
                        ("vendor", request.vendor_name),
                        ("annual cost", request.annual_cost_usd),
                        ("user count", request.user_count),
                        ("business purpose", request.business_justification),
                        (
                            "data access level",
                            request.data_access_level
                            if request.data_access_level != "unknown"
                            else None,
                        ),
                    )
                    if value is None or value == ""
                ]
                assessment = evaluate_procurement_rules(
                    ProcurementFacts(
                        annual_cost_usd=request.annual_cost_usd,
                        available_budget_usd=available_budget,
                        missing_information=tuple(missing),
                        data_access_level=request.data_access_level,
                        security_review_status=(
                            vendor["security_review_status"] if vendor else None
                        ),
                        security_review_date=(
                            vendor["security_review_date"] if vendor else None
                        ),
                        conflicting_vendor_evidence=(
                            vendor["conflicting_vendor_evidence"] if vendor else False
                        ),
                        vendor_risk_unavailable=vendor is None,
                        vendor_is_new=vendor["vendor_is_new"] if vendor else True,
                        legal_terms_status=(
                            vendor["legal_terms_status"] if vendor else None
                        ),
                        stores_data_outside_region=(
                            vendor["stores_data_outside_region"] if vendor else None
                        ),
                        processes_personal_data=(
                            vendor["processes_personal_data"] if vendor else None
                        ),
                    )
                )
                expected_roles = {
                    approval.role for approval in assessment.approvals_required
                }
                self.assertEqual(
                    expected_roles,
                    set(case.expected.approvals_required_roles),
                )
                self.assertEqual(
                    list(assessment.missing_information),
                    case.expected.missing_information,
                )

                catalog_result = tools.search_software_catalog(
                    product_name=request.product_name,
                    vendor_name=request.vendor_name,
                    category=request.category,
                )
                matches = catalog_result.data.matches
                flags = {flag.code for flag in assessment.risk_flags}
                if matches:
                    flags.add("existing_tool_overlap")
                texts = [
                    request.business_justification,
                    request.product_name,
                    request.vendor_name,
                    case.request,
                    *case.fixture.additional_untrusted_texts,
                    *(vendor["notes"] if vendor else []),
                    *(item.notes for item in matches),
                ]
                if scan_untrusted_texts(texts):
                    flags.add("prompt_injection_detected")
                self.assertTrue(set(case.expected.must_flag).issubset(flags))
                self.assertFalse(set(case.expected.must_not_flag).intersection(flags))

                if assessment.rule_floor in {
                    "ESCALATE_FINANCE",
                    "ESCALATE_SECURITY",
                }:
                    expected_recommendation = assessment.rule_floor
                elif assessment.missing_information:
                    expected_recommendation = "REQUEST_MORE_INFO"
                else:
                    exact_cover = any(
                        item.vendor_name.casefold() == request.vendor_name.casefold()
                        and tools.normalize(item.category)
                        == tools.normalize(request.category)
                        and item.licensed_seats >= (request.user_count or 0)
                        and item.status.casefold() == "approved"
                        for item in matches
                    )
                    expected_recommendation = (
                        "USE_EXISTING_TOOL" if exact_cover else "RECOMMEND_APPROVAL"
                    )
                self.assertEqual(
                    case.expected.recommendation,
                    expected_recommendation,
                )


if __name__ == "__main__":
    unittest.main()
