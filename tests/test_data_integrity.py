from __future__ import annotations

import csv
import json
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
EVALS = ROOT / "evals"
REFERENCE_DATE = date(2026, 9, 30)


def read_csv(name: str) -> list[dict[str, str]]:
    with (DATA / name).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class DataIntegrityTests(unittest.TestCase):
    def test_budget_arithmetic(self):
        for row in read_csv("department_budgets.csv"):
            self.assertEqual(
                int(row["annual_software_budget_usd"]) - int(row["committed_usd"]),
                int(row["available_usd"]),
            )
            self.assertGreaterEqual(int(row["available_usd"]), 0)

    def test_primary_ids_unique(self):
        for filename, field in [
            ("employees.csv", "employee_id"),
            ("software_catalog.csv", "software_id"),
            ("vendors.csv", "vendor_id"),
            ("purchase_history.csv", "purchase_id"),
        ]:
            values = [r[field] for r in read_csv(filename)]
            self.assertEqual(len(values), len(set(values)), f"duplicate {field} in {filename}")

    def test_request_ids_unique(self):
        requests = json.loads((DATA / "requests.json").read_text(encoding="utf-8"))
        ids = [r["request_id"] for r in requests]
        self.assertEqual(len(ids), len(set(ids)))

    def test_employee_manager_references(self):
        employees = read_csv("employees.csv")
        employee_ids = {r["employee_id"] for r in employees}
        for row in employees:
            if row["manager_id"]:
                self.assertIn(row["manager_id"], employee_ids)

    def test_request_foreign_keys(self):
        employees = read_csv("employees.csv")
        employee_by_id = {r["employee_id"]: r for r in employees}
        departments = {r["department"] for r in read_csv("department_budgets.csv")}
        vendors = {r["vendor_name"] for r in read_csv("vendors.csv")}
        vendor_risk = json.loads((DATA / "vendor_risk.json").read_text(encoding="utf-8"))
        requests = json.loads((DATA / "requests.json").read_text(encoding="utf-8"))

        for req in requests:
            self.assertIn(req["requester_id"], employee_by_id)
            self.assertIn(employee_by_id[req["requester_id"]]["department"], departments)
            self.assertIn(req["vendor_name"], vendors)
            self.assertIn(req["vendor_name"], vendor_risk)
            if req["annual_cost_usd"] is not None:
                self.assertGreaterEqual(req["annual_cost_usd"], 0)
            if req["user_count"] is not None:
                self.assertGreater(req["user_count"], 0)

    def test_vendor_review_dates_not_in_future(self):
        for row in read_csv("vendors.csv"):
            if row["security_review_date"]:
                self.assertLessEqual(date.fromisoformat(row["security_review_date"]), REFERENCE_DATE)

        risk = json.loads((DATA / "vendor_risk.json").read_text(encoding="utf-8"))
        for record in risk.values():
            if record.get("last_review_date"):
                self.assertLessEqual(date.fromisoformat(record["last_review_date"]), REFERENCE_DATE)

    def test_public_eval_request_references(self):
        requests = json.loads((DATA / "requests.json").read_text(encoding="utf-8"))
        request_ids = {r["request_id"] for r in requests}
        cases = json.loads((EVALS / "public_cases.json").read_text(encoding="utf-8"))
        case_ids = [c["case_id"] for c in cases]
        self.assertEqual(len(case_ids), len(set(case_ids)))
        for case in cases:
            self.assertIn(case["request_id"], request_ids)


if __name__ == "__main__":
    unittest.main()
