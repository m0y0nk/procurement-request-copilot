from __future__ import annotations

from typing import Any, Literal

from eval.case_models import EvaluationCase
from src.contracts import ArchitectureLabel
from tools.procurement import ProcurementTools

Mode = Literal["live", "replay"]


def run_case(
    case: EvaluationCase,
    architecture: ArchitectureLabel,
    mode: Mode,
) -> dict[str, Any]:
    if architecture != "A":
        raise ValueError("Architecture B is not implemented in Phase 3.")

    from agents.single_agent import run_single_agent

    tools = ProcurementTools(
        vendor_base_url=(
            "http://127.0.0.1:1" if case.fixture.vendor_service_unavailable else None
        ),
        timeout_seconds=0.05,
        retry_backoff_seconds=0,
    )
    decision, trace = run_single_agent(
        case.procurement_request(),
        mode=mode,
        tools=tools,
        additional_untrusted_texts=[
            case.request,
            *case.fixture.additional_untrusted_texts,
        ],
    )
    return {**trace, "decision": decision.model_dump(mode="json")}
