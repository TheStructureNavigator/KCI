from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


RunStatus = Literal["succeeded", "failed", "requirements_failed"]


class ObserverRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: f"observer_run_{uuid4().hex}")
    observer_id: str
    observer_version: str
    context_id: str
    effective_configuration: dict[str, Any] = Field(default_factory=dict)
    dataset: str
    snapshot_id: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: float | None = None
    status: RunStatus
    failure_category: str | None = None
    candidates_count: int = 0
    findings_count: int = 0
    validation_failures_count: int = 0
    model_runs_count: int = 0
    error: str | None = None

    @classmethod
    def started(
        cls,
        observer_id: str,
        observer_version: str,
        context_id: str,
        effective_configuration: dict[str, Any],
        dataset: str,
        snapshot_id: str,
    ) -> "ObserverRun":
        return cls(
            observer_id=observer_id,
            observer_version=observer_version,
            context_id=context_id,
            effective_configuration=effective_configuration,
            dataset=dataset,
            snapshot_id=snapshot_id,
            started_at=datetime.now(timezone.utc),
            status="failed",
        )


class IntelligenceRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: f"intelligence_run_{uuid4().hex}")
    operation_id: str
    operation_version: str
    deterministic: bool
    intelligence_context_id: str
    effective_configuration: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: float | None = None
    status: RunStatus
    failure_category: str | None = None
    candidates_count: int = 0
    promoted_count: int = 0
    rejected_count: int = 0
    model_runs_count: int = 0
    error: str | None = None

    @classmethod
    def started(
        cls,
        operation_id: str,
        operation_version: str,
        deterministic: bool,
        intelligence_context_id: str,
        effective_configuration: dict[str, Any],
    ) -> "IntelligenceRun":
        return cls(
            operation_id=operation_id,
            operation_version=operation_version,
            deterministic=deterministic,
            intelligence_context_id=intelligence_context_id,
            effective_configuration=effective_configuration,
            started_at=datetime.now(timezone.utc),
            status="failed",
        )


class ModelRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: f"model_run_{uuid4().hex}")
    observer_run_id: str | None = None
    intelligence_run_id: str | None = None
    provider: str
    model: str | None = None
    model_artifact_hash: str | None = None
    quantization: str | None = None
    inference_parameters: dict[str, Any] = Field(default_factory=dict)
    prompt_version: str | None = None
    context_size: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    model_load_ms: float | None = None
    prompt_eval_ms: float | None = None
    generation_ms: float | None = None
    total_ms: float | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    prompt_tokens_per_second: float | None = None
    generation_tokens_per_second: float | None = None
    peak_memory_mb: float | None = None
    status: RunStatus
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def exactly_one_parent_run(self) -> "ModelRun":
        parents = [self.observer_run_id is not None, self.intelligence_run_id is not None]
        if sum(parents) != 1:
            raise ValueError("ModelRun requires exactly one parent: observer_run_id or intelligence_run_id")
        return self
