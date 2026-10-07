from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.contracts import ApprovalRequired, Recommendation, RiskFlag
from rules.approval_chain import annual_amount, business_approval_chain
from rules.policy import REFERENCE_DATE, SECURITY_REVIEW_MAX_AGE_DAYS


@dataclass(frozen=True)
class ProcurementFacts:
    annual_cost_usd: Decimal | int | str | None
    available_budget_usd: Decimal | int | str | None
    missing_information: tuple[str, ...] = ()
    data_access_level: str | None = None
    security_review_status: str | None = None
    security_review_date: date | None = None
    conflicting_vendor_evidence: bool = False
    vendor_risk_unavailable: bool = False
    vendor_is_new: bool = False
    legal_terms_status: str | None = None
    stores_data_outside_region: bool | None = None


@dataclass(frozen=True)
class RuleAssessment:
    rule_floor: Recommendation
    approvals_required: tuple[ApprovalRequired, ...]
    risk_flags: tuple[RiskFlag, ...]
    missing_information: tuple[str, ...]
    budget_insufficient: bool


def vendor_review_is_current(
    review_date: date | None,
    reference_date: date = REFERENCE_DATE,
) -> bool:
    if review_date is None:
        return False
    age_days = (reference_date - review_date).days
    return 0 <= age_days <= SECURITY_REVIEW_MAX_AGE_DAYS


def _approval(role: str, reason: str, rule_id: str) -> ApprovalRequired:
    return ApprovalRequired(role=role, reason=reason, rule_id=rule_id)


def _unique_approvals(approvals: list[ApprovalRequired]) -> tuple[ApprovalRequired, ...]:
    by_role: dict[str, ApprovalRequired] = {}
    for approval in approvals:
        current = by_role.get(approval.role)
        if current is None:
            by_role[approval.role] = approval
        else:
            by_role[approval.role] = ApprovalRequired(
                role=approval.role,
                reason=f"{current.reason} {approval.reason}",
                rule_id=f"{current.rule_id};{approval.rule_id}",
            )
    return tuple(by_role.values())


def evaluate_procurement_rules(facts: ProcurementFacts) -> RuleAssessment:
    approvals: list[ApprovalRequired] = []
    flags: list[RiskFlag] = []
    missing = list(dict.fromkeys(facts.missing_information))
    if facts.annual_cost_usd is None and "annual cost" not in missing:
        missing.append("annual cost")
    if (facts.data_access_level or "").strip().casefold() in {"", "unknown"}:
        if "data access level" not in missing:
            missing.append("data access level")
    amount = annual_amount(facts.annual_cost_usd) if facts.annual_cost_usd is not None else None
    available = (
        annual_amount(facts.available_budget_usd)
        if facts.available_budget_usd is not None
        else None
    )
    budget_insufficient = amount is not None and available is not None and amount > available

    if amount is not None:
        approvals.extend(business_approval_chain(amount))
    if budget_insufficient:
        approvals.append(_approval("Finance", "Budget exception review is required.", "POL-BUDGET"))
        flags.append(
            RiskFlag(
                code="budget_insufficient",
                severity="high",
                detail=f"Annual cost {amount} USD exceeds available budget {available} USD.",
            )
        )

    data_class = (facts.data_access_level or "").strip().casefold()
    security_required_data = {
        "source_code",
        "production_telemetry",
        "production",
        "production_access",
        "cloud_account",
        "confidential_documents",
        "employee_pii",
        "customer_pii",
        "credentials",
        "secrets",
    }
    review_current = vendor_review_is_current(facts.security_review_date)
    security_required = (
        data_class in security_required_data
        or facts.conflicting_vendor_evidence
        or facts.vendor_risk_unavailable
        or facts.security_review_status is None
        or facts.security_review_status.casefold() != "approved"
        or not review_current
    )
    if security_required:
        approvals.append(
            _approval("Security", "Sensitive access or current vendor assessment requires review.", "POL-SECURITY")
        )
        flags.append(
            RiskFlag(
                code="security_review_required",
                severity="high",
                detail="Security review is required by the access class or vendor assessment status.",
            )
        )
    if not review_current and not facts.vendor_risk_unavailable:
        flags.append(
            RiskFlag(
                code="vendor_review_expired",
                severity="high",
                detail="The vendor security review is missing or older than 365 days at the policy reference date.",
            )
        )
    if facts.vendor_risk_unavailable:
        flags.append(
            RiskFlag(
                code="vendor_risk_unavailable",
                severity="high",
                detail="Vendor risk status could not be verified.",
            )
        )
    if facts.conflicting_vendor_evidence:
        flags.append(
            RiskFlag(
                code="conflicting_vendor_evidence",
                severity="high",
                detail="Vendor registry and risk-service evidence conflict.",
            )
        )

    privacy_required = (
        data_class in {"employee_pii", "customer_pii"}
        or facts.stores_data_outside_region is True
    )
    if privacy_required:
        approvals.append(
            _approval("Privacy", "PII processing or cross-region storage requires review.", "POL-PRIVACY")
        )
        flags.append(
            RiskFlag(
                code="privacy_review_required",
                severity="high",
                detail="Privacy review is required for the stated data handling.",
            )
        )

    terms_approved = (facts.legal_terms_status or "").strip().casefold() in {
        "approved",
        "standard",
    }
    legal_required = (
        (facts.vendor_is_new and amount is not None and amount >= Decimal("10000"))
        or not terms_approved
        or facts.stores_data_outside_region is True
    )
    if legal_required:
        approvals.append(
            _approval("Legal", "Vendor terms or material data processing requires review.", "POL-LEGAL")
        )
        flags.append(
            RiskFlag(
                code="legal_review_required",
                severity="high",
                detail="Legal review is required for vendor onboarding, terms, or data handling.",
            )
        )

    if missing:
        flags.append(
            RiskFlag(
                code="missing_information",
                severity="medium",
                detail="Material request information is missing.",
            )
        )

    if budget_insufficient:
        floor: Recommendation = "ESCALATE_FINANCE"
    elif security_required:
        floor = "ESCALATE_SECURITY"
    elif missing:
        floor = "REQUEST_MORE_INFO"
    else:
        floor = "RECOMMEND_APPROVAL"

    return RuleAssessment(
        rule_floor=floor,
        approvals_required=_unique_approvals(approvals),
        risk_flags=tuple(flags),
        missing_information=tuple(missing),
        budget_insufficient=budget_insufficient,
    )
