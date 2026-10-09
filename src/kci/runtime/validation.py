from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from kci.contracts import Finding, FindingCandidate, ObservationContext


@dataclass(frozen=True)
class ValidationFailure:
    candidate_index: int
    reason: str


def validate_candidates(
    candidates: list[FindingCandidate],
    context: ObservationContext,
    observer_run_id: str,
    observer_id: str,
    observer_version: str,
) -> tuple[list[Finding], list[ValidationFailure]]:
    findings: list[Finding] = []
    failures: list[ValidationFailure] = []

    for index, candidate in enumerate(candidates):
        if not candidate.evidence:
            failures.append(ValidationFailure(candidate_index=index, reason="finding candidate requires evidence"))
            continue

        bad_refs = [
            f"{evidence.dataset}/{evidence.snapshot_id}/{evidence.ref}"
            for evidence in candidate.evidence
            if not context.has_evidence(evidence.dataset, evidence.snapshot_id, evidence.ref)
        ]
        if bad_refs:
            failures.append(
                ValidationFailure(
                    candidate_index=index,
                    reason=f"invalid evidence reference(s): {', '.join(sorted(bad_refs))}",
                )
            )
            continue

        try:
            findings.append(
                Finding(
                    **candidate.model_dump(),
                    observer_run_id=observer_run_id,
                    observer_id=observer_id,
                    observer_version=observer_version,
                )
            )
        except ValidationError as exc:
            failures.append(ValidationFailure(candidate_index=index, reason=str(exc)))

    return findings, failures
