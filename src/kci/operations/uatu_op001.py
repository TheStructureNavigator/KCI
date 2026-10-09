from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from kci.contracts import EntityReference, Finding, InsightCandidate, IntelligenceContext, IntelligenceRun, ModelRun
from kci.error_hygiene import (
    describe_validation_errors,
    issues_from_validation_error,
    safe_error_message,
    trusted_message_type,
)
from kci.models import InferenceParameters, InferenceParametersError, ModelProvider
from kci.operations.base import IntelligenceOperation
from kci.operations.op001_policy import (
    OP001_INSTRUCTIONS,
    find_abstention,
    find_foreign_finding_reference,
    find_tripwire,
    find_ungrounded_reference,
    text_problem,
)
from kci.persistence.repository import KciRepository


OP001_CATEGORY = "uatu.cross_finding_pattern"
OP001_OPERATION_ID = "uatu.cross_finding_pattern_synthesis"
# Bump whenever OP-001 instructions or deterministic output rules (op001_policy) change behavior (Contract 008.5).
OP001_OPERATION_VERSION = "analytical-safety-v1"

Op001PatternType = Literal["co_occurring", "recurring", "compound"]
Op001Significance = Literal["low", "medium", "high"]


class Op001ModelBoundaryError(RuntimeError):
    pass


@trusted_message_type
class Op001ModelInvocationError(Op001ModelBoundaryError):
    # Message is always the output of safe_error_message().
    pass


@trusted_message_type
class Op001MalformedModelResponse(Op001ModelBoundaryError):
    # Messages contain only line/column numbers or sanitized field names and pydantic error types.
    pass


class Op001ModelSubject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)

    @classmethod
    def from_entity_reference(cls, subject: EntityReference) -> "Op001ModelSubject":
        return cls(entity_type=subject.entity_type, entity_id=subject.entity_id)

    def to_entity_reference(self) -> EntityReference:
        return EntityReference(entity_type=self.entity_type, entity_id=self.entity_id)


class Op001ModelFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(min_length=1)
    observer_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    severity: Literal["low", "medium", "high"]
    subjects: list[Op001ModelSubject] = Field(default_factory=list)
    title: str = Field(min_length=1)
    observation: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Op001ModelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[Op001ModelFinding]


class Op001ModelPattern(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern_type: Op001PatternType
    supporting_finding_ids: list[str] = Field(min_length=2)
    subjects: list[Op001ModelSubject] = Field(default_factory=list)
    significance: Op001Significance
    title: str = Field(min_length=1)
    synthesis: str = Field(min_length=1)

    @field_validator("supporting_finding_ids")
    @classmethod
    def support_ids_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("supporting_finding_ids must be unique")
        return value


class Op001ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patterns: list[Op001ModelPattern]


@dataclass(frozen=True)
class Op001ModelOutputRejection:
    pattern_index: int
    failure_category: str
    detail: str


@dataclass(frozen=True)
class Op001CandidateConversionResult:
    candidates: list[InsightCandidate]
    rejections: list[Op001ModelOutputRejection]
    patterns_received: int = 0


@dataclass(frozen=True)
class Op001ParsedResponse:
    """Top-level-valid response: structurally valid patterns plus per-pattern schema rejections."""

    patterns: list[Op001ModelPattern]
    pattern_indices: list[int]
    rejections: list[Op001ModelOutputRejection]
    received: int


class _Op001TopLevel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patterns: list[Any]


def project_op001_model_input(context: IntelligenceContext, repository: KciRepository) -> Op001ModelInput:
    findings_by_id = repository.get_findings_by_ids(context.finding_ids)
    missing_ids = sorted(set(context.finding_ids) - set(findings_by_id))
    if missing_ids:
        raise ValueError(f"cannot project missing Finding(s): {', '.join(missing_ids)}")
    projected = [_project_finding(findings_by_id[finding_id]) for finding_id in sorted(context.finding_ids)]
    return Op001ModelInput(findings=projected)


def parse_op001_model_response(raw_response: str | dict[str, Any]) -> Op001ParsedResponse:
    """Parse a raw model response.

    A malformed *top level* (not JSON, not an object, extra/missing keys, ``patterns`` not a list)
    raises ``Op001MalformedModelResponse`` and fails the run. An invalid *individual* pattern is
    rejected on its own (category ``schema``) and never discards its valid siblings.
    """
    try:
        data = json.loads(raw_response) if isinstance(raw_response, str) else raw_response
    except json.JSONDecodeError as exc:
        raise Op001MalformedModelResponse(
            f"model response is not valid JSON (line {exc.lineno}, column {exc.colno})"
        ) from exc
    try:
        top = _Op001TopLevel.model_validate(data)
    except ValidationError as exc:
        raise Op001MalformedModelResponse(
            f"model response does not match OP-001 schema: {describe_validation_errors(exc)}"
        ) from exc
    patterns: list[Op001ModelPattern] = []
    indices: list[int] = []
    rejections: list[Op001ModelOutputRejection] = []
    for index, item in enumerate(top.patterns):
        try:
            patterns.append(Op001ModelPattern.model_validate(item))
            indices.append(index)
        except ValidationError as exc:
            rejections.append(Op001ModelOutputRejection(index, "schema", describe_validation_errors(exc)))
    return Op001ParsedResponse(patterns, indices, rejections, received=len(top.patterns))


def convert_op001_model_response(
    response: Op001ModelResponse | Op001ParsedResponse,
    model_input: Op001ModelInput,
) -> Op001CandidateConversionResult:
    """Validate each pattern independently and build InsightCandidates from the valid ones.

    Rejection only: text, support and subjects are never rewritten, added or removed. At most one
    rejection (the first failing check, in the order below) is recorded per pattern.
    """
    candidates: list[InsightCandidate] = []
    rejections: list[Op001ModelOutputRejection] = list(getattr(response, "rejections", ()))
    indices = list(getattr(response, "pattern_indices", range(len(response.patterns))))
    received = getattr(response, "received", len(response.patterns))
    input_finding_ids = {finding.finding_id for finding in model_input.findings}
    findings_by_id = {finding.finding_id: finding for finding in model_input.findings}
    subjects_by_finding_id = {
        finding.finding_id: {(subject.entity_type, subject.entity_id) for subject in finding.subjects}
        for finding in model_input.findings
    }
    accepted_supports: set[frozenset[str]] = set()

    def reject(index: int, category: str, detail: str) -> None:
        rejections.append(Op001ModelOutputRejection(index, category, detail))

    for index, pattern in zip(indices, response.patterns):
        unknown_support = sorted(set(pattern.supporting_finding_ids) - input_finding_ids)
        if unknown_support:
            reject(index, "support", f"supporting finding_id value(s) outside OP-001 input: {', '.join(unknown_support)}")
            continue

        grounded_subjects: set[tuple[str, str]] = set()
        for finding_id in pattern.supporting_finding_ids:
            grounded_subjects.update(subjects_by_finding_id[finding_id])
        output_subjects = {(subject.entity_type, subject.entity_id) for subject in pattern.subjects}
        ungrounded_subjects = sorted(output_subjects - grounded_subjects)
        if ungrounded_subjects:
            reject(index, "subject_grounding", f"output subject(s) not grounded in supporting Findings: {ungrounded_subjects}")
            continue

        problem = text_problem(pattern.title, pattern.synthesis)
        if problem is not None:
            reject(index, "text", f"rule {problem}")
            continue

        reference_problem = find_foreign_finding_reference(
            pattern.title, pattern.synthesis, pattern.supporting_finding_ids, input_finding_ids
        )
        if reference_problem is not None:
            reject(index, reference_problem, "text cites a Finding identifier outside this pattern's support")
            continue
        supporting_text = "\n".join(
            _grounding_text(findings_by_id[finding_id]) for finding_id in pattern.supporting_finding_ids
        )
        if find_ungrounded_reference(pattern.title, pattern.synthesis, supporting_text):
            reject(index, "fabricated_reference", "text cites an evidence-style reference absent from the supporting Findings")
            continue

        tripwire = find_tripwire(pattern.title, pattern.synthesis)
        if tripwire is not None:
            category, rule_id = tripwire
            reject(index, category, f"rule {rule_id}")
            continue

        abstention = find_abstention(pattern.title, pattern.synthesis)
        if abstention is not None:
            reject(index, "abstention_text", f"rule {abstention}")
            continue

        support_set = frozenset(pattern.supporting_finding_ids)
        if support_set in accepted_supports:
            reject(index, "duplicate_support", "an earlier accepted pattern has the same supporting Finding set")
            continue
        accepted_supports.add(support_set)

        candidates.append(
            InsightCandidate(
                category=OP001_CATEGORY,
                subjects=[subject.to_entity_reference() for subject in pattern.subjects],
                significance=pattern.significance,
                title=pattern.title,
                synthesis=pattern.synthesis,
                supporting_finding_ids=list(pattern.supporting_finding_ids),
                metadata={"pattern_type": pattern.pattern_type},
            )
        )

    rejections.sort(key=lambda rejection: rejection.pattern_index)
    return Op001CandidateConversionResult(candidates=candidates, rejections=rejections, patterns_received=received)


def _grounding_text(finding: Op001ModelFinding) -> str:
    subjects = " ".join(f"{subject.entity_type}:{subject.entity_id}" for subject in finding.subjects)
    return "\n".join(
        [finding.title, finding.observation, finding.category, finding.observer_id, subjects, json.dumps(finding.metadata, sort_keys=True)]
    )


def op001_output_schema() -> dict[str, Any]:
    return Op001ModelResponse.model_json_schema()


def invoke_op001_model_boundary(
    provider: ModelProvider,
    model_input: Op001ModelInput,
    intelligence_run_id: str,
    repository: KciRepository,
    inference_parameters: dict[str, Any] | None = None,
) -> Op001CandidateConversionResult:
    started_at = datetime.now(timezone.utc)
    parameters = dict(inference_parameters or {})
    try:
        raw_response = provider.generate(
            # Operation-owned instructions travel as the generic ``task``; Finding content travels only
            # as ``context`` data, never inside the instructions (untrusted-data delimitation).
            OP001_INSTRUCTIONS,
            model_input.model_dump(mode="json"),
            op001_output_schema(),
            inference_parameters=parameters,
        )
    except Exception as exc:
        message = safe_error_message(exc)
        _save_op001_model_run(
            provider,
            repository,
            intelligence_run_id,
            "failed",
            started_at,
            message,
            failure=exc,
        )
        raise Op001ModelInvocationError(message) from exc

    try:
        response = parse_op001_model_response(raw_response)
    except Op001MalformedModelResponse:
        _save_op001_model_run(
            provider, repository, intelligence_run_id, "succeeded", started_at, None, raw_response
        )
        raise

    _save_op001_model_run(
        provider, repository, intelligence_run_id, "succeeded", started_at, None, raw_response
    )
    return convert_op001_model_response(response, model_input)


class Op001ModelAssistedOperation(IntelligenceOperation):
    operation_id = OP001_OPERATION_ID
    operation_version = OP001_OPERATION_VERSION
    deterministic = False

    def __init__(self, provider: ModelProvider, inference_parameters: Mapping[str, Any] | None = None) -> None:
        # Inference parameters belong to the composition boundary, not to per-run configuration.
        # Validated once here; analytical configuration for OP-001 v1 is always empty.
        requested = dict(inference_parameters or {})
        try:
            InferenceParameters.model_validate(requested)
        except ValidationError as exc:
            raise InferenceParametersError(issues_from_validation_error(exc)) from None
        self._inference_parameters: dict[str, Any] = json.loads(json.dumps(requested, sort_keys=True))
        self.provider = provider
        self.model_output_rejections: list[Op001ModelOutputRejection] = []
        self._diagnostics: dict[str, Any] = _empty_diagnostics("not_received")
        self._repository: KciRepository | None = None
        self._run: IntelligenceRun | None = None

    def begin_intelligence_run(self, repository: KciRepository, run: IntelligenceRun) -> None:
        self._repository = repository
        self._run = run
        # Per-run state: never carry rejections or diagnostics over from an earlier run.
        self.model_output_rejections = []
        self._diagnostics = _empty_diagnostics("not_received")

    def execution_diagnostics(self) -> dict[str, Any]:
        """Non-canonical diagnostics of the last execution: never persisted, never part of run counters.

        Counts model-output rejections (before an InsightCandidate exists) by reason category, kept
        distinct from Runtime candidate rejection (OP-001 spec, model invocation and failure semantics).
        """
        return json.loads(json.dumps(self._diagnostics))

    @property
    def inference_parameters(self) -> dict[str, Any]:
        return dict(self._inference_parameters)

    def synthesize(self, context: IntelligenceContext, configuration: dict[str, Any]) -> list[InsightCandidate]:
        if self._repository is None or self._run is None:
            raise RuntimeError("Op001ModelAssistedOperation requires IntelligenceRun binding before synthesis")
        model_input = project_op001_model_input(context, self._repository)
        self.model_output_rejections = []
        self._diagnostics = _empty_diagnostics("not_received")
        try:
            result = invoke_op001_model_boundary(
                self.provider,
                model_input,
                self._run.run_id,
                self._repository,
                inference_parameters=self.inference_parameters,
            )
        except Op001MalformedModelResponse:
            self._diagnostics = _empty_diagnostics("malformed")
            raise
        except Op001ModelInvocationError:
            self._diagnostics = _empty_diagnostics("provider_failure")
            raise
        finally:
            self._run.model_runs_count += 1
        self.model_output_rejections = result.rejections
        by_category: dict[str, int] = {}
        for rejection in result.rejections:
            by_category[rejection.failure_category] = by_category.get(rejection.failure_category, 0) + 1
        self._diagnostics = {
            "response": "parsed",
            "patterns_received": result.patterns_received,
            "patterns_accepted": len(result.candidates),
            "patterns_rejected": len(result.rejections),
            "rejected_by_category": dict(sorted(by_category.items())),
        }
        return result.candidates


def _empty_diagnostics(response: str) -> dict[str, Any]:
    return {
        "response": response,
        "patterns_received": 0,
        "patterns_accepted": 0,
        "patterns_rejected": 0,
        "rejected_by_category": {},
    }


def _project_finding(finding: Finding) -> Op001ModelFinding:
    return Op001ModelFinding(
        finding_id=finding.finding_id,
        observer_id=finding.observer_id,
        category=finding.category,
        severity=finding.severity,
        subjects=[Op001ModelSubject.from_entity_reference(subject) for subject in finding.subjects],
        title=finding.title,
        observation=finding.observation,
        metadata=_canonical_metadata(finding.metadata),
    )


def _canonical_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(metadata, separators=(",", ":"), sort_keys=True))


def _save_op001_model_run(
    provider: ModelProvider,
    repository: KciRepository,
    intelligence_run_id: str,
    status: Literal["succeeded", "failed"],
    started_at: datetime,
    error: str | None,
    raw_response: object = None,
    failure: Exception | None = None,
) -> None:
    # Telemetry is taken only from the artifacts of this very call: the returned value on
    # success, the raised error on failure. Provider-wide "last_*" state is never read.
    finished_at = datetime.now(timezone.utc)
    inference_parameters: dict[str, Any] | None
    if failure is not None:
        duration_ms = getattr(failure, "duration_ms", None)
        # Unknown unless the error carries parameters that were actually resolved; rejected
        # requests are never recorded as parameters that were used.
        inference_parameters = getattr(failure, "inference_parameters", None)
    else:
        telemetry = getattr(raw_response, "telemetry", None)
        if telemetry is not None:
            duration_ms = telemetry.duration_ms
            inference_parameters = dict(telemetry.inference_parameters)
        else:
            # No trustworthy per-call telemetry: nothing is established, and requested
            # parameters are never echoed as effective ones.
            duration_ms = None
            inference_parameters = None
    repository.save_model_run(
        ModelRun(
            intelligence_run_id=intelligence_run_id,
            provider=provider.provider_name,
            model=getattr(provider, "model_name", None),
            model_artifact_hash=getattr(provider, "model_artifact_hash", None),
            quantization=getattr(provider, "quantization", None),
            inference_parameters=inference_parameters,
            started_at=started_at,
            finished_at=finished_at,
            total_ms=duration_ms,
            status=status,
            error=error,
        )
    )
