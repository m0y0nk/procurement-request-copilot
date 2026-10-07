from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Recommendation = Literal[
    "USE_EXISTING_TOOL",
    "RECOMMEND_APPROVAL",
    "REQUEST_MORE_INFO",
    "ESCALATE_SECURITY",
    "ESCALATE_FINANCE",
    "RECOMMEND_REJECTION",
]
RiskSeverity = Literal["low", "medium", "high"]
Architecture = Literal["single", "staged"]
ArchitectureLabel = Literal["A", "B"]


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    claim: str
    source_tool: str
    tool_call_id: str
    record_ref: str


class ProcurementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    requester_id: str
    product_name: str
    vendor_name: str
    category: str
    annual_cost_usd: int | str | None
    user_count: int | None
    business_justification: str
    data_access_level: str
    requested_integrations: list[str]
    urgency: str


class ApprovalRequired(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    reason: str
    rule_id: str


class RiskFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: RiskSeverity
    detail: str
    evidence_ids: list[str] = Field(default_factory=list)


class HumanReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: Literal[True] = True
    reason: str


class ToolStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str
    tool_name: str
    status: Literal["success", "unavailable"]
    reason: str | None = None


class RunMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    architecture: ArchitectureLabel
    llm_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    latency_ms: float = Field(ge=0)


class RunTelemetry(BaseModel):
    llm_calls: int | None = None
    tool_calls: int | None = None
    tool_names: list[str] = Field(default_factory=list)


class ProcurementDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    recommendation: Recommendation
    next_step: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    approvals_required: list[ApprovalRequired] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    rule_floor: Recommendation
    human_review: HumanReview
    meta: RunMetadata
    tool_statuses: list[ToolStatus] = Field(default_factory=list)
    failure_detail: str | None = None

    @property
    def required_approvals(self) -> list[str]:
        return [approval.role for approval in self.approvals_required]

    @property
    def human_review_required(self) -> bool:
        return self.human_review.required

    @property
    def telemetry(self) -> RunTelemetry:
        return RunTelemetry(
            llm_calls=self.meta.llm_calls,
            tool_calls=self.meta.tool_calls,
        )
