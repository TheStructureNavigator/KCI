from __future__ import annotations

from kci.observers.production import ProductionObserver
from kci.runtime import run_observer
from tests.conftest import load_context


def test_deterministic_production_observer_produces_expected_finding() -> None:
    context = load_context("unexplained_downtime.json")

    result = run_observer(ProductionObserver(), context)

    assert result.run.status == "succeeded"
    assert result.run.findings_count == 1
    assert result.run.candidates_count == 1
    assert result.findings[0].title == "Unexplained downtime exceeded threshold"
    assert result.findings[0].observer_run_id == result.run.run_id
    assert {e.ref for e in result.findings[0].evidence} == {
        "event:unexplained:stop-001",
        "event:unexplained:stop-002",
    }


def test_normal_dataset_can_produce_zero_findings() -> None:
    context = load_context("normal_shift.json")

    result = run_observer(ProductionObserver(), context)

    assert result.run.status == "succeeded"
    assert result.findings == []
    assert result.run.findings_count == 0


def test_observer_run_is_created_automatically_with_timing() -> None:
    context = load_context("mixed_problem.json")

    result = run_observer(ProductionObserver(), context)

    assert result.run.run_id.startswith("observer_run_")
    assert result.run.started_at is not None
    assert result.run.finished_at is not None
    assert result.run.duration_ms is not None
    assert result.run.duration_ms >= 0


def test_run_failure_is_represented() -> None:
    context = load_context("normal_shift.json")
    observer = ProductionObserver()
    observer.required_datasets = ()

    result = run_observer(observer, context)

    assert result.run.status == "failed"
    assert result.run.error is not None
    assert result.run.findings_count == 0


def test_missing_dataset_prevents_observer_execution() -> None:
    context = load_context("normal_shift.json")
    observer = ProductionObserver()
    observer.required_datasets = (
        observer.required_datasets[0].model_copy(update={"dataset": "synthetic.production.other"}),
    )

    result = run_observer(observer, context)

    assert result.run.status == "requirements_failed"
    assert result.run.failure_category == "requirements"
    assert result.run.error is not None


def test_incompatible_dataset_version_prevents_observer_execution() -> None:
    context = load_context("normal_shift.json")
    observer = ProductionObserver()
    observer.required_datasets = (
        observer.required_datasets[0].model_copy(update={"dataset_versions": (99,)}),
    )

    result = run_observer(observer, context)

    assert result.run.status == "requirements_failed"
    assert result.run.failure_category == "requirements"
    assert result.run.error is not None
