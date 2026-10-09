from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field, field_validator

from kci.contracts.dataset import DatasetEnvelope


class DatasetRequirement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: str
    dataset_versions: tuple[int, ...]

    @field_validator("dataset_versions")
    @classmethod
    def versions_required(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if not value:
            raise ValueError("at least one supported dataset version is required")
        return value


class ObservationContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    datasets: tuple[DatasetEnvelope, ...] = Field(min_length=1)

    @field_validator("datasets")
    @classmethod
    def unique_dataset_names(cls, value: tuple[DatasetEnvelope, ...]) -> tuple[DatasetEnvelope, ...]:
        names = [dataset.dataset for dataset in value]
        if len(names) != len(set(names)):
            raise ValueError("ObservationContext currently accepts only one Snapshot per Dataset name")
        return value

    @property
    def context_id(self) -> str:
        entries = [
            {
                "dataset": dataset.dataset,
                "dataset_version": dataset.dataset_version,
                "snapshot_id": dataset.snapshot_id,
                "content_hash": dataset.content_hash,
            }
            for dataset in self.datasets
        ]
        canonical = json.dumps(sorted(entries, key=lambda item: item["dataset"]), separators=(",", ":"), sort_keys=True)
        return f"context_sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"

    def require_dataset(self, dataset: str) -> DatasetEnvelope:
        for envelope in self.datasets:
            if envelope.dataset == dataset:
                return envelope
        raise ValueError(f"required dataset not supplied: {dataset}")

    def has_evidence(self, dataset: str, snapshot_id: str, ref: str) -> bool:
        try:
            envelope = self.require_dataset(dataset)
        except ValueError:
            return False
        return envelope.snapshot_id == snapshot_id and envelope.has_evidence_ref(ref)
