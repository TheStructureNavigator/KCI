from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from time import perf_counter
from typing import Any

from kci.contracts import Insight, IntelligenceContext, IntelligenceRun
from kci.error_hygiene import safe_error_message, trusted_message_type
from kci.operations import IntelligenceOperation, OperationConfigurationError
from kci.persistence.repository import KciRepository
from kci.runtime.insight_validation import InsightValidationFailure, promote_insight_candidate


@dataclass(frozen=True)
class IntelligenceExecutionResult:
    run: IntelligenceRun
    insights: list[Insight]
    validation_failures: list[tuple[int, InsightValidationFailure]]
    # Non-canonical, in-memory only: never persisted and never part of run counters or statuses.
    diagnostics: dict[str, Any] = field(default_factory=dict)


class PreconditionReason(Enum):
    CONTEXT_NOT_PERSISTED = "intelligence_context_id is not persisted"
    CONTEXT_MEMBERSHIP_MISMATCH = "persisted IntelligenceContext membership does not match supplied context"


@trusted_message_type
class IntelligencePreconditionFailed(ValueError):
    """Closed constructor: only a PreconditionReason member, never free-form text."""

    def __init__(self, reason: PreconditionReason) -> None:
        if not isinstance(reason, PreconditionReason):
            raise TypeError("reason must be a PreconditionReason")
        self.reason = reason
        super().__init__(reason.value)


def run_intelligence_operation(
    operation: IntelligenceOperation,
    context: IntelligenceContext,
    repository: KciRepository,
    requested_configuration: dict[str, Any] | None = None,
) -> IntelligenceExecutionResult:
    # Contract 007.4 step 1: resolve and validate configuration before the run is established.
    # A rejected request is never recorded: the run then carries only validated data ({}).
    effective_configuration: dict[str, Any] = {}
    resolution_error: Exception | None = None
    try:
        effective_configuration = canonical_configuration(operation.effective_configuration(requested_configuration))
    except Exception as exc:
        effective_configuration = {}
        resolution_error = exc

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
    operation_started = False

    try:
        if resolution_error is not None:
            raise resolution_error
        verify_intelligence_preconditions(context, repository)
        begin_intelligence_run = getattr(operation, "begin_intelligence_run", None)
        if begin_intelligence_run is not None:
            begin_intelligence_run(repository, run)
        operation_started = True
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
    except (IntelligencePreconditionFailed, OperationConfigurationError) as exc:
        run.status = "requirements_failed"
        run.failure_category = "requirements"
        run.error = safe_error_message(exc)
    except Exception as exc:
        run.status = "failed"
        run.failure_category = "execution"
        run.error = safe_error_message(exc)
    finally:
        run.finished_at = datetime.now(timezone.utc)
        run.duration_ms = (perf_counter() - started) * 1000
        repository.update_intelligence_run(run)

    return IntelligenceExecutionResult(
        run=run,
        insights=insights,
        validation_failures=validation_failures,
        diagnostics=_collect_diagnostics(operation) if operation_started else {},
    )


def _collect_diagnostics(operation: IntelligenceOperation) -> dict[str, Any]:
    hook = getattr(operation, "execution_diagnostics", None)
    if hook is None:
        return {}
    try:
        return dict(hook())
    except Exception:
        return {}


def verify_intelligence_preconditions(context: IntelligenceContext, repository: KciRepository) -> None:
    persisted_ids = repository.get_intelligence_context_finding_ids(context.intelligence_context_id)
    if not persisted_ids:
        raise IntelligencePreconditionFailed(PreconditionReason.CONTEXT_NOT_PERSISTED)
    if set(persisted_ids) != set(context.finding_ids):
        raise IntelligencePreconditionFailed(PreconditionReason.CONTEXT_MEMBERSHIP_MISMATCH)


def canonical_configuration(configuration: dict[str, Any]) -> dict[str, Any]:
    canonical = json.dumps(configuration, separators=(",", ":"), sort_keys=True)
    return json.loads(canonical)
