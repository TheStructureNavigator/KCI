from __future__ import annotations

from kci.contracts import EvidenceReference, FindingCandidate
from kci.runtime.validation import validate_candidates
from tests.conftest import load_context


def test_invalid_nonexistent_evidence_is_rejected() -> None:
    context = load_context("normal_shift.json")
    dataset = context.datasets[0]
    candidate = FindingCandidate(
        category="production.test",
        severity="low",
        title="Invalid evidence",
        observation="The ref is not in the dataset.",
        evidence=[
            EvidenceReference(
                dataset=dataset.dataset,
                snapshot_id=dataset.snapshot_id,
                ref="event:does-not-exist",
            )
        ],
    )

    findings, failures = validate_candidates([candidate], context, "run-1", "test_observer", "0.0.1")

    assert findings == []
    assert len(failures) == 1
    assert "event:does-not-exist" in failures[0].reason


def test_wrong_dataset_evidence_is_rejected() -> None:
    context = load_context("normal_shift.json")
    dataset = context.datasets[0]
    candidate = FindingCandidate(
        category="production.test",
        severity="low",
        title="Wrong dataset",
        observation="The dataset is not in the ObservationContext.",
        evidence=[
            EvidenceReference(
                dataset="synthetic.production.other",
                snapshot_id=dataset.snapshot_id,
                ref="event:normal:planned-cleaning",
            )
        ],
    )

    findings, failures = validate_candidates([candidate], context, "run-1", "test_observer", "0.0.1")

    assert findings == []
    assert len(failures) == 1


def test_wrong_snapshot_evidence_is_rejected() -> None:
    context = load_context("normal_shift.json")
    dataset = context.datasets[0]
    candidate = FindingCandidate(
        category="production.test",
        severity="low",
        title="Wrong snapshot",
        observation="The snapshot does not match the ObservationContext.",
        evidence=[
            EvidenceReference(
                dataset=dataset.dataset,
                snapshot_id="other-snapshot",
                ref="event:normal:planned-cleaning",
            )
        ],
    )

    findings, failures = validate_candidates([candidate], context, "run-1", "test_observer", "0.0.1")

    assert findings == []
    assert len(failures) == 1


def test_valid_evidence_reference_is_promoted() -> None:
    context = load_context("normal_shift.json")
    dataset = context.datasets[0]
    candidate = FindingCandidate(
        category="production.test",
        severity="low",
        title="Valid evidence",
        observation="The evidence ref is explicit in the Dataset Snapshot.",
        evidence=[
            EvidenceReference(
                dataset=dataset.dataset,
                snapshot_id=dataset.snapshot_id,
                ref="event:normal:planned-cleaning",
            )
        ],
    )

    findings, failures = validate_candidates([candidate], context, "run-1", "test_observer", "0.0.1")

    assert failures == []
    assert len(findings) == 1
    assert findings[0].observer_run_id == "run-1"
