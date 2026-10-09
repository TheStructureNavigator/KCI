from __future__ import annotations

from kci.contracts import DatasetRequirement, EntityReference, EvidenceReference, FindingCandidate, ObservationContext
from kci.observers.base import Observer


class ProductionObserver(Observer):
    id = "production.unexplained_downtime"
    version = "1"
    required_datasets = (DatasetRequirement(dataset="synthetic.production.shift", dataset_versions=(1,)),)
    deterministic = True

    def __init__(self, threshold_minutes: int = 30, unexplained_downtime_threshold_minutes: int | None = None) -> None:
        if unexplained_downtime_threshold_minutes is not None:
            threshold_minutes = unexplained_downtime_threshold_minutes
        self.threshold_minutes = threshold_minutes

    def effective_configuration(self, requested_configuration: dict[str, object] | None = None) -> dict[str, int]:
        effective = {"threshold_minutes": self.threshold_minutes}
        if requested_configuration:
            unknown = set(requested_configuration) - {"threshold_minutes"}
            if unknown:
                raise ValueError(f"unsupported observer configuration key(s): {', '.join(sorted(unknown))}")
            effective["threshold_minutes"] = int(requested_configuration["threshold_minutes"])
        return effective

    def apply_configuration(self, effective_configuration: dict[str, object]) -> None:
        self.threshold_minutes = int(effective_configuration["threshold_minutes"])

    def observe(self, context: ObservationContext) -> list[FindingCandidate]:
        dataset = context.require_dataset(self.required_datasets[0].dataset)
        events = dataset.data.get("downtime_events", [])
        if not isinstance(events, list):
            raise ValueError("downtime_events must be a list")

        unexplained = []
        total_minutes = 0.0
        for event in events:
            if not isinstance(event, dict):
                continue
            category = str(event.get("category", "")).lower()
            duration = float(event.get("duration_minutes", 0) or 0)
            if category == "unexplained":
                total_minutes += duration
                if isinstance(event.get("evidence_ref"), str):
                    unexplained.append(event)

        if total_minutes < self.threshold_minutes:
            return []

        evidence = [
            EvidenceReference(dataset=dataset.dataset, snapshot_id=dataset.snapshot_id, ref=event["evidence_ref"])
            for event in unexplained
        ]
        subjects = []
        machine = dataset.scope.get("machine")
        if isinstance(machine, str) and machine:
            subjects.append(EntityReference(entity_type="machine", entity_id=machine))

        return [
            FindingCandidate(
                category="production.unexplained_downtime",
                subjects=subjects,
                severity="medium" if total_minutes < 60 else "high",
                title="Unexplained downtime exceeded threshold",
                observation=(
                    f"Unexplained downtime totaled {total_minutes:g} minutes, "
                    f"reaching or exceeding the {self.threshold_minutes} minute threshold."
                ),
                evidence=evidence,
                metadata={"total_unexplained_downtime_minutes": total_minutes},
            )
        ]
