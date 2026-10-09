from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kci.contracts import EvidenceReference, FindingCandidate, ModelRun
from kci.observers.production import ProductionObserver
from kci.persistence import KciRepository, connect, initialize_database
from kci.runtime import run_observer
from tests.conftest import load_context


class SpyObserver(ProductionObserver):
    def __init__(self) -> None:
        super().__init__()
        self.called = False

    def observe(self, context):
        self.called = True
        return super().observe(context)


class EmptyObserver(ProductionObserver):
    def observe(self, context):
        return []


class FailingObserver(ProductionObserver):
    def observe(self, context):
        raise RuntimeError("observer exploded")


class InvalidCandidateObserver(ProductionObserver):
    def observe(self, context):
        dataset = context.datasets[0]
        return [
            FindingCandidate(
                category="production.test",
                severity="low",
                title="Invalid evidence",
                observation="Runtime must reject this without repair.",
                evidence=[
                    EvidenceReference(
                        dataset=dataset.dataset,
                        snapshot_id="snapshot-outside-context",
                        ref="event:unexplained:stop-001",
                    )
                ],
            )
        ]


def test_observer_identity_version_and_effective_configuration_are_persisted(tmp_path) -> None:
    connection = connect(tmp_path / "kci.sqlite3")
    initialize_database(connection)
    repository = KciRepository(connection)
    context = load_context("unexplained_downtime.json")

    result = run_observer(
        ProductionObserver(),
        context,
        repository,
        requested_configuration={"threshold_minutes": 35},
    )

    row = connection.execute(
        """
        SELECT observer_id, observer_version, context_id, effective_configuration_json, status
        FROM observer_runs
        WHERE run_id = ?
        """,
        (result.run.run_id,),
    ).fetchone()

    assert row["observer_id"] == ProductionObserver.id
    assert row["observer_version"] == ProductionObserver.version
    assert row["context_id"] == context.context_id
    assert row["effective_configuration_json"] == '{"threshold_minutes":35}'
    assert row["status"] == "succeeded"


def test_requested_configuration_changes_effective_config_not_observer_version() -> None:
    context = load_context("unexplained_downtime.json")

    low = run_observer(ProductionObserver(), context, requested_configuration={"threshold_minutes": 30})
    high = run_observer(ProductionObserver(), context, requested_configuration={"threshold_minutes": 40})

    assert low.run.observer_version == high.run.observer_version
    assert low.run.effective_configuration == {"threshold_minutes": 30}
    assert high.run.effective_configuration == {"threshold_minutes": 40}
    assert low.findings
    assert high.findings == []


def test_historical_run_config_is_not_affected_by_later_default_changes() -> None:
    context = load_context("unexplained_downtime.json")
    observer = ProductionObserver(threshold_minutes=30)

    first = run_observer(observer, context)
    observer.threshold_minutes = 99

    assert first.run.effective_configuration == {"threshold_minutes": 30}


def test_identical_executions_create_different_run_ids() -> None:
    context = load_context("unexplained_downtime.json")

    first = run_observer(ProductionObserver(), context)
    second = run_observer(ProductionObserver(), context)

    assert first.run.run_id != second.run.run_id


def test_requirements_failure_prevents_observe_call() -> None:
    context = load_context("normal_shift.json")
    observer = SpyObserver()
    observer.required_datasets = (
        observer.required_datasets[0].model_copy(update={"dataset": "synthetic.production.other"}),
    )

    result = run_observer(observer, context)

    assert result.run.status == "requirements_failed"
    assert result.run.failure_category == "requirements"
    assert observer.called is False


def test_requirements_failure_is_distinct_from_execution_failure() -> None:
    context = load_context("normal_shift.json")

    failed = run_observer(FailingObserver(), context)

    assert failed.run.status == "failed"
    assert failed.run.failure_category == "observer_execution"


def test_zero_candidates_is_success() -> None:
    result = run_observer(EmptyObserver(), load_context("normal_shift.json"))

    assert result.run.status == "succeeded"
    assert result.run.candidates_count == 0
    assert result.run.findings_count == 0


def test_invalid_candidate_is_rejected_without_repair() -> None:
    result = run_observer(InvalidCandidateObserver(), load_context("unexplained_downtime.json"))

    assert result.run.status == "succeeded"
    assert result.run.candidates_count == 1
    assert result.run.validation_failures_count == 1
    assert result.findings == []
    assert "snapshot-outside-context" in result.validation_failures[0].reason


def test_deterministic_observer_declares_determinism_and_repeats_semantically() -> None:
    context = load_context("unexplained_downtime.json")

    first = run_observer(ProductionObserver(), context)
    second = run_observer(ProductionObserver(), context)

    assert ProductionObserver.deterministic is True
    assert [(f.category, f.title, f.observation, [e.ref for e in f.evidence]) for f in first.findings] == [
        (f.category, f.title, f.observation, [e.ref for e in f.evidence]) for f in second.findings
    ]


def test_observer_can_be_unit_tested_without_runtime_persistence() -> None:
    observer = ProductionObserver()

    candidates = observer.observe(load_context("unexplained_downtime.json"))

    assert len(candidates) == 1
    assert candidates[0].title == "Unexplained downtime exceeded threshold"


def test_model_run_can_reference_one_parent_observer_run(tmp_path) -> None:
    connection = connect(tmp_path / "kci.sqlite3")
    initialize_database(connection)
    repository = KciRepository(connection)
    observer_result = run_observer(ProductionObserver(), load_context("normal_shift.json"), repository)
    model_run = ModelRun(
        observer_run_id=observer_result.run.run_id,
        provider="stub-provider",
        model="stub-model",
        status="succeeded",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )

    repository.save_model_run(model_run)

    row = connection.execute(
        "SELECT observer_run_id, provider, model, input_tokens, output_tokens, total_ms FROM model_runs WHERE run_id = ?",
        (model_run.run_id,),
    ).fetchone()
    assert row["observer_run_id"] == observer_result.run.run_id
    assert row["provider"] == "stub-provider"
    assert row["model"] == "stub-model"
    assert row["input_tokens"] is None
    assert row["output_tokens"] is None
    assert row["total_ms"] is None


def test_model_run_requires_existing_parent_observer_run(tmp_path) -> None:
    connection = connect(tmp_path / "kci.sqlite3")
    initialize_database(connection)
    repository = KciRepository(connection)

    with pytest.raises(Exception):
        repository.save_model_run(
            ModelRun(observer_run_id="missing", provider="stub-provider", status="failed")
        )
