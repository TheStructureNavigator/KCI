from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from kci.contracts import Insight, IntelligenceContext, IntelligenceRun
from kci.operations import IntelligenceOperation
from kci.persistence.repository import KciRepository
from kci.runtime.insight_validation import InsightValidationFailure, promote_insight_candidate


@dataclass(frozen=True)
class IntelligenceExecutionResult:
    run: IntelligenceRun
    insights: list[Insight]
    validation_failures: list[tuple[int, InsightValidationFailure]]


class IntelligencePreconditionFailed(ValueError):
    pass


def run_intelligence_operation(
    operation: IntelligenceOperation,
    context: IntelligenceContext,
    repository: KciRepository,
    requested_configuration: dict[str, Any] | None = None,
) -> IntelligenceExecutionResult:
    effective_configuration: dict[str, Any] = {}
    try:
        effective_configuration = canonical_configuration(operation.effective_configuration(requested_configuration))
    except Exception:
        effective_configuration = {}

    run = IntelligenceRun.started(
        operation.operation_id,
        operation.operation_version,
        operation.deterministic,
        context.intelligence_context_id,
        effective_configuration,
    )
    repository.save_intelligence_run(run)
    started = perf_counter()
    insights: list[Insight] = []
    validation_failures: list[tuple[int, InsightValidationFailure]] = []

    try:
        effective_configuration = canonical_configuration(operation.effective_configuration(requested_configuration))
        run.effective_configuration = effective_configuration
        verify_intelligence_preconditions(context, repository)
        begin_intelligence_run = getattr(operation, "begin_intelligence_run", None)
        if begin_intelligence_run is not None:
            begin_intelligence_run(repository, run)
        candidates = operation.synthesize(context, effective_configuration)
        run.candidates_count = len(candidates)
        for index, candidate in enumerate(candidates):
            insight, failures = promote_insight_candidate(candidate, context, repository, intelligence_run_id=run.run_id)
            if failures:
                run.rejected_count += 1
                for failure in failures:
                    validation_failures.append((index, failure))
                    repository.save_intelligence_candidate_rejection(
                        run.run_id,
                        index,
                        "validation",
                        failure.reason,
                    )
                continue
            if insight is not None:
                insights.append(insight)
                run.promoted_count += 1
        run.status = "succeeded"
    except IntelligencePreconditionFailed as exc:
        run.status = "requirements_failed"
        run.failure_category = "requirements"
        run.error = str(exc)
    except Exception as exc:
        run.status = "failed"
        run.failure_category = "execution"
        run.error = str(exc)
    finally:
        run.finished_at = datetime.now(timezone.utc)
        run.duration_ms = (perf_counter() - started) * 1000
        repository.update_intelligence_run(run)

    return IntelligenceExecutionResult(run=run, insights=insights, validation_failures=validation_failures)


def verify_intelligence_preconditions(context: IntelligenceContext, repository: KciRepository) -> None:
    persisted_ids = repository.get_intelligence_context_finding_ids(context.intelligence_context_id)
    if not persisted_ids:
        raise IntelligencePreconditionFailed("intelligence_context_id is not persisted")
    if set(persisted_ids) != set(context.finding_ids):
        raise IntelligencePreconditionFailed("persisted IntelligenceContext membership does not match supplied context")


def canonical_configuration(configuration: dict[str, Any]) -> dict[str, Any]:
    canonical = json.dumps(configuration, separators=(",", ":"), sort_keys=True)
    return json.loads(canonical)
