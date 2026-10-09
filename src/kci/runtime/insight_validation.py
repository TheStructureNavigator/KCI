from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from kci.contracts import Insight, InsightCandidate, IntelligenceContext
from kci.persistence.repository import KciRepository


@dataclass(frozen=True)
class InsightValidationFailure:
    reason: str


def promote_insight_candidate(
    candidate: InsightCandidate,
    context: IntelligenceContext,
    repository: KciRepository,
    intelligence_run_id: str | None = None,
) -> tuple[Insight | None, list[InsightValidationFailure]]:
    context_finding_ids = repository.get_intelligence_context_finding_ids(context.intelligence_context_id)
    if not context_finding_ids:
        return None, [InsightValidationFailure("intelligence_context_id is not persisted")]

    context_set = set(context_finding_ids)
    stored_findings = repository.get_findings_by_ids(candidate.supporting_finding_ids)
    failures: list[InsightValidationFailure] = []
    missing = sorted(set(candidate.supporting_finding_ids) - set(stored_findings))
    outside_context = sorted(set(candidate.supporting_finding_ids) - context_set)

    if missing:
        failures.append(InsightValidationFailure(f"missing supporting finding_id value(s): {', '.join(missing)}"))
    if outside_context:
        failures.append(
            InsightValidationFailure(
                f"supporting finding_id value(s) outside IntelligenceContext: {', '.join(outside_context)}"
            )
        )
    if failures:
        return None, failures

    try:
        insight = Insight(
            **candidate.model_dump(),
            intelligence_context_id=context.intelligence_context_id,
            intelligence_run_id=intelligence_run_id,
        )
    except ValidationError as exc:
        return None, [InsightValidationFailure(str(exc))]

    repository.save_insight(insight)
    return insight, []
