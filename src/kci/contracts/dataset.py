from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DatasetPeriod(BaseModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def end_must_not_precede_start(self) -> "DatasetPeriod":
        if self.end < self.start:
            raise ValueError("period end must not be earlier than period start")
        return self


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str
    data: dict[str, Any] = Field(default_factory=dict)


class DatasetEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema: str
    schema_version: str
    dataset: str
    dataset_version: int
    snapshot_id: str
    generated_at: datetime
    content_hash: str
    period: DatasetPeriod | None = None
    as_of: datetime | None = None
    scope: dict[str, Any] = Field(default_factory=dict)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)
    data: dict[str, Any]

    @model_validator(mode="after")
    def temporal_metadata_required(self) -> "DatasetEnvelope":
        if self.period is None and self.as_of is None:
            raise ValueError("DatasetEnvelope requires either period or as_of temporal metadata")
        return self

    def evidence_refs(self) -> set[str]:
        return {record.ref for record in self.evidence_records}

    def has_evidence_ref(self, ref: str) -> bool:
        return ref in self.evidence_refs()

    def computed_content_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude={"content_hash"}, by_alias=True)
        canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    def content_hash_valid(self) -> bool:
        return self.content_hash == self.computed_content_hash()
