from __future__ import annotations

import hashlib
import json

from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, field_validator

from kci.contracts.dataset import DatasetEnvelope


class ObservationIntegrityError(ValueError):
    """Base for observation-input integrity violations. Messages carry identities, never payloads."""


class SnapshotIntegrityError(ObservationIntegrityError):
    """A snapshot_id is reused with a different dataset, dataset_version or content_hash."""


class ObservationContextIntegrityError(ObservationIntegrityError):
    """A recorded observation manifest is inconsistent with its context_id."""


class DatasetReference(BaseModel):
    """Identity of one Dataset Snapshot in an ObservationContext. Never its content (Contract 002.8)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: str
    dataset_version: int
    snapshot_id: str
    content_hash: str


def compute_context_id(references: Iterable[DatasetReference]) -> str:
    """The single canonical context_id implementation (Contract 002.9): order-independent SHA-256."""
    entries = [
        {
            "dataset": reference.dataset,
            "dataset_version": reference.dataset_version,
            "snapshot_id": reference.snapshot_id,
            "content_hash": reference.content_hash,
        }
        for reference in references
    ]
    canonical = json.dumps(sorted(entries, key=lambda item: item["dataset"]), separators=(",", ":"), sort_keys=True)
    return f"context_sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


class ObservationContextManifest(BaseModel):
    """Immutable, canonical record of which Snapshots an ObservationContext contained.

    References are always held sorted by dataset name, so caller tuple order never matters.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    references: tuple[DatasetReference, ...] = Field(min_length=1)

    @field_validator("references")
    @classmethod
    def canonical_unique_references(cls, value: tuple[DatasetReference, ...]) -> tuple[DatasetReference, ...]:
        if len({reference.dataset for reference in value}) != len(value):
            raise ValueError("manifest accepts only one Snapshot per Dataset name")
        if len({reference.snapshot_id for reference in value}) != len(value):
            raise ValueError("manifest cannot contain the same snapshot_id twice")
        return tuple(sorted(value, key=lambda reference: reference.dataset))

    @property
    def context_id(self) -> str:
        return compute_context_id(self.references)


@dataclass(frozen=True)
class UnknownObservationContext:
    """Explicit result for a context_id with no recorded manifest (e.g. a legacy ObserverRun).

    Nothing is guessed: the datasets of such a run are unknown.
    """

    context_id: str
    reason: str = "no observation manifest was recorded"


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
        snapshots = [dataset.snapshot_id for dataset in value]
        if len(snapshots) != len(set(snapshots)):
            raise ValueError("ObservationContext cannot contain the same snapshot_id twice")
        return value

    def references(self) -> tuple[DatasetReference, ...]:
        return tuple(
            DatasetReference(
                dataset=dataset.dataset,
                dataset_version=dataset.dataset_version,
                snapshot_id=dataset.snapshot_id,
                content_hash=dataset.content_hash,
            )
            for dataset in self.datasets
        )

    def manifest(self) -> ObservationContextManifest:
        return ObservationContextManifest(references=self.references())

    @property
    def context_id(self) -> str:
        return compute_context_id(self.references())

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
