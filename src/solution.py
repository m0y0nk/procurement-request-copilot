from __future__ import annotations

from time import perf_counter

from src.contracts import (
    Architecture,
    EvidenceItem,
    HumanReview,
    ProcurementRequest,
    ProcurementDecision,
    RiskFlag,
    RunMetadata,
)
from src.data_access import get_request
from guards.grounding import grounded_evidence
from guards.injection import scan_untrusted_texts
from tools.procurement import ProcurementTools


def handle_request(
    request_id: str,
    architecture: Architecture = "single",
) -> ProcurementDecision:
    request = ProcurementRequest.model_validate(get_request(request_id))
    if architecture == "staged":
        raise NotImplementedError("Architecture B is not implemented in Phase 3.")
    from agents.single_agent import run_single_agent

    return run_single_agent(request)[0]


def analyze_request(
    request: ProcurementRequest,
    architecture: Architecture = "single",
    *,
    tools: ProcurementTools | None = None,
    additional_untrusted_texts: list[str] | None = None,
) -> ProcurementDecision:
    started = perf_counter()
    request_id = request.request_id
    tools = tools or ProcurementTools()
    evidence: list[EvidenceItem] = []
    risk_flags: list[RiskFlag] = []

    employee_result = tools.get_employee_and_budget(request.requester_id)
    if employee_result.status == "success" and employee_result.data is not None:
        employee = employee_result.data
        evidence.append(
            EvidenceItem(
                id="e-budget",
                claim=(
                    f"{employee.department} has ${employee.available_usd} USD "
                    "available for the annual software budget."
                ),
                source_tool="get_employee_and_budget",
                tool_call_id=employee_result.tool_call_id,
                record_ref=employee.department,
            )
        )

    catalog_result = tools.search_software_catalog(
        product_name=request.product_name,
        vendor_name=request.vendor_name,
        category=request.category,
    )
    if catalog_result.status == "success" and catalog_result.data is not None:
        for index, item in enumerate(catalog_result.data.matches, start=1):
            evidence.append(
                EvidenceItem(
                    id=f"e-catalog-{index}",
                    claim=(
                        f"{item.product_name} is {item.status}, has "
                        f"{item.licensed_seats} seats, and scope {item.scope}."
                    ),
                    source_tool="search_software_catalog",
                    tool_call_id=catalog_result.tool_call_id,
                    record_ref=item.software_id,
                )
            )
            risk_flags.append(
                RiskFlag(
                    code="existing_tool_overlap",
                    severity="medium",
                    detail=f"{item.product_name} is an existing catalog option to review.",
                    evidence_ids=[f"e-catalog-{index}"],
                )
            )

    vendor_result = tools.get_vendor_status(request.vendor_name)
    vendor = vendor_result.data if vendor_result.status == "success" else None
    if vendor is not None:
        evidence.append(
            EvidenceItem(
                id="e-vendor",
                claim=(
                    f"Vendor security assessment is {vendor.security_review_status}; "
                    f"review date is {vendor.last_review_date or 'missing'}."
                ),
                source_tool="get_vendor_status",
                tool_call_id=vendor_result.tool_call_id,
                record_ref=vendor.vendor_name,
            )
        )
        if vendor.conflicting_evidence:
            risk_flags.append(
                RiskFlag(
                    code="conflicting_vendor_evidence",
                    severity="high",
                    detail="Internal registry and vendor-risk service disagree.",
                    evidence_ids=["e-vendor"],
                )
            )
    else:
        risk_flags.append(
            RiskFlag(
                code="vendor_risk_unavailable",
                severity="high",
                detail=vendor_result.reason or "Vendor risk could not be verified.",
            )
        )
    policy_result = tools.lookup_policy(
        "required request information budget overlap security privacy legal approval human"
    )
    if policy_result.status == "success" and policy_result.data is not None:
        for index, rule in enumerate(policy_result.data.rules, start=1):
            evidence.append(
                EvidenceItem(
                    id=f"e-policy-{index}",
                    claim=rule.text,
                    source_tool="lookup_policy",
                    tool_call_id=policy_result.tool_call_id,
                    record_ref=rule.rule_id,
                )
            )

    employee = employee_result.data
    history_result = tools.get_purchase_history(
        department=employee.department if employee is not None else "",
        vendor_name=request.vendor_name,
        product_name=request.product_name,
    )
    if history_result.status == "success" and history_result.data is not None:
        for index, record in enumerate(history_result.data.records, start=1):
            evidence.append(
                EvidenceItem(
                    id=f"e-purchase-{index}",
                    claim=(
                        f"{record.department} purchased {record.product_name} "
                        f"for ${record.annual_amount_usd} USD annually."
                    ),
                    source_tool="get_purchase_history",
                    tool_call_id=history_result.tool_call_id,
                    record_ref=record.purchase_id,
                )
            )

    missing_fields = [
        field
        for field, value in (
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
    assessment_result = tools.compute_approval_chain(
        request_id=request_id,
        annual_cost_usd=request.annual_cost_usd,
        available_budget_usd=employee.available_usd if employee is not None else None,
        missing_information=missing_fields,
        data_access_level=request.data_access_level,
        security_review_status=(
            vendor.security_review_status if vendor is not None else None
        ),
        security_review_date=vendor.last_review_date if vendor is not None else None,
        conflicting_vendor_evidence=(
            vendor.conflicting_evidence if vendor is not None else False
        ),
        vendor_risk_unavailable=vendor is None,
        vendor_is_new=vendor.procurement_status.casefold() == "new" if vendor else True,
        legal_terms_status=vendor.legal_terms_status if vendor is not None else None,
        stores_data_outside_region=(
            vendor.stores_data_outside_region if vendor is not None else None
        ),
        processes_personal_data=(
            vendor.processes_personal_data if vendor is not None else None
        ),
    )
    if assessment_result.status == "success" and assessment_result.data is not None:
        assessment = assessment_result.data
        floor = assessment.rule_floor
        approvals = assessment.approvals_required
        missing = assessment.missing_information
        for flag in assessment.risk_flags:
            if flag.code not in {existing.code for existing in risk_flags}:
                risk_flags.append(flag)
    else:
        floor = "ESCALATE_SECURITY"
        approvals = []
        missing = ["Could not compute the policy approval chain."]
        risk_flags.append(
            RiskFlag(
                code="approval_chain_unavailable",
                severity="high",
                detail=assessment_result.reason or "Rule evaluation is unavailable.",
            )
        )

    untrusted_texts = [
        request.business_justification,
        request.product_name,
        request.vendor_name,
    ]
    if vendor is not None:
        untrusted_texts.extend(vendor.notes)
    if catalog_result.data is not None:
        untrusted_texts.extend(item.notes for item in catalog_result.data.matches)
    untrusted_texts.extend(additional_untrusted_texts or [])
    if scan_untrusted_texts(untrusted_texts):
        risk_flags.append(
            RiskFlag(
                code="prompt_injection_detected",
                severity="high",
                detail="Business data contains an instruction that conflicts with policy controls.",
            )
        )

    evidence, dropped = grounded_evidence(evidence, tools.calls)
    if dropped:
        risk_flags.append(
            RiskFlag(
                code="ungrounded_evidence_dropped",
                severity="high",
                detail=f"{dropped} evidence item(s) did not match successful tool output and were removed.",
            )
        )

    if floor in {"ESCALATE_FINANCE", "ESCALATE_SECURITY"}:
        recommendation = floor
    elif missing:
        recommendation = "REQUEST_MORE_INFO"
    elif vendor is None:
        recommendation = "ESCALATE_SECURITY"
    elif request.annual_cost_usd is not None and request.user_count is not None:
        exact_cover = next(
            (
                item for item in (catalog_result.data.matches if catalog_result.data else [])
                if item.vendor_name.casefold() == request.vendor_name.casefold()
                and tools.normalize(item.category)
                == tools.normalize(request.category)
                and item.licensed_seats >= request.user_count
                and item.status.casefold() == "approved"
            ),
            None,
        )
        recommendation = "USE_EXISTING_TOOL" if exact_cover else "RECOMMEND_APPROVAL"
    else:
        recommendation = "REQUEST_MORE_INFO"

    next_step = {
        "REQUEST_MORE_INFO": "Requester supplies the missing information.",
        "ESCALATE_SECURITY": "Security reviewer checks the vendor and data-access controls.",
        "ESCALATE_FINANCE": "Finance reviewer assesses the budget exception.",
        "USE_EXISTING_TOOL": "Procurement reviewer confirms existing capacity and fit.",
        "RECOMMEND_APPROVAL": "Procurement reviewer routes the request to listed approvers.",
        "RECOMMEND_REJECTION": "Procurement reviewer confirms an explicit policy prohibition.",
    }[recommendation]
    return ProcurementDecision(
        request_id=request_id,
        recommendation=recommendation,
        next_step=next_step,
        evidence=evidence,
        approvals_required=approvals,
        missing_information=missing,
        risk_flags=risk_flags,
        rule_floor=floor,
        human_review=HumanReview(
            required=True,
            reason="A human reviewer owns the final purchasing decision.",
        ),
        meta=RunMetadata(
            architecture="A" if architecture == "single" else "B",
            llm_calls=0,
            tool_calls=len(tools.calls),
            latency_ms=(perf_counter() - started) * 1000,
        ),
    )
