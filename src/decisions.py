from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.contracts import Recommendation
ReviewerAction = Literal["accept", "reject", "request_info"]


class ReviewerDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    request_id: str = Field(min_length=1)
    action: ReviewerAction
    note: str = Field(min_length=1, max_length=2000)
    reviewer: str = Field(min_length=1, max_length=200)
    recommendation: Recommendation
    created_at: datetime


class DecisionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def append(
        self,
        *,
        request_id: str,
        action: ReviewerAction,
        note: str,
        recommendation: Recommendation,
        reviewer: str = "Procurement reviewer",
    ) -> ReviewerDecision:
        cleaned_note = note.strip()
        if not cleaned_note:
            raise ValueError("Reviewer note is required.")
        cleaned_request_id = request_id.strip()
        if not cleaned_request_id:
            raise ValueError("Request id is required.")
        cleaned_reviewer = reviewer.strip()
        if not cleaned_reviewer:
            raise ValueError("Reviewer is required.")
        record = ReviewerDecision(
            decision_id=str(uuid4()),
            request_id=cleaned_request_id,
            action=action,
            note=cleaned_note,
            reviewer=cleaned_reviewer,
            recommendation=recommendation,
            created_at=datetime.now(UTC),
        )
        serialized = json.dumps(
            record.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=True,
        )
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as output:
                output.write(serialized + "\n")
        return record

    def list(self, request_id: str | None = None) -> list[ReviewerDecision]:
        if not self.path.exists():
            return []
        records: list[ReviewerDecision] = []
        with self.path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                try:
                    record = ReviewerDecision.model_validate_json(line)
                except ValueError as exc:
                    raise ValueError(
                        f"Invalid reviewer decision at line {line_number}: {exc}"
                    ) from exc
                if request_id is None or record.request_id == request_id:
                    records.append(record)
        return records
