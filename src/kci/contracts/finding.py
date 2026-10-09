from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


Severity = Literal["low", "medium", "high"]


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str
    snapshot_id: str
    ref: str


class EntityReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: str
    entity_id: str


class FindingCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    subjects: list[EntityReference] = Field(default_factory=list)
    severity: Severity
    title: str
    observation: str
    evidence: list[EvidenceReference]
    metadata: dict[str, Any] = Field(default_factory=dict)

class Finding(FindingCandidate):
    finding_id: str = Field(default_factory=lambda: f"finding_{uuid4().hex}")
    observer_run_id: str
    observer_id: str
    observer_version: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("evidence")
    @classmethod
    def evidence_required(cls, value: list[EvidenceReference]) -> list[EvidenceReference]:
        if not value:
            raise ValueError("findings require at least one evidence reference")
        return value
