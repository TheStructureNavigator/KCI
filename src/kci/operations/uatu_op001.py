from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from kci.contracts import EntityReference, Finding, InsightCandidate, IntelligenceContext, IntelligenceRun, ModelRun
from kci.models import ModelProvider
from kci.operations.base import IntelligenceOperation
from kci.persistence.repository import KciRepository


OP001_CATEGORY = "uatu.cross_finding_pattern"
OP001_OPERATION_ID = "uatu.cross_finding_pattern_synthesis"
OP001_OPERATION_VERSION = "model-boundary-v1"

Op001PatternType = Literal["co_occurring", "recurring", "compound"]
Op001Significance = Literal["low", "medium", "high"]


class Op001ModelBoundaryError(RuntimeError):
    pass


class Op001ModelInvocationError(Op001ModelBoundaryError):
    pass


class Op001MalformedModelResponse(Op001ModelBoundaryError):
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


def project_op001_model_input(context: IntelligenceContext, repository: KciRepository) -> Op001ModelInput:
    findings_by_id = repository.get_findings_by_ids(context.finding_ids)
    missing_ids = sorted(set(context.finding_ids) - set(findings_by_id))
    if missing_ids:
        raise ValueError(f"cannot project missing Finding(s): {', '.join(missing_ids)}")
    projected = [_project_finding(findings_by_id[finding_id]) for finding_id in sorted(context.finding_ids)]
    return Op001ModelInput(findings=projected)


def parse_op001_model_response(raw_response: str | dict[str, Any]) -> Op001ModelResponse:
    try:
        data = json.loads(raw_response) if isinstance(raw_response, str) else raw_response
    except json.JSONDecodeError as exc:
        raise Op001MalformedModelResponse(f"model response is not valid JSON: {exc}") from exc
    try:
        return Op001ModelResponse.model_validate(data)
    except ValidationError as exc:
        raise Op001MalformedModelResponse(f"model response does not match OP-001 schema: {exc}") from exc


def convert_op001_model_response(
    response: Op001ModelResponse,
    model_input: Op001ModelInput,
) -> Op001CandidateConversionResult:
    candidates: list[InsightCandidate] = []
    rejections: list[Op001ModelOutputRejection] = []
    input_finding_ids = {finding.finding_id for finding in model_input.findings}
    subjects_by_finding_id = {
        finding.finding_id: {(subject.entity_type, subject.entity_id) for subject in finding.subjects}
        for finding in model_input.findings
    }

    for index, pattern in enumerate(response.patterns):
        unknown_support = sorted(set(pattern.supporting_finding_ids) - input_finding_ids)
        if unknown_support:
            rejections.append(
                Op001ModelOutputRejection(
                    index,
                    "support",
                    f"supporting finding_id value(s) outside OP-001 input: {', '.join(unknown_support)}",
                )
            )
            continue

        grounded_subjects: set[tuple[str, str]] = set()
        for finding_id in pattern.supporting_finding_ids:
            grounded_subjects.update(subjects_by_finding_id[finding_id])
        output_subjects = {(subject.entity_type, subject.entity_id) for subject in pattern.subjects}
        ungrounded_subjects = sorted(output_subjects - grounded_subjects)
        if ungrounded_subjects:
            rejections.append(
                Op001ModelOutputRejection(
                    index,
                    "subject_grounding",
                    f"output subject(s) not grounded in supporting Findings: {ungrounded_subjects}",
                )
            )
            continue

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

    return Op001CandidateConversionResult(candidates=candidates, rejections=rejections)


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
    started = perf_counter()
    parameters = dict(inference_parameters or {})
    try:
        raw_response = provider.generate(
            OP001_OPERATION_ID,
            model_input.model_dump(mode="json"),
            op001_output_schema(),
            inference_parameters=parameters,
        )
    except Exception as exc:
        _save_op001_model_run(
            provider,
            repository,
            intelligence_run_id,
            "failed",
            started_at,
            started,
            parameters,
            str(exc),
        )
        raise Op001ModelInvocationError(str(exc)) from exc

    try:
        response = parse_op001_model_response(raw_response)
    except Op001MalformedModelResponse:
        _save_op001_model_run(
            provider,
            repository,
            intelligence_run_id,
            "succeeded",
            started_at,
            started,
            parameters,
            None,
        )
        raise

    _save_op001_model_run(
        provider,
        repository,
        intelligence_run_id,
        "succeeded",
        started_at,
        started,
        parameters,
        None,
    )
    return convert_op001_model_response(response, model_input)


class Op001ModelAssistedOperation(IntelligenceOperation):
    operation_id = OP001_OPERATION_ID
    operation_version = OP001_OPERATION_VERSION
    deterministic = False

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider
        self.model_output_rejections: list[Op001ModelOutputRejection] = []
        self._repository: KciRepository | None = None
        self._run: IntelligenceRun | None = None

    def begin_intelligence_run(self, repository: KciRepository, run: IntelligenceRun) -> None:
        self._repository = repository
        self._run = run

    def effective_configuration(self, requested_configuration: dict[str, Any] | None = None) -> dict[str, Any]:
        if requested_configuration:
            return dict(requested_configuration)
        return {}

    def synthesize(self, context: IntelligenceContext, configuration: dict[str, Any]) -> list[InsightCandidate]:
        if self._repository is None or self._run is None:
            raise RuntimeError("Op001ModelAssistedOperation requires IntelligenceRun binding before synthesis")
        model_input = project_op001_model_input(context, self._repository)
        try:
            result = invoke_op001_model_boundary(
                self.provider,
                model_input,
                self._run.run_id,
                self._repository,
                inference_parameters=configuration,
            )
        finally:
            self._run.model_runs_count += 1
        self.model_output_rejections = result.rejections
        return result.candidates


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
    started: float,
    inference_parameters: dict[str, Any],
    error: str | None,
) -> None:
    finished_at = datetime.now(timezone.utc)
    repository.save_model_run(
        ModelRun(
            intelligence_run_id=intelligence_run_id,
            provider=provider.provider_name,
            model=getattr(provider, "model_name", None),
            model_artifact_hash=getattr(provider, "model_artifact_hash", None),
            quantization=getattr(provider, "quantization", None),
            inference_parameters=getattr(provider, "last_effective_inference_parameters", inference_parameters),
            started_at=started_at,
            finished_at=finished_at,
            total_ms=_provider_duration_ms(provider, started),
            status=status,
            error=error,
        )
    )


def _provider_duration_ms(provider: ModelProvider, started: float) -> float:
    invocation = getattr(provider, "last_invocation", None)
    duration_ms = getattr(invocation, "duration_ms", None)
    if duration_ms is not None:
        return duration_ms
    return (perf_counter() - started) * 1000
