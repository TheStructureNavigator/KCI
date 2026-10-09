from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IntelligenceContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    finding_ids: tuple[str, ...] = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("finding_ids")
    @classmethod
    def unique_finding_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("IntelligenceContext cannot contain duplicate finding_id values")
        return value

    @property
    def intelligence_context_id(self) -> str:
        canonical = json.dumps(sorted(self.finding_ids), separators=(",", ":"), sort_keys=True)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"intelligence_context_sha256:{digest}"
