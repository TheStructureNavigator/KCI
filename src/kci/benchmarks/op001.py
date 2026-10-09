from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from kci.contracts import EntityReference, InsightCandidate


OP001_CATEGORY = "uatu.cross_finding_pattern"
OP001_OPERATION_ID = "uatu.cross_finding_pattern_synthesis"
OP001_ALLOWED_PATTERN_TYPES = ("co_occurring", "recurring", "compound")

PatternType = Literal["co_occurring", "recurring", "compound"]


class OP001FindingFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    observer_id: str
    category: str
    severity: Literal["low", "medium", "high"]
    title: str
    observation: str
    subjects: list[EntityReference] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OP001ExpectedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern_type: PatternType
    required_support: list[str]
    forbidden_support: list[str] = Field(default_factory=list)
    expected_significance: Literal["low", "medium", "high"] | None = None
    required_claims: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    human_review_notes: str | None = None

    @field_validator("required_support", "forbidden_support")
    @classmethod
    def support_ids_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("expected support lists cannot contain duplicate finding_id values")
        return value

    @field_validator("required_support")
    @classmethod
    def op001_requires_two_supports(cls, value: list[str]) -> list[str]:
        if len(value) < 2:
            raise ValueError("OP-001 expected candidates require at least two supporting Findings")
        return value


class OP001Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    title: str
    purpose: str
    findings: list[OP001FindingFixture]
    context_finding_ids: list[str]
    expected_candidate_count: int = Field(ge=0)
    expected_candidates: list[OP001ExpectedCandidate] = Field(default_factory=list)
    disallow_duplicate_support_sets: bool = False
    human_review_focus: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_fixture_references(self) -> "OP001Scenario":
        finding_ids = [finding.finding_id for finding in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("scenario finding_id values must be unique")
        known_ids = set(finding_ids)
        context_ids = set(self.context_finding_ids)
        if len(self.context_finding_ids) != len(context_ids):
            raise ValueError("context_finding_ids cannot contain duplicates")
        unknown_context_ids = context_ids - known_ids
        if unknown_context_ids:
            raise ValueError(f"context references unknown finding_id values: {sorted(unknown_context_ids)}")
        if self.expected_candidate_count == 0 and self.expected_candidates:
            raise ValueError("zero-output scenarios cannot define expected candidates")
        if self.expected_candidate_count != len(self.expected_candidates):
            raise ValueError("expected_candidate_count must match expected_candidates length")
        for expected in self.expected_candidates:
            support_ids = set(expected.required_support + expected.forbidden_support)
            unknown_support_ids = support_ids - context_ids
            if unknown_support_ids:
                raise ValueError(f"expectation references finding_id values outside context: {sorted(unknown_support_ids)}")
        return self


class OP001Benchmark(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_id: Literal["kci.benchmark.uatu.op001"] = Field(alias="schema")
    schema_version: str
    operation_id: Literal["uatu.cross_finding_pattern_synthesis"]
    scenarios: list[OP001Scenario]

    @field_validator("scenarios")
    @classmethod
    def scenario_ids_unique(cls, value: list[OP001Scenario]) -> list[OP001Scenario]:
        scenario_ids = [scenario.scenario_id for scenario in value]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("scenario_id values must be unique")
        return value


class OP001BenchmarkPerformance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    elapsed_ms: float | None = Field(default=None, ge=0)
    model_run_count: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OP001EvaluationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    candidate_index: int | None = None
    expected_index: int | None = None


class OP001EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    passed: bool
    candidate_count: int
    issues: list[OP001EvaluationIssue] = Field(default_factory=list)
    performance: OP001BenchmarkPerformance = Field(default_factory=OP001BenchmarkPerformance)
    human_review_required: list[str] = Field(default_factory=list)


class HumanReviewCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    question: str


def op001_human_review_rubric() -> list[HumanReviewCriterion]:
    return [
        HumanReviewCriterion(name="pattern_detection", question="Was the intended pattern found without inventing extra patterns?"),
        HumanReviewCriterion(name="analytical_novelty", question="Does the candidate add joint analytical meaning beyond the individual Findings?"),
        HumanReviewCriterion(name="relationship_grounding", question="Do the supporting Findings ground the declared relationship type?"),
        HumanReviewCriterion(name="support_correctness", question="Do all cited Findings materially support the claim?"),
        HumanReviewCriterion(name="support_minimality", question="Are cited Findings necessary rather than merely available or interesting?"),
        HumanReviewCriterion(name="distractor_resistance", question="Were unrelated, high-severity, or broadly similar distractors excluded?"),
        HumanReviewCriterion(name="analytical_restraint", question="Is the claim scoped to what the Findings actually support?"),
        HumanReviewCriterion(name="unsupported_causality", question="Does the candidate avoid unsupported causal meaning?"),
        HumanReviewCriterion(name="unsupported_prediction", question="Does the candidate avoid unsupported future-outcome claims?"),
        HumanReviewCriterion(name="unsupported_prescription", question="Does the candidate avoid recommendations or next actions?"),
        HumanReviewCriterion(name="unsupported_generalization", question="Does the candidate avoid broad claims beyond the supplied Findings?"),
        HumanReviewCriterion(name="significance_calibration", question="Is significance assigned to the new pattern rather than severity, confidence, or support count?"),
        HumanReviewCriterion(name="atomicity_coherence", question="Is the synthesis one coherent atomic analytical claim?"),
        HumanReviewCriterion(name="zero_output_judgment", question="When no valid pattern exists, did the operation return no candidates?"),
    ]


def default_op001_benchmark_path() -> Path:
    return Path(__file__).resolve().parents[3] / "benchmarks" / "uatu" / "op001_scenarios.json"


def load_op001_benchmark(path: Path | str | None = None) -> OP001Benchmark:
    benchmark_path = Path(path) if path is not None else default_op001_benchmark_path()
    return OP001Benchmark.model_validate_json(benchmark_path.read_text(encoding="utf-8"))


def evaluate_op001_candidates(
    scenario: OP001Scenario,
    candidates: list[InsightCandidate | dict[str, Any]],
    performance: OP001BenchmarkPerformance | None = None,
) -> OP001EvaluationResult:
    issues: list[OP001EvaluationIssue] = []
    parsed_candidates: list[InsightCandidate | None] = []
    context_ids = set(scenario.context_finding_ids)

    for index, raw_candidate in enumerate(candidates):
        candidate = _parse_candidate(raw_candidate, index, issues)
        parsed_candidates.append(candidate)
        if candidate is None:
            continue
        _evaluate_candidate_structure(candidate, index, context_ids, issues)

    if len(candidates) != scenario.expected_candidate_count:
        issues.append(
            OP001EvaluationIssue(
                code="candidate_count_mismatch",
                message=f"expected {scenario.expected_candidate_count} candidate(s), got {len(candidates)}",
            )
        )

    if scenario.expected_candidate_count == 0 and candidates:
        issues.append(
            OP001EvaluationIssue(
                code="expected_zero_output",
                message="scenario expects no valid OP-001 pattern candidates",
            )
        )

    if scenario.disallow_duplicate_support_sets:
        _evaluate_duplicate_support_sets(parsed_candidates, issues)

    for expected_index, expected in enumerate(scenario.expected_candidates):
        _evaluate_expected_candidate(expected, expected_index, parsed_candidates, issues)

    human_review_required = _human_review_items(scenario)
    return OP001EvaluationResult(
        scenario_id=scenario.scenario_id,
        passed=not issues,
        candidate_count=len(candidates),
        issues=issues,
        performance=performance or OP001BenchmarkPerformance(),
        human_review_required=human_review_required,
    )


def _parse_candidate(
    raw_candidate: InsightCandidate | dict[str, Any],
    index: int,
    issues: list[OP001EvaluationIssue],
) -> InsightCandidate | None:
    if isinstance(raw_candidate, InsightCandidate):
        return raw_candidate
    try:
        return InsightCandidate.model_validate(raw_candidate)
    except Exception as exc:
        issues.append(
            OP001EvaluationIssue(
                code="candidate_schema_invalid",
                message=str(exc),
                candidate_index=index,
            )
        )
        return None


def _evaluate_candidate_structure(
    candidate: InsightCandidate,
    index: int,
    context_ids: set[str],
    issues: list[OP001EvaluationIssue],
) -> None:
    if candidate.category != OP001_CATEGORY:
        issues.append(
            OP001EvaluationIssue(
                code="category_mismatch",
                message=f"expected category {OP001_CATEGORY!r}, got {candidate.category!r}",
                candidate_index=index,
            )
        )

    pattern_type = candidate.metadata.get("pattern_type")
    if pattern_type not in OP001_ALLOWED_PATTERN_TYPES:
        issues.append(
            OP001EvaluationIssue(
                code="pattern_type_invalid",
                message=f"metadata.pattern_type must be one of {OP001_ALLOWED_PATTERN_TYPES}",
                candidate_index=index,
            )
        )

    support_ids = candidate.supporting_finding_ids
    if len(support_ids) < 2:
        issues.append(
            OP001EvaluationIssue(
                code="support_count_too_low",
                message="OP-001 candidates require at least two supporting Findings",
                candidate_index=index,
            )
        )
    if len(support_ids) != len(set(support_ids)):
        issues.append(
            OP001EvaluationIssue(
                code="support_ids_not_unique",
                message="supporting_finding_ids cannot contain duplicates",
                candidate_index=index,
            )
        )
    outside_context = sorted(set(support_ids) - context_ids)
    if outside_context:
        issues.append(
            OP001EvaluationIssue(
                code="support_outside_context",
                message=f"supporting finding_id value(s) outside scenario context: {outside_context}",
                candidate_index=index,
            )
        )


def _evaluate_duplicate_support_sets(
    candidates: list[InsightCandidate | None],
    issues: list[OP001EvaluationIssue],
) -> None:
    seen: dict[tuple[str, tuple[str, ...]], int] = {}
    for index, candidate in enumerate(candidates):
        if candidate is None:
            continue
        key = (
            str(candidate.metadata.get("pattern_type")),
            tuple(sorted(candidate.supporting_finding_ids)),
        )
        if key in seen:
            issues.append(
                OP001EvaluationIssue(
                    code="duplicate_support_set",
                    message=f"candidate duplicates candidate {seen[key]} by pattern_type and support set",
                    candidate_index=index,
                )
            )
        else:
            seen[key] = index


def _evaluate_expected_candidate(
    expected: OP001ExpectedCandidate,
    expected_index: int,
    candidates: list[InsightCandidate | None],
    issues: list[OP001EvaluationIssue],
) -> None:
    required_support = set(expected.required_support)
    forbidden_support = set(expected.forbidden_support)
    matching_indexes: list[int] = []

    for candidate_index, candidate in enumerate(candidates):
        if candidate is None:
            continue
        candidate_support = set(candidate.supporting_finding_ids)
        if candidate.metadata.get("pattern_type") != expected.pattern_type:
            continue
        if not required_support.issubset(candidate_support):
            continue
        if forbidden_support & candidate_support:
            issues.append(
                OP001EvaluationIssue(
                    code="forbidden_support_present",
                    message=f"candidate includes forbidden support: {sorted(forbidden_support & candidate_support)}",
                    candidate_index=candidate_index,
                    expected_index=expected_index,
                )
            )
            continue
        if expected.expected_significance and candidate.significance != expected.expected_significance:
            issues.append(
                OP001EvaluationIssue(
                    code="significance_mismatch",
                    message=f"expected significance {expected.expected_significance!r}, got {candidate.significance!r}",
                    candidate_index=candidate_index,
                    expected_index=expected_index,
                )
            )
            continue
        matching_indexes.append(candidate_index)

    if not matching_indexes:
        issues.append(
            OP001EvaluationIssue(
                code="expected_candidate_missing",
                message="no candidate satisfied expected pattern_type, required support, forbidden support, and significance",
                expected_index=expected_index,
            )
        )


def _human_review_items(scenario: OP001Scenario) -> list[str]:
    items: list[str] = []
    items.extend(scenario.human_review_focus)
    for expected in scenario.expected_candidates:
        items.extend(f"required_claim: {claim}" for claim in expected.required_claims)
        items.extend(f"forbidden_claim: {claim}" for claim in expected.forbidden_claims)
        if expected.human_review_notes:
            items.append(expected.human_review_notes)
    return items
