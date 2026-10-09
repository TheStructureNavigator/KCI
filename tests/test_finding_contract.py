from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from kci.contracts import DatasetEnvelope, EntityReference, EvidenceReference, Finding, FindingCandidate, ObservationContext
from kci.observers.production import ProductionObserver
from kci.persistence import KciRepository, connect, initialize_database
from kci.runtime import run_observer
from kci.runtime.validation import validate_candidates
from tests.conftest import load_context, load_fixture


def candidate_with_evidence(**updates) -> FindingCandidate:
    dataset = load_fixture("unexplained_downtime.json")
    values = {
        "category": "production.test",
        "severity": "low",
        "title": "Test finding",
        "observation": "A test analytical claim.",
        "evidence": [
            EvidenceReference(
                dataset=dataset.dataset,
                snapshot_id=dataset.snapshot_id,
                ref="event:unexplained:stop-001",
            )
        ],
        "metadata": {"measure": 1.2},
    }
    values.update(updates)
    return FindingCandidate(**values)


def test_finding_ids_are_unique_for_equivalent_findings_from_separate_runs() -> None:
    context = load_context("unexplained_downtime.json")

    first = run_observer(ProductionObserver(), context)
    second = run_observer(ProductionObserver(), context)

    assert first.findings[0].finding_id != second.findings[0].finding_id


def test_finding_points_to_exactly_one_observer_run() -> None:
    result = run_observer(ProductionObserver(), load_context("unexplained_downtime.json"))

    assert result.findings[0].observer_run_id == result.run.run_id


def test_finding_supports_zero_one_and_multiple_subjects() -> None:
    no_subject = candidate_with_evidence(subjects=[])
    one_subject = candidate_with_evidence(subjects=[EntityReference(entity_type="machine", entity_id="M-FICTION-01")])
    many_subjects = candidate_with_evidence(
        subjects=[
            EntityReference(entity_type="machine", entity_id="M-FICTION-01"),
            EntityReference(entity_type="line", entity_id="L-FICTION-01"),
        ]
    )

    assert no_subject.subjects == []
    assert one_subject.subjects[0].entity_type == "machine"
    assert [subject.entity_id for subject in many_subjects.subjects] == ["M-FICTION-01", "L-FICTION-01"]


@pytest.mark.parametrize("severity", ["low", "medium", "high"])
def test_allowed_severity_values(severity: str) -> None:
    assert candidate_with_evidence(severity=severity).severity == severity


def test_invalid_severity_is_rejected() -> None:
    with pytest.raises(ValidationError):
        candidate_with_evidence(severity="critical")


def test_finding_candidate_and_finding_do_not_expose_confidence() -> None:
    candidate = candidate_with_evidence()
    context = load_context("unexplained_downtime.json")
    findings, failures = validate_candidates([candidate], context, "run-1", "observer", "1")

    assert failures == []
    assert not hasattr(candidate, "confidence")
    assert not hasattr(findings[0], "confidence")
    with pytest.raises(ValidationError):
        candidate_with_evidence(confidence=0.95)


def test_production_observer_no_longer_emits_confidence() -> None:
    candidate = ProductionObserver().observe(load_context("unexplained_downtime.json"))[0]

    assert not hasattr(candidate, "confidence")


def test_zero_evidence_candidate_is_rejected_with_telemetry() -> None:
    class ZeroEvidenceObserver(ProductionObserver):
        def observe(self, context):
            return [
                FindingCandidate(
                    category="production.test",
                    severity="low",
                    title="No evidence",
                    observation="This must not promote.",
                    evidence=[],
                )
            ]

    result = run_observer(ZeroEvidenceObserver(), load_context("unexplained_downtime.json"))

    assert result.run.status == "succeeded"
    assert result.run.validation_failures_count == 1
    assert result.findings == []
    assert "requires evidence" in result.validation_failures[0].reason


def test_valid_evidence_from_exact_context_is_accepted_and_other_snapshot_rejected() -> None:
    context = load_context("unexplained_downtime.json")
    valid = candidate_with_evidence()
    invalid = candidate_with_evidence(
        evidence=[
            EvidenceReference(
                dataset=context.datasets[0].dataset,
                snapshot_id="other-snapshot",
                ref="event:unexplained:stop-001",
            )
        ]
    )

    findings, failures = validate_candidates([valid, invalid], context, "run-1", "observer", "1")

    assert len(findings) == 1
    assert len(failures) == 1


def test_one_finding_may_reference_multiple_evidence_records() -> None:
    result = run_observer(ProductionObserver(), load_context("unexplained_downtime.json"))

    assert len(result.findings[0].evidence) == 2


def test_one_finding_may_reference_evidence_from_multiple_datasets_in_same_context() -> None:
    primary = load_fixture("unexplained_downtime.json")
    secondary_payload = load_fixture("normal_shift.json").model_dump(mode="json")
    secondary_payload["dataset"] = "synthetic.production.shift.secondary"
    secondary_payload["content_hash"] = DatasetEnvelope.model_validate(secondary_payload).computed_content_hash()
    secondary = DatasetEnvelope.model_validate(secondary_payload)
    context = ObservationContext(datasets=(primary, secondary))
    candidate = candidate_with_evidence(
        evidence=[
            EvidenceReference(
                dataset=primary.dataset,
                snapshot_id=primary.snapshot_id,
                ref="event:unexplained:stop-001",
            ),
            EvidenceReference(
                dataset=secondary.dataset,
                snapshot_id=secondary.snapshot_id,
                ref="event:normal:planned-cleaning",
            ),
        ]
    )

    findings, failures = validate_candidates([candidate], context, "run-1", "observer", "1")

    assert failures == []
    assert len(findings[0].evidence) == 2


def test_runtime_does_not_copy_evidence_payload_or_invent_subjects() -> None:
    context = load_context("unexplained_downtime.json")
    candidate = candidate_with_evidence(subjects=[])

    findings, failures = validate_candidates([candidate], context, "run-1", "observer", "1")

    assert failures == []
    assert findings[0].subjects == []
    assert "duration_minutes" not in findings[0].model_dump_json()


def test_subject_is_distinct_from_evidence_and_scope() -> None:
    result = run_observer(ProductionObserver(), load_context("unexplained_downtime.json"))
    finding = result.findings[0]

    assert finding.subjects
    assert finding.subjects[0].entity_id == "M-FICTION-03"
    assert finding.subjects[0].entity_id != finding.evidence[0].ref
    assert finding.subjects[0].entity_type == "machine"


def test_created_at_is_artifact_time_and_finding_has_no_global_period_or_as_of() -> None:
    result = run_observer(ProductionObserver(), load_context("unexplained_downtime.json"))
    finding = result.findings[0]

    assert finding.created_at is not None
    assert "period" not in type(finding).model_fields
    assert "as_of" not in type(finding).model_fields


def test_metadata_remains_available_for_observer_specific_details() -> None:
    result = run_observer(ProductionObserver(), load_context("unexplained_downtime.json"))

    assert result.findings[0].metadata == {"total_unexplained_downtime_minutes": 38.0}


def test_production_observer_threshold_and_severity_semantics() -> None:
    context = load_context("unexplained_downtime.json")

    exact = run_observer(ProductionObserver(), context, requested_configuration={"threshold_minutes": 38})
    below = run_observer(ProductionObserver(), context, requested_configuration={"threshold_minutes": 39})

    assert exact.findings
    assert below.findings == []
    assert exact.findings[0].severity == "medium"


def test_production_observer_high_severity_at_or_above_60_minutes() -> None:
    payload = load_fixture("unexplained_downtime.json").model_dump(mode="json")
    payload["evidence_records"][0]["data"]["duration_minutes"] = 30
    payload["evidence_records"][1]["data"]["duration_minutes"] = 30
    payload["data"]["downtime_events"][0]["duration_minutes"] = 30
    payload["data"]["downtime_events"][1]["duration_minutes"] = 30
    payload["content_hash"] = DatasetEnvelope.model_validate(payload).computed_content_hash()
    context = ObservationContext(datasets=(DatasetEnvelope.model_validate(payload),))

    result = run_observer(ProductionObserver(), context, requested_configuration={"threshold_minutes": 30})

    assert result.findings[0].severity == "high"


def test_production_observer_wording_matches_greater_than_or_equal_semantics() -> None:
    result = run_observer(
        ProductionObserver(),
        load_context("unexplained_downtime.json"),
        requested_configuration={"threshold_minutes": 38},
    )

    assert "reaching or exceeding" in result.findings[0].observation
    assert "above the" not in result.findings[0].observation


def test_persistence_stores_subjects_without_confidence_or_evidence_payload(tmp_path) -> None:
    connection = connect(tmp_path / "kci.sqlite3")
    initialize_database(connection)
    repository = KciRepository(connection)
    result = run_observer(ProductionObserver(), load_context("unexplained_downtime.json"), repository)

    finding_row = connection.execute("SELECT * FROM findings WHERE finding_id = ?", (result.findings[0].finding_id,)).fetchone()
    subject_rows = connection.execute("SELECT entity_type, entity_id FROM finding_subjects").fetchall()
    evidence_rows = connection.execute("SELECT dataset, snapshot_id, ref FROM evidence").fetchall()

    assert "confidence" not in finding_row.keys()
    assert finding_row["observer_run_id"] == result.run.run_id
    assert [dict(row) for row in subject_rows] == [{"entity_type": "machine", "entity_id": "M-FICTION-03"}]
    assert len(evidence_rows) == 2
    assert "duration_minutes" not in json.dumps([dict(row) for row in evidence_rows])
