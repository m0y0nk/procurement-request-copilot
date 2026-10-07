from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.contracts import ProcurementRequest, Recommendation
from src.data_access import get_request
ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "eval" / "cases" / "cases.json"


class ExpectedOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation: Recommendation
    approvals_required_roles: list[str]
    missing_information: list[str]
    must_flag: list[str]
    must_not_flag: list[str]
    must_call_tools: list[str]


class CaseFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_request_id: str
    overrides: dict[str, object] = Field(default_factory=dict)
    additional_untrusted_texts: list[str] = Field(default_factory=list)
    vendor_service_unavailable: bool = False


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    split: Literal["dev", "holdout"]
    category: str
    employee_id: str
    request: str
    synthetic: bool = False
    fixture: CaseFixture
    expected: ExpectedOutcome
    rationale: str

    @model_validator(mode="after")
    def ensure_employee_matches_fixture(self) -> EvaluationCase:
        request = get_request(self.fixture.base_request_id).copy()
        request.update(self.fixture.overrides)
        if request.get("requester_id") != self.employee_id:
            raise ValueError(
                f"{self.id}: employee_id must match fixture requester_id."
            )
        return self

    def procurement_request(self) -> ProcurementRequest:
        request = get_request(self.fixture.base_request_id).copy()
        request.update(self.fixture.overrides)
        request["request_id"] = self.id
        return ProcurementRequest.model_validate(request)


def load_cases(path: Path = CASES_PATH) -> list[EvaluationCase]:
    raw_cases = json.loads(path.read_text(encoding="utf-8"))
    cases = [EvaluationCase.model_validate(item) for item in raw_cases]
    validate_case_set(cases)
    return cases


def validate_case_set(cases: list[EvaluationCase]) -> None:
    case_ids = [case.id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Evaluation case IDs must be unique.")
    if len(cases) < 30:
        raise ValueError("At least 30 evaluation cases are required.")
    if any(case.synthetic and not case.fixture for case in cases):
        raise ValueError("Every synthetic case must have a fixture.")
    coverage = {
        "Clean approve path": 3,
        "Incomplete / ambiguous request": 4,
        "Existing tool solves it": 4,
        "Conflicting or expired vendor info": 4,
        "Security / privacy sensitive": 4,
        "Approval threshold boundaries": 9,
        "Over budget": 2,
        "Prompt injection in business data": 3,
        "Tool / API unavailable": 2,
        "Blocked vendor / policy violation": 2,
    }
    categories: dict[str, int] = {}
    for case in cases:
        categories[case.category] = categories.get(case.category, 0) + 1
    undercovered = {
        category: minimum
        for category, minimum in coverage.items()
        if categories.get(category, 0) < minimum
    }
    if undercovered:
        raise ValueError(f"Evaluation categories below minimum: {undercovered}")
    for case in cases:
        if not case.request.strip() or not case.rationale.strip():
            raise ValueError(f"{case.id}: request and rationale must be non-empty.")
        if len(case.expected.approvals_required_roles) != len(
            set(case.expected.approvals_required_roles)
        ):
            raise ValueError(f"{case.id}: approval roles must be unique.")
        if len(case.expected.missing_information) != len(
            set(case.expected.missing_information)
        ):
            raise ValueError(f"{case.id}: missing-information labels must be unique.")
        if set(case.expected.must_flag).intersection(case.expected.must_not_flag):
            raise ValueError(f"{case.id}: a flag cannot be both required and forbidden.")

    threshold_cases = {
        str(case.fixture.overrides.get("annual_cost_usd")): case
        for case in cases
        if case.category == "Approval threshold boundaries"
    }
    threshold_roles = {
        "999.99": {"Manager"},
        "1000": {"Manager"},
        "1000.01": {"Department Head", "Procurement"},
        "9999.99": {"Department Head", "Procurement"},
        "10000": {"Department Head", "Procurement"},
        "10000.01": {"Department Head", "Finance", "Procurement"},
        "24999.99": {"Department Head", "Finance", "Procurement"},
        "25000": {"Department Head", "Finance", "Procurement"},
        "25000.01": {"Department Head", "Finance", "CFO", "Procurement"},
    }
    for amount, roles in threshold_roles.items():
        case = threshold_cases.get(amount)
        if case is None:
            raise ValueError(f"Missing threshold boundary case for ${amount}.")
        if not roles.issubset(case.expected.approvals_required_roles):
            raise ValueError(
                f"{case.id}: expected approval roles omit a tier approver for ${amount}."
            )
    dev_count = sum(case.split == "dev" for case in cases)
    holdout_count = len(cases) - dev_count
    if min(dev_count, holdout_count) / len(cases) < 0.35:
        raise ValueError("Dev and holdout should each contain at least 35% of cases.")
