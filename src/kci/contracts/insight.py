from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from kci.contracts.finding import EntityReference


Significance = Literal["low", "medium", "high"]


class InsightCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    subjects: list[EntityReference] = Field(default_factory=list)
    significance: Significance
    title: str
    synthesis: str
    supporting_finding_ids: list[str]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("supporting_finding_ids")
    @classmethod
    def support_required_and_unique(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("InsightCandidate requires at least one supporting finding_id")
        if len(value) != len(set(value)):
            raise ValueError("InsightCandidate cannot contain duplicate supporting finding_id values")
        return value


class Insight(InsightCandidate):
    insight_id: str = Field(default_factory=lambda: f"insight_{uuid4().hex}")
    intelligence_context_id: str
    intelligence_run_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
