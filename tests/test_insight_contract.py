from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from kci.contracts import EntityReference, EvidenceReference, FindingCandidate, InsightCandidate
from kci.observers.production import ProductionObserver
from kci.persistence import KciRepository, connect, initialize_database
from kci.runtime import build_intelligence_context, promote_insight_candidate, run_observer
from tests.conftest import load_context


class SyntheticObserver(ProductionObserver):
    def __init__(self, observer_id: str, category: str, severity: str = "low") -> None:
        super().__init__()
        self.id = observer_id
        self.category = category
        self.synthetic_severity = severity

    def observe(self, context):
        dataset = context.datasets[0]
        return [
            FindingCandidate(
                category=self.category,
                subjects=[EntityReference(entity_type="machine", entity_id=str(dataset.scope["machine"]))],
                severity=self.synthetic_severity,
                title=f"{self.category} finding",
                observation="Synthetic Finding for Insight tests.",
                evidence=[
                    EvidenceReference(
                        dataset=dataset.dataset,
                        snapshot_id=dataset.snapshot_id,
                        ref=dataset.evidence_records[0].ref,
                    )
                ],
                metadata={"observer": self.id},
            )
        ]


def make_repo(tmp_path) -> KciRepository:
    connection = connect(tmp_path / "kci.sqlite3")
    initialize_database(connection)
    return KciRepository(connection)


def persist_finding(repository: KciRepository, observer, fixture: str):
    result = run_observer(observer, load_context(fixture), repository)
    assert result.findings
    return result.findings[0]


def setup_context(repository: KciRepository):
    f1 = persist_finding(repository, ProductionObserver(), "unexplained_downtime.json")
    f2 = persist_finding(
        repository,
        SyntheticObserver("maintenance.observer", "maintenance.recurring_failure", "high"),
        "mixed_problem.json",
    )
    f3 = persist_finding(
        repository,
        SyntheticObserver("projects.observer", "projects.schedule_risk", "low"),
        "normal_shift.json",
    )
    context = build_intelligence_context(repository, [f1.finding_id, f2.finding_id, f3.finding_id])
    return context, f1, f2, f3


def candidate(*finding_ids: str, significance: str = "medium", **updates) -> InsightCandidate:
    values = {
        "category": "operations.cross_domain_pattern",
        "subjects": [EntityReference(entity_type="machine", entity_id="M-FICTION-03")],
        "significance": significance,
        "title": "Cross-domain pattern",
        "synthesis": "A synthesized analytical claim across trusted Findings.",
        "supporting_finding_ids": list(finding_ids),
        "metadata": {"method": "synthetic-test"},
    }
    values.update(updates)
    return InsightCandidate(**values)


@pytest.mark.parametrize("field", ["category", "title", "synthesis", "significance"])
def test_insight_candidate_requires_core_claim_fields(field: str) -> None:
    values = {
        "category": "x",
        "title": "Title",
        "synthesis": "Synthesis",
        "significance": "low",
        "supporting_finding_ids": ["finding_1"],
    }
    values.pop(field)
    with pytest.raises(ValidationError):
        InsightCandidate(**values)


@pytest.mark.parametrize("value", ["low", "medium", "high"])
def test_significance_accepts_allowed_values(value: str) -> None:
    assert candidate("finding_1", significance=value).significance == value


def test_invalid_significance_rejected() -> None:
    with pytest.raises(ValidationError):
        candidate("finding_1", significance="critical")


def test_support_required_and_duplicates_rejected() -> None:
    with pytest.raises(ValidationError):
        candidate()
    with pytest.raises(ValidationError):
        candidate("finding_1", "finding_1")


def test_candidate_subjects_and_no_trusted_provenance_or_confidence() -> None:
    empty_subjects = candidate("finding_1", subjects=[])
    many_subjects = candidate(
        "finding_1",
        subjects=[
            EntityReference(entity_type="machine", entity_id="M-FICTION-03"),
            EntityReference(entity_type="line", entity_id="L-FICTION-01"),
        ],
    )

    assert empty_subjects.subjects == []
    assert len(many_subjects.subjects) == 2
    assert not hasattr(many_subjects, "confidence")
    assert not hasattr(many_subjects, "insight_id")
    assert not hasattr(many_subjects, "intelligence_context_id")
    assert not hasattr(many_subjects, "created_at")
    with pytest.raises(ValidationError):
        candidate("finding_1", confidence=0.9)


def test_promotion_creates_unique_insight_id_and_attaches_context_and_created_at(tmp_path) -> None:
    repository = make_repo(tmp_path)
    context, f1, _, f3 = setup_context(repository)
    first, failures = promote_insight_candidate(candidate(f1.finding_id, f3.finding_id), context, repository)
    second, second_failures = promote_insight_candidate(candidate(f1.finding_id, f3.finding_id), context, repository)

    assert failures == []
    assert second_failures == []
    assert first is not None and second is not None
    assert first.insight_id != second.insight_id
    assert first.intelligence_context_id == context.intelligence_context_id
    assert first.created_at is not None
    assert first.supporting_finding_ids == [f1.finding_id, f3.finding_id]


def test_support_must_exist_and_belong_to_exact_context(tmp_path) -> None:
    repository = make_repo(tmp_path)
    context, f1, _, _ = setup_context(repository)
    outside = persist_finding(repository, ProductionObserver(), "unexplained_downtime.json")

    missing_insight, missing_failures = promote_insight_candidate(candidate("finding_missing"), context, repository)
    outside_insight, outside_failures = promote_insight_candidate(candidate(f1.finding_id, outside.finding_id), context, repository)

    assert missing_insight is None
    assert "missing" in missing_failures[0].reason
    assert outside_insight is None
    assert "outside IntelligenceContext" in outside_failures[0].reason


def test_invalid_support_is_not_silently_removed(tmp_path) -> None:
    repository = make_repo(tmp_path)
    context, f1, _, _ = setup_context(repository)

    insight, failures = promote_insight_candidate(candidate(f1.finding_id, "finding_missing"), context, repository)

    assert insight is None
    assert failures
    assert repository.connection.execute("SELECT COUNT(*) FROM insights").fetchone()[0] == 0


def test_promotion_preserves_candidate_content_without_deriving_significance_or_subjects(tmp_path) -> None:
    repository = make_repo(tmp_path)
    context, _, f2, _ = setup_context(repository)
    insight, failures = promote_insight_candidate(
        candidate(
            f2.finding_id,
            significance="low",
            subjects=[EntityReference(entity_type="pattern", entity_id="P-FICTION-01")],
            title="Chosen title",
            synthesis="Chosen synthesis",
            metadata={"kept": True},
        ),
        context,
        repository,
    )

    assert failures == []
    assert insight is not None
    assert insight.category == "operations.cross_domain_pattern"
    assert insight.title == "Chosen title"
    assert insight.synthesis == "Chosen synthesis"
    assert insight.significance == "low"
    assert insight.subjects == [EntityReference(entity_type="pattern", entity_id="P-FICTION-01")]
    assert insight.metadata == {"kept": True}


def test_one_or_multiple_supporting_findings_are_valid_and_not_all_context_findings_required(tmp_path) -> None:
    repository = make_repo(tmp_path)
    context, f1, f2, f3 = setup_context(repository)

    one, one_failures = promote_insight_candidate(candidate(f1.finding_id), context, repository)
    many, many_failures = promote_insight_candidate(candidate(f1.finding_id, f3.finding_id), context, repository)

    assert one_failures == []
    assert many_failures == []
    assert one is not None and many is not None
    assert one.supporting_finding_ids == [f1.finding_id]
    assert many.supporting_finding_ids == [f1.finding_id, f3.finding_id]
    assert f2.finding_id not in many.supporting_finding_ids


def test_findings_from_multiple_runs_observers_and_domains_may_support_one_insight(tmp_path) -> None:
    repository = make_repo(tmp_path)
    context, f1, f2, f3 = setup_context(repository)
    insight, failures = promote_insight_candidate(candidate(f1.finding_id, f2.finding_id, f3.finding_id), context, repository)

    assert failures == []
    assert insight is not None
    assert len({f1.observer_run_id, f2.observer_run_id, f3.observer_run_id}) == 3
    assert len({f1.observer_id, f2.observer_id, f3.observer_id}) == 3
    assert {f1.category, f2.category, f3.category} == {
        "production.unexplained_downtime",
        "maintenance.recurring_failure",
        "projects.schedule_risk",
    }


def test_significance_is_independent_of_finding_severity(tmp_path) -> None:
    repository = make_repo(tmp_path)
    context, _, f2, _ = setup_context(repository)

    insight, failures = promote_insight_candidate(candidate(f2.finding_id, significance="low"), context, repository)

    assert failures == []
    assert insight is not None
    assert f2.severity == "high"
    assert insight.significance == "low"


def test_persistence_stores_insight_content_and_reference_only_support(tmp_path) -> None:
    repository = make_repo(tmp_path)
    context, f1, _, f3 = setup_context(repository)
    insight, failures = promote_insight_candidate(candidate(f1.finding_id, f3.finding_id), context, repository)
    assert failures == []
    assert insight is not None

    insights = [dict(row) for row in repository.connection.execute("SELECT * FROM insights")]
    subjects = [dict(row) for row in repository.connection.execute("SELECT insight_id, entity_type, entity_id FROM insight_subjects")]
    support = [dict(row) for row in repository.connection.execute("SELECT insight_id, finding_id FROM insight_findings ORDER BY finding_id")]
    support_columns = [row["name"] for row in repository.connection.execute("PRAGMA table_info(insight_findings)")]
    table_names = {row["name"] for row in repository.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert insights[0]["category"] == "operations.cross_domain_pattern"
    assert insights[0]["significance"] == "medium"
    assert insights[0]["title"] == "Cross-domain pattern"
    assert insights[0]["synthesis"] == "A synthesized analytical claim across trusted Findings."
    assert insights[0]["metadata_json"] == '{"method":"synthetic-test"}'
    assert subjects == [{"insight_id": insight.insight_id, "entity_type": "machine", "entity_id": "M-FICTION-03"}]
    assert [row["finding_id"] for row in support] == sorted([f1.finding_id, f3.finding_id])
    assert support_columns == ["insight_id", "finding_id"]
    assert "insight_evidence" not in table_names


def test_fk_integrity_duplicate_support_and_delete_behavior(tmp_path) -> None:
    repository = make_repo(tmp_path)
    context, f1, _, _ = setup_context(repository)
    insight, failures = promote_insight_candidate(candidate(f1.finding_id), context, repository)
    assert insight is not None and failures == []

    with pytest.raises(sqlite3.IntegrityError):
        repository.connection.execute(
            "INSERT INTO insight_findings (insight_id, finding_id) VALUES (?, ?)",
            (insight.insight_id, f1.finding_id),
        )
    with pytest.raises(sqlite3.IntegrityError):
        repository.connection.execute(
            "INSERT INTO insight_findings (insight_id, finding_id) VALUES (?, ?)",
            (insight.insight_id, "finding_missing"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        repository.connection.execute(
            "INSERT INTO insights (insight_id, intelligence_context_id, category, significance, title, synthesis, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("insight_bad", "missing_context", "x", "low", "t", "s", "{}", "2026-01-01T00:00:00+00:00"),
        )

    repository.connection.execute("DELETE FROM insights WHERE insight_id = ?", (insight.insight_id,))
    assert repository.connection.execute("SELECT COUNT(*) FROM findings WHERE finding_id = ?", (f1.finding_id,)).fetchone()[0] == 1
    assert repository.connection.execute(
        "SELECT COUNT(*) FROM intelligence_contexts WHERE intelligence_context_id = ?",
        (context.intelligence_context_id,),
    ).fetchone()[0] == 1


def test_existing_finding_observerrun_evidence_provenance_remains_traversable(tmp_path) -> None:
    repository = make_repo(tmp_path)
    context, f1, _, _ = setup_context(repository)
    insight, failures = promote_insight_candidate(candidate(f1.finding_id), context, repository)
    assert insight is not None and failures == []

    row = repository.connection.execute(
        """
        SELECT i.insight_id, f.finding_id, f.observer_run_id, e.dataset, e.snapshot_id, e.ref
        FROM insights i
        JOIN insight_findings ifs ON ifs.insight_id = i.insight_id
        JOIN findings f ON f.finding_id = ifs.finding_id
        JOIN evidence e ON e.finding_id = f.finding_id
        WHERE i.insight_id = ?
        ORDER BY e.ref
        """,
        (insight.insight_id,),
    ).fetchone()

    assert row["insight_id"] == insight.insight_id
    assert row["finding_id"] == f1.finding_id
    assert row["observer_run_id"] == f1.observer_run_id
    assert row["dataset"] == "synthetic.production.shift"


def test_insight_has_no_workflow_or_recommendation_fields(tmp_path) -> None:
    repository = make_repo(tmp_path)
    context, f1, _, _ = setup_context(repository)
    insight, failures = promote_insight_candidate(candidate(f1.finding_id), context, repository)
    assert insight is not None and failures == []

    forbidden = {
        "status",
        "review_status",
        "published",
        "dismissed",
        "confirmed",
        "superseded",
        "assigned_to",
        "due_date",
        "resolution",
        "action_priority",
        "recommendation",
        "next_action",
        "confidence",
    }
    assert forbidden.isdisjoint(type(insight).model_fields)
    assert insight.intelligence_run_id is None
