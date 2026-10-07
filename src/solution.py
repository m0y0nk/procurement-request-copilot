from __future__ import annotations

from src.contracts import Architecture, ProcurementDecision


def handle_request(request_id: str, architecture: Architecture = "single") -> ProcurementDecision:
    """Assessment adapter.

    Keep this function callable by the public/hidden evaluation harness.
    Your internal implementation may use any framework, modules, agents, tools,
    deterministic checks, or orchestration strategy.
    """
    raise NotImplementedError(
        "Implement handle_request(...) as part of Assessment 3. "
        "Return a ProcurementDecision-compatible object."
    )
