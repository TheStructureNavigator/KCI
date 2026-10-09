from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from kci.contracts import EntityReference, EvidenceReference, FindingCandidate, IntelligenceContext
from kci.observers.production import ProductionObserver
from kci.persistence import KciRepository, connect, initialize_database
from kci.runtime import IntelligenceContextConstructionError, build_intelligence_context, run_observer
from tests.conftest import load_context


class CategoryObserver(ProductionObserver):
    id = "synthetic.category_observer"

    def __init__(self, category: str, severity: str = "low") -> None:
        super().__init__()
        self.category = category
        self.test_severity = severity

    def observe(self, context):
        dataset = context.datasets[0]
        subjects = []
        machine = dataset.scope.get("machine")
        if isinstance(machine, str):
            subjects.append(EntityReference(entity_type="machine", entity_id=machine))
        return [
            FindingCandidate(
                category=self.category,
                subjects=subjects,
                severity=self.test_severity,
                title=f"{self.category} finding",
                observation="Synthetic trusted finding for IntelligenceContext tests.",
                evidence=[
                    EvidenceReference(
                        dataset=dataset.dataset,
                        snapshot_id=dataset.snapshot_id,
                        ref=dataset.evidence_records[0].ref,
                    )
                ],
                metadata={"source": "test"},
            )
        ]


def make_repository(tmp_path) -> KciRepository:
    connection = connect(tmp_path / "kci.sqlite3")
    initialize_database(connection)
    return KciRepository(connection)


def persist_finding(repository: KciRepository, observer=None, fixture: str = "unexplained_downtime.json"):
    result = run_observer(observer or ProductionObserver(), load_context(fixture), repository)
    assert result.findings
    return result.findings[0]


def test_intelligence_context_requires_at_least_one_finding() -> None:
    with pytest.raises(ValidationError):
        IntelligenceContext(finding_ids=())


def test_same_finding_set_has_order_independent_identity(tmp_path) -> None:
    repository = make_repository(tmp_path)
    first = persist_finding(repository)
    second = persist_finding(repository, fixture="mixed_problem.json")

    context_a = build_intelligence_context(repository, [first.finding_id, second.finding_id])
    context_b = build_intelligence_context(repository, [second.finding_id, first.finding_id])

    assert context_a.intelligence_context_id == context_b.intelligence_context_id


def test_adding_removing_or_replacing_finding_changes_identity(tmp_path) -> None:
    repository = make_repository(tmp_path)
    first = persist_finding(repository)
    second = persist_finding(repository, fixture="mixed_problem.json")
    replacement = persist_finding(repository)

    both = build_intelligence_context(repository, [first.finding_id, second.finding_id])
    first_only = build_intelligence_context(repository, [first.finding_id])
    replaced = build_intelligence_context(repository, [replacement.finding_id, second.finding_id])

    assert both.intelligence_context_id != first_only.intelligence_context_id
    assert both.intelligence_context_id != replaced.intelligence_context_id


def test_semantically_identical_findings_with_different_ids_change_identity(tmp_path) -> None:
    repository = make_repository(tmp_path)
    first = persist_finding(repository)
    second = persist_finding(repository)

    assert first.category == second.category
    assert first.finding_id != second.finding_id
    assert build_intelligence_context(repository, [first.finding_id]).intelligence_context_id != (
        build_intelligence_context(repository, [second.finding_id]).intelligence_context_id
    )


def test_duplicate_finding_id_request_is_rejected_without_deduplication(tmp_path) -> None:
    repository = make_repository(tmp_path)
    finding = persist_finding(repository)

    with pytest.raises(IntelligenceContextConstructionError, match="duplicate"):
        build_intelligence_context(repository, [finding.finding_id, finding.finding_id])


def test_missing_finding_id_rejects_without_partial_context(tmp_path) -> None:
    repository = make_repository(tmp_path)
    finding = persist_finding(repository)

    with pytest.raises(IntelligenceContextConstructionError, match="missing"):
        build_intelligence_context(repository, [finding.finding_id, "finding_missing"])

    count = repository.connection.execute("SELECT COUNT(*) FROM intelligence_contexts").fetchone()[0]
    assert count == 0


def test_candidates_and_arbitrary_claim_dicts_cannot_be_context_members(tmp_path) -> None:
    repository = make_repository(tmp_path)
    candidate = FindingCandidate(
        category="synthetic",
        severity="low",
        title="candidate",
        observation="not trusted",
        evidence=[],
    )

    with pytest.raises(IntelligenceContextConstructionError):
        build_intelligence_context(repository, [candidate])  # type: ignore[list-item]
    with pytest.raises(IntelligenceContextConstructionError):
        build_intelligence_context(repository, [{"finding_id": "finding_1"}])  # type: ignore[list-item]


def test_cross_origin_findings_can_coexist(tmp_path) -> None:
    repository = make_repository(tmp_path)
    production = persist_finding(repository, ProductionObserver(), "unexplained_downtime.json")
    maintenance = persist_finding(repository, CategoryObserver("maintenance.recurring_failure", "high"), "mixed_problem.json")
    projects = persist_finding(repository, CategoryObserver("projects.schedule_risk", "medium"), "normal_shift.json")

    context = build_intelligence_context(
        repository,
        [production.finding_id, maintenance.finding_id, projects.finding_id],
    )

    findings = repository.get_findings_by_ids(context.finding_ids)
    assert {finding.observer_run_id for finding in findings.values()} == {
        production.observer_run_id,
        maintenance.observer_run_id,
        projects.observer_run_id,
    }
    assert {finding.category for finding in findings.values()} == {
        "production.unexplained_downtime",
        "maintenance.recurring_failure",
        "projects.schedule_risk",
    }
    assert {finding.severity for finding in findings.values()} == {"medium", "high"}
    assert {finding.subjects[0].entity_id for finding in findings.values() if finding.subjects} >= {
        "M-FICTION-03",
        "M-FICTION-05",
        "M-FICTION-01",
    }


def test_context_does_not_require_common_temporal_metadata_or_expose_selection_semantics(tmp_path) -> None:
    repository = make_repository(tmp_path)
    first = persist_finding(repository, fixture="unexplained_downtime.json")
    second = persist_finding(repository, fixture="mixed_problem.json")

    context = build_intelligence_context(repository, [first.finding_id, second.finding_id])

    assert "period" not in type(context).model_fields
    assert "as_of" not in type(context).model_fields
    assert "generated_at" not in type(context).model_fields
    assert "selection_reason" not in type(context).model_fields
    assert "purpose" not in type(context).model_fields
    assert "goal" not in type(context).model_fields


def test_context_persistence_stores_finding_references_only(tmp_path) -> None:
    repository = make_repository(tmp_path)
    first = persist_finding(repository)
    second = persist_finding(repository, fixture="mixed_problem.json")
    context = build_intelligence_context(repository, [first.finding_id, second.finding_id])

    context_columns = [
        row["name"] for row in repository.connection.execute("PRAGMA table_info(intelligence_contexts)")
    ]
    membership_columns = [
        row["name"] for row in repository.connection.execute("PRAGMA table_info(intelligence_context_findings)")
    ]
    table_names = {
        row["name"] for row in repository.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }

    assert context_columns == ["intelligence_context_id", "created_at"]
    assert membership_columns == ["intelligence_context_id", "finding_id"]
    assert "intelligence_context_evidence" not in table_names
    assert repository.get_intelligence_context_finding_ids(context.intelligence_context_id) == sorted(
        [first.finding_id, second.finding_id]
    )


def test_foreign_keys_and_duplicate_membership_are_enforced(tmp_path) -> None:
    repository = make_repository(tmp_path)
    finding = persist_finding(repository)
    context = build_intelligence_context(repository, [finding.finding_id])

    with pytest.raises(sqlite3.IntegrityError):
        repository.connection.execute(
            """
            INSERT INTO intelligence_context_findings (intelligence_context_id, finding_id)
            VALUES (?, ?)
            """,
            (context.intelligence_context_id, "finding_missing"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        repository.connection.execute(
            """
            INSERT INTO intelligence_context_findings (intelligence_context_id, finding_id)
            VALUES (?, ?)
            """,
            (context.intelligence_context_id, finding.finding_id),
        )


def test_reconstructing_same_set_is_logically_idempotent(tmp_path) -> None:
    repository = make_repository(tmp_path)
    first = persist_finding(repository)
    second = persist_finding(repository, fixture="mixed_problem.json")

    context_a = build_intelligence_context(repository, [first.finding_id, second.finding_id])
    context_b = build_intelligence_context(repository, [second.finding_id, first.finding_id])

    assert context_a.intelligence_context_id == context_b.intelligence_context_id
    assert repository.connection.execute("SELECT COUNT(*) FROM intelligence_contexts").fetchone()[0] == 1
    assert repository.connection.execute("SELECT COUNT(*) FROM intelligence_context_findings").fetchone()[0] == 2


def test_created_at_does_not_affect_identity() -> None:
    first = IntelligenceContext(finding_ids=("finding_a",), created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    second = IntelligenceContext(finding_ids=("finding_a",), created_at=datetime(2026, 1, 2, tzinfo=timezone.utc))

    assert first.intelligence_context_id == second.intelligence_context_id


def test_context_performs_no_io_or_analysis_itself() -> None:
    context = IntelligenceContext(finding_ids=("finding_a",))

    assert not hasattr(context, "run")
    assert not hasattr(context, "analyze")
    assert not hasattr(context, "ask_uatu")


def test_existing_finding_provenance_and_evidence_are_unchanged(tmp_path) -> None:
    repository = make_repository(tmp_path)
    finding = persist_finding(repository)
    before = repository.list_findings()[0]

    build_intelligence_context(repository, [finding.finding_id])
    after = repository.list_findings()[0]

    assert before.finding_id == after.finding_id
    assert before.observer_run_id == after.observer_run_id
    assert before.evidence == after.evidence
