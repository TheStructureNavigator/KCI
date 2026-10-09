from __future__ import annotations

import pytest
from pydantic import ValidationError

from kci.contracts import DatasetEnvelope, EntityReference, EvidenceReference, FindingCandidate
from tests.conftest import load_fixture


def test_dataset_envelope_validation() -> None:
    dataset = load_fixture("normal_shift.json")

    assert dataset.dataset == "synthetic.production.shift"
    assert "event:normal:planned-cleaning" in dataset.evidence_refs()
    assert dataset.content_hash_valid()


def test_arbitrary_nested_ref_does_not_become_evidence() -> None:
    dataset = load_fixture("normal_shift.json")
    payload = dataset.model_dump(mode="json")
    payload["data"]["not_evidence"] = {"ref": "not:evidence"}
    payload["content_hash"] = DatasetEnvelope.model_validate(payload).computed_content_hash()
    changed = DatasetEnvelope.model_validate(payload)

    assert "not:evidence" not in changed.evidence_refs()


def test_content_hash_mismatch_is_detected() -> None:
    payload = load_fixture("normal_shift.json").model_dump(mode="json")
    payload["data"]["summary"]["oee"] = 0.01
    changed = DatasetEnvelope.model_validate(payload)

    assert not changed.content_hash_valid()


def test_finding_candidate_can_represent_untrusted_zero_evidence_output() -> None:
    candidate = FindingCandidate(
        category="production.test",
        severity="low",
        title="No evidence candidate",
        observation="Runtime must reject this during promotion.",
        evidence=[],
    )

    assert candidate.evidence == []


def test_finding_candidate_rejects_generic_confidence() -> None:
    with pytest.raises(ValidationError):
        FindingCandidate(
            category="production.test",
            severity="low",
            title="Generic confidence",
            observation="Contract 004 forbids global confidence.",
            evidence=[
                EvidenceReference(
                    dataset="synthetic.production.shift",
                    snapshot_id="snapshot",
                    ref="ref",
                )
            ],
            confidence=1.5,
        )


def test_entity_reference_is_minimal_reference() -> None:
    subject = EntityReference(entity_type="machine", entity_id="M-FICTION-01")

    assert subject.entity_type == "machine"
    assert subject.entity_id == "M-FICTION-01"
