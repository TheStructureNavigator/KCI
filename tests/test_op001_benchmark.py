from __future__ import annotations

import pytest
from pydantic import ValidationError

from kci.benchmarks import (
    OP001_CATEGORY,
    OP001Benchmark,
    OP001BenchmarkPerformance,
    OP001ExpectedCandidate,
    OP001Scenario,
    evaluate_op001_candidates,
    load_op001_benchmark,
    op001_human_review_rubric,
)
from kci.contracts import EntityReference, InsightCandidate


def candidate(
    support: list[str],
    pattern_type: str = "co_occurring",
    significance: str = "medium",
    category: str = OP001_CATEGORY,
    synthesis: str = "A structurally valid synthetic benchmark candidate.",
) -> InsightCandidate:
    return InsightCandidate(
        category=category,
        subjects=[EntityReference(entity_type="synthetic_scope", entity_id="benchmark")],
        significance=significance,
        title="Synthetic benchmark candidate",
        synthesis=synthesis,
        supporting_finding_ids=support,
        metadata={"pattern_type": pattern_type},
    )


def candidate_from_expected(expected: OP001ExpectedCandidate) -> InsightCandidate:
    return candidate(
        support=list(expected.required_support),
        pattern_type=expected.pattern_type,
        significance=expected.expected_significance or "medium",
    )


def test_op001_benchmark_fixture_loads_and_validates() -> None:
    benchmark = load_op001_benchmark()

    assert isinstance(benchmark, OP001Benchmark)
    assert benchmark.schema_id == "kci.benchmark.uatu.op001"
    assert benchmark.operation_id == "uatu.cross_finding_pattern_synthesis"
    assert len(benchmark.scenarios) == 15
    assert {scenario.expected_candidate_count for scenario in benchmark.scenarios} >= {0, 1}


@pytest.mark.parametrize("scenario", load_op001_benchmark().scenarios, ids=lambda scenario: scenario.scenario_id)
def test_all_op001_expected_scenarios_are_evaluable(scenario) -> None:
    produced = [candidate_from_expected(expected) for expected in scenario.expected_candidates]

    result = evaluate_op001_candidates(scenario, produced)

    assert result.passed
    assert result.candidate_count == scenario.expected_candidate_count
    assert result.human_review_required


def test_zero_output_scenario_passes_with_no_candidates_and_fails_with_output() -> None:
    scenario = next(s for s in load_op001_benchmark().scenarios if s.scenario_id == "op001_no_pattern_single_finding")

    assert evaluate_op001_candidates(scenario, []).passed

    result = evaluate_op001_candidates(scenario, [candidate(["F_SINGLE_QUEUE", "F_SINGLE_QUEUE_OTHER"])])

    assert not result.passed
    assert {issue.code for issue in result.issues} >= {"expected_zero_output", "candidate_count_mismatch"}


def test_evaluator_checks_required_and_forbidden_support() -> None:
    scenario = next(s for s in load_op001_benchmark().scenarios if s.scenario_id == "op001_support_minimality")
    expected = scenario.expected_candidates[0]

    missing_required = evaluate_op001_candidates(
        scenario,
        [candidate(["F_LINE_B_CHANGEOVER_DELAY", "F_LINE_B_GENERAL_BACKLOG"], expected.pattern_type, expected.expected_significance)],
    )
    includes_forbidden = evaluate_op001_candidates(
        scenario,
        [
            candidate(
                ["F_LINE_B_CHANGEOVER_DELAY", "F_LINE_B_LABEL_APPROVAL", "F_LINE_B_GENERAL_BACKLOG"],
                expected.pattern_type,
                expected.expected_significance,
            )
        ],
    )

    assert "expected_candidate_missing" in {issue.code for issue in missing_required.issues}
    assert "forbidden_support_present" in {issue.code for issue in includes_forbidden.issues}


def test_evaluator_checks_pattern_type_category_and_significance() -> None:
    scenario = next(s for s in load_op001_benchmark().scenarios if s.scenario_id == "op001_positive_co_occurring_shift_handover")
    expected = scenario.expected_candidates[0]

    result = evaluate_op001_candidates(
        scenario,
        [
            candidate(
                expected.required_support,
                pattern_type="invented",
                significance="high",
                category="uatu.some_other_operation",
            )
        ],
    )

    issue_codes = {issue.code for issue in result.issues}
    assert "category_mismatch" in issue_codes
    assert "pattern_type_invalid" in issue_codes
    assert "expected_candidate_missing" in issue_codes


def test_evaluator_enforces_op001_minimum_two_supports() -> None:
    scenario = next(s for s in load_op001_benchmark().scenarios if s.scenario_id == "op001_positive_co_occurring_shift_handover")

    result = evaluate_op001_candidates(
        scenario,
        [candidate(["F_HANDOVER_QUEUE"], pattern_type="co_occurring", significance="medium")],
    )

    assert "support_count_too_low" in {issue.code for issue in result.issues}


def test_evaluator_reports_duplicate_support_ids_from_raw_output() -> None:
    scenario = next(s for s in load_op001_benchmark().scenarios if s.scenario_id == "op001_positive_co_occurring_shift_handover")

    result = evaluate_op001_candidates(
        scenario,
        [
            {
                "category": OP001_CATEGORY,
                "subjects": [],
                "significance": "medium",
                "title": "Duplicate support",
                "synthesis": "Duplicate support raw payload.",
                "supporting_finding_ids": ["F_HANDOVER_QUEUE", "F_HANDOVER_QUEUE"],
                "metadata": {"pattern_type": "co_occurring"},
            }
        ],
    )

    assert "candidate_schema_invalid" in {issue.code for issue in result.issues}


def test_duplicate_pattern_behavior_is_structural_only() -> None:
    scenario = next(s for s in load_op001_benchmark().scenarios if s.scenario_id == "op001_duplicate_pattern_behavior")
    expected = scenario.expected_candidates[0]
    duplicate = candidate_from_expected(expected)

    result = evaluate_op001_candidates(scenario, [duplicate, duplicate.model_copy(deep=True)])

    issue_codes = {issue.code for issue in result.issues}
    assert "duplicate_support_set" in issue_codes
    assert "candidate_count_mismatch" in issue_codes


def test_semantic_review_claims_are_not_deterministically_keyword_scored() -> None:
    scenario = next(s for s in load_op001_benchmark().scenarios if s.scenario_id == "op001_causal_overclaim_trap")
    expected = scenario.expected_candidates[0]
    overclaim = candidate(
        expected.required_support,
        pattern_type=expected.pattern_type,
        significance=expected.expected_significance,
        synthesis="The staging rework caused the cart queue.",
    )

    result = evaluate_op001_candidates(scenario, [overclaim])

    assert result.passed
    assert any("forbidden_claim" in item and "caused" in item for item in result.human_review_required)


def test_human_review_rubric_is_multidimensional() -> None:
    rubric = op001_human_review_rubric()
    names = {criterion.name for criterion in rubric}

    assert "pattern_detection" in names
    assert "unsupported_causality" in names
    assert "unsupported_prediction" in names
    assert "unsupported_prescription" in names
    assert "unsupported_generalization" in names
    assert "zero_output_judgment" in names
    assert "aggregate_score" not in names


def test_benchmark_performance_result_structure_is_provider_neutral() -> None:
    scenario = next(s for s in load_op001_benchmark().scenarios if s.scenario_id == "op001_positive_recurring_same_observer_machine")
    performance = OP001BenchmarkPerformance(elapsed_ms=12.5, model_run_count=1, metadata={"provider_metric": 7})

    result = evaluate_op001_candidates(
        scenario,
        [candidate_from_expected(scenario.expected_candidates[0])],
        performance=performance,
    )

    assert result.passed
    assert result.performance.elapsed_ms == 12.5
    assert result.performance.model_run_count == 1
    assert result.performance.metadata == {"provider_metric": 7}


def test_fixture_validation_rejects_invalid_expectation_references() -> None:
    scenario = next(s for s in load_op001_benchmark().scenarios if s.scenario_id == "op001_positive_recurring_same_observer_machine")
    payload = scenario.model_dump()
    payload["expected_candidates"][0]["required_support"] = ["F_M14_DRIFT_MONDAY", "F_NOT_IN_CONTEXT"]

    with pytest.raises(ValidationError):
        OP001Scenario.model_validate(payload)
