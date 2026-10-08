from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agents.single_agent import run_single_agent
from src.contracts import ProcurementDecision, ProcurementRequest, Recommendation
from src.decisions import DecisionStore, ReviewerAction, ReviewerDecision
from src.data_access import get_request, load_requests
from src.llm import LLMRunAborted

Mode = Literal["live", "replay"]
ROOT = Path(__file__).resolve().parent
DEFAULT_DECISIONS_PATH = ROOT / "data" / "decisions.jsonl"


class RequestIntake(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str | None = None
    requester_id: str = Field(min_length=1)
    product_name: str = ""
    vendor_name: str = ""
    category: str = ""
    annual_cost_usd: int | str | None = None
    user_count: int | None = Field(default=None, gt=0)
    business_justification: str = ""
    data_access_level: str = "unknown"
    requested_integrations: list[str] = Field(default_factory=list)
    urgency: str = "normal"

    @field_validator(
        "requester_id",
        "product_name",
        "vendor_name",
        "category",
        "business_justification",
        "data_access_level",
        mode="before",
    )
    @classmethod
    def trim_text_fields(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("annual_cost_usd", mode="before")
    @classmethod
    def normalize_annual_cost(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    def to_request(self, description: str) -> ProcurementRequest:
        return ProcurementRequest(
            request_id=self.request_id or f"REQ-{uuid4().hex[:12].upper()}",
            requester_id=self.requester_id,
            product_name=self.product_name,
            vendor_name=self.vendor_name,
            category=self.category,
            annual_cost_usd=self.annual_cost_usd,
            user_count=self.user_count,
            business_justification=self.business_justification or description,
            data_access_level=self.data_access_level,
            requested_integrations=self.requested_integrations,
            urgency=self.urgency,
        )


class AnalyzePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str | None = None
    request: RequestIntake | None = None
    description: str | None = None
    architecture: Literal["A", "B"] = "A"
    mode: Mode | None = None

    @model_validator(mode="after")
    def requires_one_request_source(self) -> AnalyzePayload:
        if bool(self.request_id) == bool(self.request):
            raise ValueError("Provide exactly one of request_id or request.")
        if self.request is not None and not (self.description or "").strip():
            raise ValueError("A plain-language description is required for new requests.")
        return self


class ReviewerActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    action: ReviewerAction
    note: str = Field(min_length=1, max_length=2000)
    recommendation: Recommendation
    reviewer: str = Field(default="Procurement reviewer", min_length=1, max_length=200)

    @field_validator("note", "reviewer")
    @classmethod
    def require_non_whitespace(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Value must contain non-whitespace characters.")
        return cleaned


class AnalysisResponse(BaseModel):
    decision: ProcurementDecision
    trace: dict[str, object]


Analyzer = Callable[..., tuple[ProcurementDecision, dict[str, object]]]


def create_app(
    *,
    analyzer: Analyzer = run_single_agent,
    decisions_path: Path = DEFAULT_DECISIONS_PATH,
) -> FastAPI:
    application = FastAPI(title="AI Procurement Request Copilot API")
    store = DecisionStore(decisions_path)
    application.state.decision_store = store

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/requests")
    def requests_list() -> list[dict[str, object]]:
        return load_requests()

    @application.get("/api/requests/{request_id}")
    def request_detail(request_id: str) -> dict[str, object]:
        try:
            return get_request(request_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @application.post("/api/analyze", response_model=AnalysisResponse)
    def analyze(payload: AnalyzePayload) -> AnalysisResponse:
        if payload.request_id:
            try:
                request = ProcurementRequest.model_validate(
                    get_request(payload.request_id)
                )
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
        else:
            request = payload.request.to_request(payload.description or "")
        selected_mode = payload.mode or os.getenv("LLM_MODE", "live")
        try:
            if payload.architecture == "B":
                from agents.staged_agent import run_staged_agent

                decision, trace = run_staged_agent(request, mode=selected_mode)
            else:
                decision, trace = analyzer(request, mode=selected_mode)
        except LLMRunAborted as exc:
            raise HTTPException(
                status_code=429,
                detail=str(exc),
            ) from exc
        return AnalysisResponse(decision=decision, trace=trace)

    @application.get("/api/decisions", response_model=list[ReviewerDecision])
    def decisions_list(
        request_id: str | None = Query(default=None, min_length=1),
    ) -> list[ReviewerDecision]:
        try:
            return store.list(request_id=request_id)
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Could not read reviewer decisions: {exc}",
            ) from exc

    @application.post("/api/decisions", response_model=ReviewerDecision)
    def save_reviewer_decision(
        payload: ReviewerActionPayload,
    ) -> ReviewerDecision:
        try:
            return store.append(
                request_id=payload.request_id,
                action=payload.action,
                note=payload.note,
                reviewer=payload.reviewer,
                recommendation=payload.recommendation,
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Could not persist reviewer decision: {exc}",
            ) from exc

    return application


app = create_app()
