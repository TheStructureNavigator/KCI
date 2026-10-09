from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from kci.contracts import Finding, ObservationContext, ObserverRun
from kci.observers.base import Observer
from kci.persistence.repository import KciRepository
from kci.runtime.validation import ValidationFailure, validate_candidates


@dataclass(frozen=True)
class ObserverExecutionResult:
    run: ObserverRun
    findings: list[Finding]
    validation_failures: list[ValidationFailure]


def run_observer(
    observer: Observer,
    context: ObservationContext,
    repository: KciRepository | None = None,
    requested_configuration: dict[str, Any] | None = None,
) -> ObserverExecutionResult:
    primary_dataset = context.datasets[0]
    effective_configuration: dict[str, Any] = {}
    try:
        effective_configuration = canonical_configuration(observer.effective_configuration(requested_configuration))
    except Exception:
        effective_configuration = {}
    run = ObserverRun.started(
        observer.id,
        observer.version,
        context.context_id,
        effective_configuration,
        primary_dataset.dataset,
        primary_dataset.snapshot_id,
    )
    started = perf_counter()
    findings: list[Finding] = []
    failures: list[ValidationFailure] = []

    try:
        effective_configuration = canonical_configuration(observer.effective_configuration(requested_configuration))
        run.effective_configuration = effective_configuration
        verify_requirements(observer, context)
        observer.apply_configuration(effective_configuration)
        candidates = observer.observe(context)
        run.candidates_count = len(candidates)
        findings, failures = validate_candidates(candidates, context, run.run_id, observer.id, observer.version)
        run.status = "succeeded"
        run.findings_count = len(findings)
        run.validation_failures_count = len(failures)
    except RequirementsNotSatisfied as exc:
        run.status = "requirements_failed"
        run.failure_category = "requirements"
        run.error = str(exc)
    except Exception as exc:
        run.status = "failed"
        run.failure_category = "observer_execution"
        run.error = str(exc)
    finally:
        run.finished_at = datetime.now(timezone.utc)
        run.duration_ms = (perf_counter() - started) * 1000

    if repository is not None:
        repository.save_observer_run(run)
        for finding in findings:
            repository.save_finding(run.run_id, finding)

    return ObserverExecutionResult(run=run, findings=findings, validation_failures=failures)


class RequirementsNotSatisfied(ValueError):
    pass


def verify_requirements(observer: Observer, context: ObservationContext) -> None:
    for dataset in context.datasets:
        if not dataset.content_hash_valid():
            raise RequirementsNotSatisfied(
                f"content_hash mismatch for {dataset.dataset}/{dataset.snapshot_id}"
            )

    for requirement in observer.required_datasets:
        try:
            dataset = context.require_dataset(requirement.dataset)
        except ValueError as exc:
            raise RequirementsNotSatisfied(str(exc)) from exc
        if dataset.dataset_version not in requirement.dataset_versions:
            raise RequirementsNotSatisfied(
                f"unsupported dataset version for {dataset.dataset}: "
                f"{dataset.dataset_version} not in {requirement.dataset_versions}"
            )


def canonical_configuration(configuration: dict[str, Any]) -> dict[str, Any]:
    canonical = json.dumps(configuration, separators=(",", ":"), sort_keys=True)
    return json.loads(canonical)
