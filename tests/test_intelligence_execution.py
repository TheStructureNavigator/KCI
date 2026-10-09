from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from kci.contracts import EntityReference, EvidenceReference, FindingCandidate, InsightCandidate, IntelligenceContext, ModelRun
from kci.operations import IntelligenceOperation
from kci.observers.production import ProductionObserver
from kci.persistence import KciRepository, connect, initialize_database
from kci.runtime import build_intelligence_context, run_intelligence_operation, run_observer
from tests.conftest import load_context


class SyntheticOperation(IntelligenceOperation):
    operation_id = "synthetic.cross_domain_synthesis"
    operation_version = "1"
    deterministic = True

    def __init__(self, candidates: list[InsightCandidate] | None = None, fail: bool = False) -> None:
        self.candidates = candidates or []
        self.fail = fail
        self.invoked = False
        self.received_context: IntelligenceContext | None = None
        self.received_configuration: dict[str, Any] | None = None

    def effective_configuration(self, requested_configuration: dict[str, Any] | None = None) -> dict[str, Any]:
        effective = {"minimum_support": 1}
        if requested_configuration:
            effective.update(requested_configuration)
        return effective

    def synthesize(self, context: IntelligenceContext, configuration: dict[str, Any]) -> list[InsightCandidate]:
        self.invoked = True
        self.received_context = context
        self.received_configuration = dict(configuration)
        if self.fail:
            raise RuntimeError("synthetic operation failed")
        return self.candidates


class NonDeterministicOperation(SyntheticOperation):
    operation_id = "synthetic.model_assisted"
    deterministic = False


class OtherObserver(ProductionObserver):
    def __init__(self, observer_id: str, category: str, severity: str = "medium") -> None:
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
                observation="Synthetic finding for intelligence execution tests.",
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


class FailingInsightRepository(KciRepository):
    def save_insight(self, insight):
        raise RuntimeError("database write failed")


def make_repo(tmp_path, repo_cls=KciRepository):
    connection = connect(tmp_path / "kci.sqlite3")
    initialize_database(connection)
    return repo_cls(connection)


def persisted_findings_and_context(repository: KciRepository):
    f1 = run_observer(ProductionObserver(), load_context("unexplained_downtime.json"), repository).findings[0]
    f2 = run_observer(
        OtherObserver("maintenance.observer", "maintenance.recurring_failure", "high"),
        load_context("mixed_problem.json"),
        repository,
    ).findings[0]
    f3 = run_observer(
        OtherObserver("projects.observer", "projects.schedule_risk", "low"),
        load_context("normal_shift.json"),
        repository,
    ).findings[0]
    context = build_intelligence_context(repository, [f1.finding_id, f2.finding_id, f3.finding_id])
    return context, f1, f2, f3


def insight_candidate(*finding_ids: str, significance: str = "medium", **updates) -> InsightCandidate:
    values = {
        "category": "operations.cross_domain_pattern",
        "subjects": [EntityReference(entity_type="machine", entity_id="M-FICTION-03")],
        "significance": significance,
        "title": "Cross-domain pattern",
        "synthesis": "Equivalent synthetic synthesis.",
        "supporting_finding_ids": list(finding_ids),
        "metadata": {"source": "test"},
    }
    values.update(updates)
    return InsightCandidate(**values)


def test_operation_identity_version_determinism_and_unit_test_shape() -> None:
    op = SyntheticOperation()
    context = IntelligenceContext(finding_ids=("finding_a",))

    assert op.operation_id == "synthetic.cross_domain_synthesis"
    assert op.operation_version == "1"
    assert op.deterministic is True
    assert op.synthesize(context, {"minimum_support": 1}) == []
    assert op.received_context == context


def test_defaults_resolved_and_persisted_not_requested_only(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context, f1, _, _ = persisted_findings_and_context(repo)
    result = run_intelligence_operation(SyntheticOperation([insight_candidate(f1.finding_id)]), context, repo)

    row = repo.connection.execute(
        "SELECT operation_id, operation_version, deterministic, intelligence_context_id, effective_configuration_json FROM intelligence_runs WHERE run_id = ?",
        (result.run.run_id,),
    ).fetchone()

    assert row["operation_id"] == "synthetic.cross_domain_synthesis"
    assert row["operation_version"] == "1"
    assert row["deterministic"] == 1
    assert row["intelligence_context_id"] == context.intelligence_context_id
    assert row["effective_configuration_json"] == '{"minimum_support":1}'


def test_separate_runs_have_unique_ids_and_different_configs(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context, f1, _, _ = persisted_findings_and_context(repo)
    first = run_intelligence_operation(SyntheticOperation([insight_candidate(f1.finding_id)]), context, repo)
    second = run_intelligence_operation(
        SyntheticOperation([insight_candidate(f1.finding_id)]),
        context,
        repo,
        requested_configuration={"minimum_support": 2},
    )

    assert first.run.run_id != second.run.run_id
    assert first.run.effective_configuration == {"minimum_support": 1}
    assert second.run.effective_configuration == {"minimum_support": 2}


def test_zero_candidate_execution_is_success(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context, _, _, _ = persisted_findings_and_context(repo)
    result = run_intelligence_operation(SyntheticOperation([]), context, repo)

    assert result.run.status == "succeeded"
    assert result.run.candidates_count == 0
    assert result.run.promoted_count == 0
    assert result.run.rejected_count == 0


def test_precondition_failure_does_not_invoke_operation_and_is_distinct(tmp_path) -> None:
    repo = make_repo(tmp_path)
    op = SyntheticOperation()
    missing_context = IntelligenceContext(finding_ids=("finding_missing",))

    result = run_intelligence_operation(op, missing_context, repo)

    assert op.invoked is False
    assert result.run.status == "requirements_failed"
    assert result.run.failure_category == "requirements"


def test_operation_exception_preserves_failed_started_run(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context, _, _, _ = persisted_findings_and_context(repo)
    op = SyntheticOperation(fail=True)

    result = run_intelligence_operation(op, context, repo)

    assert op.invoked is True
    assert result.run.status == "failed"
    assert result.run.failure_category == "execution"
    assert result.run.finished_at is not None
    assert result.run.duration_ms is not None
    persisted = repo.connection.execute("SELECT status, error FROM intelligence_runs WHERE run_id = ?", (result.run.run_id,)).fetchone()
    assert persisted["status"] == "failed"
    assert "synthetic operation failed" in persisted["error"]


def test_per_candidate_acceptance_partial_and_all_invalid(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context, f1, f2, f3 = persisted_findings_and_context(repo)
    outside = run_observer(ProductionObserver(), load_context("unexplained_downtime.json"), repo).findings[0]
    candidates = [
        insight_candidate(f1.finding_id),
        insight_candidate(outside.finding_id, title="outside"),
        insight_candidate(f2.finding_id, f3.finding_id),
    ]

    result = run_intelligence_operation(SyntheticOperation(candidates), context, repo)

    assert result.run.status == "succeeded"
    assert result.run.candidates_count == 3
    assert result.run.promoted_count == 2
    assert result.run.rejected_count == 1
    assert [failure[0] for failure in result.validation_failures] == [1]
    assert len(result.insights) == 2
    assert all(insight.intelligence_run_id == result.run.run_id for insight in result.insights)
    rows = repo.connection.execute("SELECT candidate_index, failure_category, detail FROM intelligence_candidate_rejections").fetchall()
    assert [dict(row) for row in rows] == [
        {
            "candidate_index": 1,
            "failure_category": "validation",
            "detail": f"supporting finding_id value(s) outside IntelligenceContext: {outside.finding_id}",
        }
    ]

    all_invalid = run_intelligence_operation(SyntheticOperation([insight_candidate(outside.finding_id)]), context, repo)
    assert all_invalid.run.status == "succeeded"
    assert all_invalid.run.promoted_count == 0
    assert all_invalid.run.rejected_count == 1


def test_runtime_does_not_repair_or_rewrite_candidate_content(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context, f1, _, _ = persisted_findings_and_context(repo)
    candidate = insight_candidate(f1.finding_id, significance="low", synthesis="Do not rewrite me.")

    result = run_intelligence_operation(SyntheticOperation([candidate]), context, repo)

    insight = result.insights[0]
    assert insight.significance == "low"
    assert insight.synthesis == "Do not rewrite me."
    assert insight.title == candidate.title
    assert insight.category == candidate.category


def test_insight_run_and_context_provenance(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context, f1, _, f3 = persisted_findings_and_context(repo)
    result = run_intelligence_operation(SyntheticOperation([insight_candidate(f1.finding_id, f3.finding_id)]), context, repo)
    insight = result.insights[0]

    assert insight.intelligence_run_id == result.run.run_id
    assert insight.intelligence_context_id == result.run.intelligence_context_id
    assert insight.supporting_finding_ids == [f1.finding_id, f3.finding_id]
    row = repo.connection.execute(
        "SELECT intelligence_run_id, intelligence_context_id FROM insights WHERE insight_id = ?",
        (insight.insight_id,),
    ).fetchone()
    assert row["intelligence_run_id"] == result.run.run_id
    assert row["intelligence_context_id"] == context.intelligence_context_id


def test_persistence_failure_during_valid_promotion_is_execution_failure(tmp_path) -> None:
    repo = make_repo(tmp_path, FailingInsightRepository)
    context, f1, _, _ = persisted_findings_and_context(repo)

    result = run_intelligence_operation(SyntheticOperation([insight_candidate(f1.finding_id)]), context, repo)

    assert result.run.status == "failed"
    assert result.run.failure_category == "execution"
    assert result.run.rejected_count == 0
    assert "database write failed" in result.run.error


def test_model_run_parent_xor_and_intelligence_run_model_runs(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context, f1, _, _ = persisted_findings_and_context(repo)
    observer_run_id = repo.list_findings()[0].observer_run_id
    intelligence = run_intelligence_operation(SyntheticOperation([insight_candidate(f1.finding_id)]), context, repo)

    repo.save_model_run(ModelRun(observer_run_id=observer_run_id, provider="stub", status="succeeded"))
    repo.save_model_run(ModelRun(intelligence_run_id=intelligence.run.run_id, provider="stub", status="failed"))
    repo.save_model_run(ModelRun(intelligence_run_id=intelligence.run.run_id, provider="stub-2", status="succeeded"))

    with pytest.raises(ValidationError):
        ModelRun(observer_run_id=observer_run_id, intelligence_run_id=intelligence.run.run_id, provider="bad", status="failed")
    with pytest.raises(ValidationError):
        ModelRun(provider="bad", status="failed")

    rows = repo.connection.execute(
        "SELECT observer_run_id, intelligence_run_id, provider, status FROM model_runs ORDER BY provider"
    ).fetchall()
    assert len(rows) == 3
    assert any(row["observer_run_id"] == observer_run_id for row in rows)
    assert sum(1 for row in rows if row["intelligence_run_id"] == intelligence.run.run_id) == 2


def test_model_run_failure_does_not_force_intelligence_run_failure(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context, f1, _, _ = persisted_findings_and_context(repo)
    result = run_intelligence_operation(SyntheticOperation([insight_candidate(f1.finding_id)]), context, repo)
    repo.save_model_run(ModelRun(intelligence_run_id=result.run.run_id, provider="stub", status="failed"))

    row = repo.connection.execute("SELECT status FROM intelligence_runs WHERE run_id = ?", (result.run.run_id,)).fetchone()
    model_columns = [r["name"] for r in repo.connection.execute("PRAGMA table_info(model_runs)")]
    assert row["status"] == "succeeded"
    assert "raw_prompt" not in model_columns
    assert "raw_response" not in model_columns
    assert "chain_of_thought" not in model_columns


def test_deterministic_rerun_has_equivalent_content_but_distinct_ids(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context, f1, _, _ = persisted_findings_and_context(repo)
    op1 = SyntheticOperation([insight_candidate(f1.finding_id)])
    op2 = SyntheticOperation([insight_candidate(f1.finding_id)])

    first = run_intelligence_operation(op1, context, repo)
    second = run_intelligence_operation(op2, context, repo)

    assert first.run.deterministic is True
    assert first.run.run_id != second.run.run_id
    assert first.insights[0].insight_id != second.insights[0].insight_id
    assert first.insights[0].synthesis == second.insights[0].synthesis
    assert first.insights[0].supporting_finding_ids == second.insights[0].supporting_finding_ids


def test_model_assisted_operation_not_automatically_deterministic_and_no_execution_fingerprint(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context, f1, _, _ = persisted_findings_and_context(repo)
    result = run_intelligence_operation(NonDeterministicOperation([insight_candidate(f1.finding_id)]), context, repo)

    run_columns = [row["name"] for row in repo.connection.execute("PRAGMA table_info(intelligence_runs)")]
    table_names = {row["name"] for row in repo.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert result.run.deterministic is False
    assert "execution_fingerprint" not in run_columns
    assert "environment_hash" not in run_columns
    assert "execution_runs" not in table_names
