from __future__ import annotations

from collections.abc import Sequence

from kci.contracts import IntelligenceContext
from kci.persistence.repository import KciRepository


class IntelligenceContextConstructionError(ValueError):
    pass


def build_intelligence_context(
    repository: KciRepository,
    finding_ids: Sequence[str],
) -> IntelligenceContext:
    if not finding_ids:
        raise IntelligenceContextConstructionError("at least one finding_id is required")
    if not all(isinstance(finding_id, str) for finding_id in finding_ids):
        raise IntelligenceContextConstructionError("IntelligenceContext requires trusted persisted finding_id values")
    if len(finding_ids) != len(set(finding_ids)):
        raise IntelligenceContextConstructionError("duplicate finding_id values are not allowed")

    stored = repository.get_findings_by_ids(finding_ids)
    missing = sorted(set(finding_ids) - set(stored))
    if missing:
        raise IntelligenceContextConstructionError(f"missing finding_id value(s): {', '.join(missing)}")

    context = IntelligenceContext(finding_ids=tuple(finding_ids))
    repository.save_intelligence_context(context)
    return context
