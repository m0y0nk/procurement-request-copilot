from __future__ import annotations

import csv
import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Generic, Literal, TypeVar
from urllib.parse import quote
from uuid import uuid4

import requests
from pydantic import BaseModel, ConfigDict

from rules.evaluation import ProcurementFacts, evaluate_procurement_rules
from rules.policy import (
    POLICY_RULES,
    REFERENCE_DATE,
    RULE_SECTIONS,
    SECURITY_REVIEW_MAX_AGE_DAYS,
)
from src.contracts import ApprovalRequired, RiskFlag

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
T = TypeVar("T", bound=BaseModel)


class ToolResult(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str
    status: Literal["success", "unavailable"]
    data: T | None = None
    reason: str | None = None


class EmployeeBudgetData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: str
    employee_name: str
    department: str
    manager_id: str | None
    annual_budget_usd: int
    committed_usd: int
    available_usd: int
    currency: Literal["USD"] = "USD"
    period: Literal["annual"] = "annual"


class CatalogMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    software_id: str
    product_name: str
    category: str
    vendor_name: str
    status: str
    licensed_seats: int
    scope: str
    notes: str


class CatalogData(BaseModel):
    matches: list[CatalogMatch]


class VendorStatusData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor_name: str
    procurement_status: str
    registry_security_status: str
    security_review_status: str
    last_review_date: date | None
    assessment_age_days: int | None
    assessment_current: bool
    legal_terms_status: str
    risk_level: str | None
    processes_personal_data: bool | None
    stores_data_outside_region: bool | None
    conflicting_evidence: bool
    notes: list[str]


class PolicyRule(BaseModel):
    rule_id: str
    text: str


class PolicyData(BaseModel):
    rules: list[PolicyRule]


class PurchaseRecord(BaseModel):
    purchase_id: str
    purchase_date: date
    department: str
    vendor_name: str
    product_name: str
    annual_amount_usd: int
    status: str
    notes: str


class PurchaseHistoryData(BaseModel):
    records: list[PurchaseRecord]


class ApprovalChainData(BaseModel):
    rule_floor: str
    approvals_required: list[ApprovalRequired]
    risk_flags: list[RiskFlag]
    missing_information: list[str]
    budget_insufficient: bool


class ToolCallRecord(BaseModel):
    tool_call_id: str
    tool_name: str
    status: Literal["success", "unavailable"]
    record_refs: list[str]
    reason: str | None = None


class ProcurementTools:
    def __init__(
        self,
        *,
        data_dir: Path = DATA_DIR,
        vendor_base_url: str | None = None,
        timeout_seconds: float = 3.0,
        retry_backoff_seconds: float = 0.1,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        self.data_dir = data_dir
        self.vendor_base_url = (
            vendor_base_url
            or __import__("os").environ.get(
                "VENDOR_RISK_BASE_URL", "http://127.0.0.1:8001"
            )
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.retry_backoff_seconds = retry_backoff_seconds
        self.calls: list[ToolCallRecord] = []

    def _unavailable(self, tool_name: str, reason: str) -> ToolResult:
        call_id = str(uuid4())
        self.calls.append(
            ToolCallRecord(
                tool_call_id=call_id,
                tool_name=tool_name,
                status="unavailable",
                record_refs=[],
                reason=reason,
            )
        )
        return ToolResult(tool_call_id=call_id, status="unavailable", reason=reason)

    def _success(self, tool_name: str, data: T, record_refs: list[str]) -> ToolResult[T]:
        call_id = str(uuid4())
        self.calls.append(
            ToolCallRecord(
                tool_call_id=call_id,
                tool_name=tool_name,
                status="success",
                record_refs=record_refs,
            )
        )
        return ToolResult(tool_call_id=call_id, status="success", data=data)

    def _rows(self, filename: str) -> list[dict[str, str]]:
        with (self.data_dir / filename).open(encoding="utf-8", newline="") as file:
            return list(csv.DictReader(file))

    def _request(self, request_id: str) -> dict:
        with (self.data_dir / "requests.json").open(encoding="utf-8") as file:
            requests_data = json.load(file)
        for request in requests_data:
            if request.get("request_id") == request_id:
                return request
        raise KeyError(f"Unknown request_id: {request_id}")

    def get_employee_and_budget(self, employee_id: str) -> ToolResult[EmployeeBudgetData]:
        try:
            employee = next(
                row for row in self._rows("employees.csv")
                if row["employee_id"] == employee_id
            )
            budget = next(
                row for row in self._rows("department_budgets.csv")
                if row["department"] == employee["department"]
            )
            data = EmployeeBudgetData(
                employee_id=employee_id,
                employee_name=employee["name"],
                department=employee["department"],
                manager_id=employee["manager_id"] or None,
                annual_budget_usd=int(budget["annual_software_budget_usd"]),
                committed_usd=int(budget["committed_usd"]),
                available_usd=int(budget["available_usd"]),
            )
        except (OSError, KeyError, StopIteration, ValueError) as exc:
            return self._unavailable("get_employee_and_budget", str(exc))
        return self._success(
            "get_employee_and_budget",
            data,
            [employee_id, data.department],
        )

    def search_software_catalog(
        self,
        *,
        product_name: str,
        vendor_name: str,
        category: str,
    ) -> ToolResult[CatalogData]:
        terms = {
            self._normalize(product_name),
            self._normalize(vendor_name),
            self._normalize(category),
        } - {""}
        try:
            rows = self._rows("software_catalog.csv")
            matches = [
                CatalogMatch(
                    software_id=row["software_id"],
                    product_name=row["product_name"],
                    category=row["category"],
                    vendor_name=row["vendor_name"],
                    status=row["status"],
                    licensed_seats=int(row["licensed_seats"]),
                    scope=row["scope"],
                    notes=row["notes"],
                )
                for row in rows
                if terms.intersection(
                    {
                        self._normalize(row["product_name"]),
                        self._normalize(row["vendor_name"]),
                        self._normalize(row["category"]),
                    }
                )
            ]
        except (OSError, KeyError, ValueError) as exc:
            return self._unavailable("search_software_catalog", str(exc))
        return self._success(
            "search_software_catalog",
            CatalogData(matches=matches),
            [match.software_id for match in matches],
        )

    def get_vendor_status(self, vendor_name: str) -> ToolResult[VendorStatusData]:
        error: Exception | None = None
        response_data: dict | None = None
        for attempt in range(2):
            try:
                response = requests.get(
                    f"{self.vendor_base_url}/vendor-risk/{quote(vendor_name, safe='')}",
                    timeout=self.timeout_seconds,
                )
                if response.status_code == 404:
                    return self._unavailable(
                        "get_vendor_status",
                        f"No vendor-risk record for {vendor_name}.",
                    )
                response.raise_for_status()
                response_data = response.json()
                break
            except (requests.RequestException, ValueError) as exc:
                error = exc
                if attempt == 0 and self.retry_backoff_seconds:
                    time.sleep(self.retry_backoff_seconds)
        if response_data is None:
            return self._unavailable(
                "get_vendor_status",
                f"Vendor-risk request failed after retry: {error}",
            )
        if not isinstance(response_data, dict):
            return self._unavailable(
                "get_vendor_status",
                "Vendor-risk response must be a JSON object.",
            )

        try:
            registry = next(
                row for row in self._rows("vendors.csv")
                if row["vendor_name"].casefold() == vendor_name.casefold()
            )
            raw_date = response_data.get("last_review_date")
            review_date = date.fromisoformat(raw_date) if raw_date else None
            age_days = (REFERENCE_DATE - review_date).days if review_date else None
            current = (
                age_days is not None
                and 0 <= age_days <= SECURITY_REVIEW_MAX_AGE_DAYS
            )
            service_status = str(response_data.get("security_review_status", "unknown"))
            registry_status = registry["security_status"]
            status_conflict = (
                self._normalize_vendor_status(registry_status)
                != self._normalize_vendor_status(service_status)
            )
            date_conflict = (
                bool(registry.get("security_review_date"))
                and registry["security_review_date"] != raw_date
            )
            data = VendorStatusData(
                vendor_name=vendor_name,
                procurement_status=registry["procurement_status"],
                registry_security_status=registry_status,
                security_review_status=service_status,
                last_review_date=review_date,
                assessment_age_days=age_days,
                assessment_current=current,
                legal_terms_status=registry["legal_terms_status"],
                risk_level=response_data.get("risk_level"),
                processes_personal_data=response_data.get("processes_personal_data"),
                stores_data_outside_region=response_data.get("stores_data_outside_region"),
                conflicting_evidence=status_conflict or date_conflict,
                notes=[
                    note
                    for note in (registry.get("notes", ""), response_data.get("notes", ""))
                    if note
                ],
            )
        except (OSError, KeyError, StopIteration, TypeError, ValueError) as exc:
            return self._unavailable("get_vendor_status", f"Invalid vendor evidence: {exc}")
        return self._success("get_vendor_status", data, [vendor_name])

    def lookup_policy(self, query: str) -> ToolResult[PolicyData]:
        query_terms = set(re.findall(r"[a-z0-9_]+", query.casefold()))
        try:
            policy_text = (self.data_dir / "procurement_policy.md").read_text(
                encoding="utf-8"
            )
        except OSError as exc:
            return self._unavailable("lookup_policy", str(exc))
        sections: dict[str, str] = {}
        current_number: str | None = None
        lines: list[str] = []
        preamble: list[str] = []
        for line in policy_text.splitlines():
            heading = re.match(r"^##\s+(\d+)\.", line)
            if heading:
                if current_number is not None:
                    sections[current_number] = "\n".join(lines).strip()
                else:
                    sections["0"] = "\n".join(preamble).strip()
                current_number = heading.group(1)
                lines = [line]
            elif current_number is not None:
                lines.append(line)
            else:
                preamble.append(line)
        if current_number is not None:
            sections[current_number] = "\n".join(lines).strip()
        else:
            sections["0"] = "\n".join(preamble).strip()

        selected: list[PolicyRule] = []
        for rule_id, text in POLICY_RULES.items():
            terms = set(re.findall(r"[a-z0-9_]+", text.casefold()))
            if query_terms.intersection(terms) or rule_id.casefold() in query.casefold():
                source_text = sections.get(RULE_SECTIONS[rule_id])
                if source_text is None:
                    return self._unavailable(
                        "lookup_policy",
                        f"Policy section {RULE_SECTIONS[rule_id]} is missing for {rule_id}.",
                    )
                selected.append(PolicyRule(rule_id=rule_id, text=source_text))
        return self._success(
            "lookup_policy",
            PolicyData(rules=selected),
            [rule.rule_id for rule in selected],
        )

    def get_purchase_history(
        self,
        *,
        department: str,
        vendor_name: str,
        product_name: str,
    ) -> ToolResult[PurchaseHistoryData]:
        try:
            records = [
                PurchaseRecord(
                    purchase_id=row["purchase_id"],
                    purchase_date=date.fromisoformat(row["purchase_date"]),
                    department=row["department"],
                    vendor_name=row["vendor_name"],
                    product_name=row["product_name"],
                    annual_amount_usd=int(row["annual_amount_usd"]),
                    status=row["status"],
                    notes=row["notes"],
                )
                for row in self._rows("purchase_history.csv")
                if row["department"].casefold() == department.casefold()
                and (
                    row["vendor_name"].casefold() == vendor_name.casefold()
                    or self._normalize(product_name)
                    in self._normalize(row["product_name"])
                )
            ]
        except (OSError, KeyError, ValueError) as exc:
            return self._unavailable("get_purchase_history", str(exc))
        return self._success(
            "get_purchase_history",
            PurchaseHistoryData(records=records),
            [record.purchase_id for record in records],
        )

    def compute_approval_chain(self, request_id: str) -> ToolResult[ApprovalChainData]:
        try:
            request = self._request(request_id)
            employee = next(
                row for row in self._rows("employees.csv")
                if row["employee_id"] == request["requester_id"]
            )
            budget = next(
                row for row in self._rows("department_budgets.csv")
                if row["department"] == employee["department"]
            )
        except (OSError, KeyError, StopIteration, ValueError) as exc:
            return self._unavailable("compute_approval_chain", str(exc))

        vendor_result = self.get_vendor_status(request["vendor_name"])
        vendor = vendor_result.data if vendor_result.status == "success" else None
        data_access = request.get("data_access_level")
        missing = tuple(
            field
            for field, value in (
                ("annual cost", request.get("annual_cost_usd")),
                ("user count", request.get("user_count")),
                ("business purpose", request.get("business_justification")),
                ("data access level", data_access if data_access != "unknown" else None),
            )
            if value is None or value == ""
        )
        assessment = evaluate_procurement_rules(
            ProcurementFacts(
                annual_cost_usd=request.get("annual_cost_usd"),
                available_budget_usd=int(budget["available_usd"]),
                missing_information=missing,
                data_access_level=data_access,
                security_review_status=(
                    vendor.security_review_status if vendor else None
                ),
                security_review_date=vendor.last_review_date if vendor else None,
                conflicting_vendor_evidence=(
                    vendor.conflicting_evidence if vendor else False
                ),
                vendor_risk_unavailable=vendor is None,
                vendor_is_new=(
                    vendor.procurement_status.casefold() == "new" if vendor else True
                ),
                legal_terms_status=vendor.legal_terms_status if vendor else None,
                stores_data_outside_region=(
                    vendor.stores_data_outside_region if vendor else None
                ),
            )
        )
        data = ApprovalChainData(
            rule_floor=assessment.rule_floor,
            approvals_required=list(assessment.approvals_required),
            risk_flags=list(assessment.risk_flags),
            missing_information=list(assessment.missing_information),
            budget_insufficient=assessment.budget_insufficient,
        )
        refs = [request_id]
        if vendor_result.status == "success":
            refs.append(request["vendor_name"])
        return self._success("compute_approval_chain", data, refs)

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()

    @classmethod
    def _normalize_vendor_status(cls, value: str) -> str:
        normalized = cls._normalize(value)
        return {
            "pending": "not completed",
            "not completed": "not completed",
            "approved": "approved",
            "expired": "expired",
            "unknown": "unknown",
        }.get(normalized, normalized)
