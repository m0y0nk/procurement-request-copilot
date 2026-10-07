from __future__ import annotations

from src.contracts import EvidenceItem
from tools.procurement import ToolCallRecord


def grounded_evidence(
    evidence: list[EvidenceItem],
    tool_calls: list[ToolCallRecord],
) -> tuple[list[EvidenceItem], int]:
    records = {
        call.tool_call_id: set(call.record_refs)
        for call in tool_calls
        if call.status == "success"
    }
    grounded: list[EvidenceItem] = []
    dropped = 0
    for item in evidence:
        if item.tool_call_id in records and item.record_ref in records[item.tool_call_id]:
            grounded.append(item)
        else:
            dropped += 1
    return grounded, dropped
