from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from kci.contracts import EntityReference, EvidenceReference, Finding, IntelligenceContext, ObserverRun
from kci.models import ModelProvider
from kci.operations import (
    OP001_CATEGORY,
    OP001_INSTRUCTIONS,
    Op001MalformedModelResponse,
    Op001ModelAssistedOperation,
    Op001ModelPattern,
    Op001ModelResponse,
    convert_op001_model_response,
    parse_op001_model_response,
    project_op001_model_input,
)
from kci.persistence import KciRepository, connect, initialize_database
from kci.runtime import run_intelligence_operation


class StubProvider(ModelProvider):
    provider_name = "stub-provider"

    def __init__(self, response: str | Exception) -> None:
        self.response = response
        self.calls = 0
        self.last_task: str | None = None
        self.last_context: dict[str, Any] | None = None
        self.last_output_schema: dict[str, Any] | None = None
        self.last_inference_parameters: dict[str, Any] | None = None

    def generate(
        self,
        task: str,
        context: dict[str, Any],
        output_schema: dict[str, Any],
        inference_parameters: dict[str, Any] | None = None,
    ) -> str:
        self.calls += 1
        self.last_task = task
        self.last_context = context
        self.last_output_schema = output_schema
        self.last_inference_parameters = inference_parameters
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def make_repo(tmp_path) -> KciRepository:
    connection = connect(tmp_path / "kci.sqlite3")
    initialize_database(connection)
    return KciRepository(connection)


def persist_finding(
    repository: KciRepository,
    finding_id: str,
    *,
    subject: EntityReference,
    metadata: dict[str, Any] | None = None,
    severity: str = "medium",
    category: str = "synthetic.finding",
) -> Finding:
    run = ObserverRun.started(
        observer_id=f"observer.{finding_id.lower()}",
        observer_version="1",
        context_id=f"context.{finding_id.lower()}",
        effective_configuration={},
        dataset="synthetic.dataset",
        snapshot_id="snapshot-001",
    )
    run.status = "succeeded"
    repository.save_observer_run(run)
    finding = Finding(
        finding_id=finding_id,
        observer_run_id=run.run_id,
        observer_id=run.observer_id,
        observer_version=run.observer_version,
        category=category,
        severity=severity,
        subjects=[subject],
        title=f"{finding_id} title",
        observation=f"{finding_id} observation",
        evidence=[EvidenceReference(dataset="synthetic.dataset", snapshot_id="snapshot-001", ref=f"event:{finding_id}")],
        metadata=metadata or {"source": finding_id, "nested": {"kept": True}},
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    repository.save_finding(run.run_id, finding)
    return finding


def setup_context(repository: KciRepository) -> tuple[IntelligenceContext, Finding, Finding, Finding]:
    f_b = persist_finding(repository, "F_B", subject=EntityReference(entity_type="machine", entity_id="M15"))
    f_a = persist_finding(repository, "F_A", subject=EntityReference(entity_type="machine", entity_id="M14"))
    f_c = persist_finding(repository, "F_C", subject=EntityReference(entity_type="plant", entity_id="PL02"))
    context = IntelligenceContext(finding_ids=("F_B", "F_A", "F_C"))
    repository.save_intelligence_context(context)
    return context, f_a, f_b, f_c


def raw_response(patterns: list[dict[str, Any]]) -> str:
    return json.dumps({"patterns": patterns})


def raw_pattern(
    support: list[str] | None = None,
    *,
    subjects: list[dict[str, str]] | None = None,
    pattern_type: str = "co_occurring",
    significance: str = "medium",
    title: str = "Grounded pattern",
    synthesis: str = "A bounded structured output pattern.",
    **extra,
) -> dict[str, Any]:
    values = {
        "pattern_type": pattern_type,
        "supporting_finding_ids": support or ["F_A", "F_B"],
        "subjects": subjects if subjects is not None else [{"entity_type": "machine", "entity_id": "M14"}],
        "significance": significance,
        "title": title,
        "synthesis": synthesis,
    }
    values.update(extra)
    return values


def test_model_input_projection_is_deterministic_and_bounded(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context, _, _, _ = setup_context(repo)

    model_input = project_op001_model_input(context, repo)
    dumped = model_input.model_dump(mode="json")

    assert [finding.finding_id for finding in model_input.findings] == ["F_A", "F_B", "F_C"]
    assert set(dumped["findings"][0]) == {
        "finding_id",
        "observer_id",
        "category",
        "severity",
        "subjects",
        "title",
        "observation",
        "metadata",
    }
    serialized = json.dumps(dumped)
    assert "EvidenceReference" not in serialized
    assert "evidence" not in dumped["findings"][0]
    assert "observer_version" not in dumped["findings"][0]
    assert "observer_run_id" not in dumped["findings"][0]
    assert "created_at" not in dumped["findings"][0]
    assert "intelligence_context_id" not in serialized
    assert "snapshot-001" not in serialized
    assert dumped["findings"][0]["metadata"] == {"nested": {"kept": True}, "source": "F_A"}


def test_projection_does_not_silently_omit_missing_context_findings(tmp_path) -> None:
    repo = make_repo(tmp_path)
    persist_finding(repo, "F_A", subject=EntityReference(entity_type="machine", entity_id="M14"))
    context = IntelligenceContext(finding_ids=("F_A", "F_MISSING"))

    with pytest.raises(ValueError, match="F_MISSING"):
        project_op001_model_input(context, repo)


def test_output_schema_accepts_valid_empty_and_valid_pattern_responses() -> None:
    empty = parse_op001_model_response('{"patterns":[]}')
    response = parse_op001_model_response(raw_response([raw_pattern()]))

    assert empty.patterns == []
    assert response.patterns[0].pattern_type == "co_occurring"


@pytest.mark.parametrize(
    "payload",
    [
        {"patterns": [], "status": "ok"},  # forbidden top-level field
        {"status": "ok"},  # missing patterns
        {"patterns": "none"},  # patterns is not a list
        {"patterns": {"pattern_type": "co_occurring"}},
        [raw_pattern()],  # wrong top-level shape
        "not an object",
    ],
)
def test_malformed_top_level_responses_fail_the_whole_response(payload) -> None:
    with pytest.raises(Op001MalformedModelResponse):
        parse_op001_model_response(payload)


@pytest.mark.parametrize(
    "bad_pattern",
    [
        raw_pattern(pattern_type="causal"),
        raw_pattern(significance="urgent"),
        raw_pattern(support=["F_A"]),
        raw_pattern(support=["F_A", "F_A"]),
        {"pattern_type": "co_occurring"},
        raw_pattern(extra_field="nope"),
        raw_pattern(subjects=[{"entity_type": "machine", "entity_id": "M14", "label": "extra"}]),
        "not even an object",
    ],
)
def test_invalid_individual_patterns_are_rejected_without_discarding_valid_siblings(bad_pattern) -> None:
    parsed = parse_op001_model_response({"patterns": [raw_pattern(), bad_pattern, raw_pattern(support=["F_B", "F_C"])]})

    assert [rejection.pattern_index for rejection in parsed.rejections] == [1]
    assert parsed.rejections[0].failure_category == "schema"
    assert parsed.pattern_indices == [0, 2]
    assert len(parsed.patterns) == 2 and parsed.received == 3


def test_model_pattern_schema_is_private_not_insight_candidate() -> None:
    with pytest.raises(ValidationError):
        Op001ModelPattern.model_validate(
            raw_pattern(category="uatu.cross_finding_pattern", metadata={"pattern_type": "co_occurring"})
        )


def test_grounding_accepts_subjects_from_supporting_findings(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context, _, _, _ = setup_context(repo)
    model_input = project_op001_model_input(context, repo)
    response = Op001ModelResponse(patterns=[Op001ModelPattern.model_validate(raw_pattern())])

    result = convert_op001_model_response(response, model_input)

    assert len(result.candidates) == 1
    assert result.rejections == []


def test_grounding_rejects_unknown_support_and_ungrounded_subjects(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context, _, _, _ = setup_context(repo)
    model_input = project_op001_model_input(context, repo)
    response = Op001ModelResponse(
        patterns=[
            Op001ModelPattern.model_validate(raw_pattern(support=["F_A", "F_UNKNOWN"])),
            Op001ModelPattern.model_validate(raw_pattern(subjects=[{"entity_type": "plant", "entity_id": "PL01"}])),
            Op001ModelPattern.model_validate(
                raw_pattern(
                    support=["F_A", "F_B"],
                    subjects=[{"entity_type": "plant", "entity_id": "PL02"}],
                )
            ),
        ]
    )

    result = convert_op001_model_response(response, model_input)

    assert result.candidates == []
    assert [rejection.failure_category for rejection in result.rejections] == [
        "support",
        "subject_grounding",
        "subject_grounding",
    ]


def test_candidate_construction_uses_op001_owned_category_and_minimal_metadata(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context, _, _, _ = setup_context(repo)
    model_input = project_op001_model_input(context, repo)
    response = Op001ModelResponse(patterns=[Op001ModelPattern.model_validate(raw_pattern(pattern_type="recurring"))])

    candidate = convert_op001_model_response(response, model_input).candidates[0]

    assert candidate.category == OP001_CATEGORY
    assert candidate.metadata == {"pattern_type": "recurring"}
    assert candidate.supporting_finding_ids == ["F_A", "F_B"]
    assert candidate.subjects == [EntityReference(entity_type="machine", entity_id="M14")]
    assert candidate.significance == "medium"
    assert candidate.title == "Grounded pattern"
    assert candidate.synthesis == "A bounded structured output pattern."


def test_partial_response_keeps_valid_siblings_and_does_not_repair_invalid_item(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context, _, _, _ = setup_context(repo)
    model_input = project_op001_model_input(context, repo)
    response = Op001ModelResponse(
        patterns=[
            Op001ModelPattern.model_validate(raw_pattern(support=["F_A", "F_B"])),
            Op001ModelPattern.model_validate(raw_pattern(support=["F_A", "F_UNKNOWN"])),
            Op001ModelPattern.model_validate(raw_pattern(support=["F_B", "F_C"], subjects=[])),
        ]
    )

    result = convert_op001_model_response(response, model_input)

    assert len(result.candidates) == 2
    assert len(result.rejections) == 1
    assert result.rejections[0].pattern_index == 1
    assert result.candidates[0].supporting_finding_ids == ["F_A", "F_B"]
    assert result.candidates[1].supporting_finding_ids == ["F_B", "F_C"]


def test_valid_zero_result_is_successful_one_invocation_with_model_run(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context, _, _, _ = setup_context(repo)
    provider = StubProvider('{"patterns":[]}')

    result = run_intelligence_operation(Op001ModelAssistedOperation(provider), context, repo)

    assert result.run.status == "succeeded"
    assert result.run.candidates_count == 0
    assert result.run.model_runs_count == 1
    assert provider.calls == 1
    row = repo.connection.execute("SELECT provider, status, intelligence_run_id FROM model_runs").fetchone()
    assert dict(row) == {
        "provider": "stub-provider",
        "status": "succeeded",
        "intelligence_run_id": result.run.run_id,
    }


@pytest.mark.parametrize("exc", [RuntimeError("provider unavailable"), TimeoutError("timeout")])
def test_provider_failures_are_not_converted_to_empty_success(tmp_path, exc) -> None:
    repo = make_repo(tmp_path)
    context, _, _, _ = setup_context(repo)
    provider = StubProvider(exc)

    result = run_intelligence_operation(Op001ModelAssistedOperation(provider), context, repo)

    assert result.run.status == "failed"
    assert result.run.failure_category == "execution"
    assert result.run.model_runs_count == 1
    assert provider.calls == 1
    row = repo.connection.execute("SELECT status, error FROM model_runs").fetchone()
    assert row["status"] == "failed"
    assert row["error"] == f"{type(exc).__name__}: message withheld"
    assert str(exc) not in row["error"]


def test_malformed_top_level_response_is_not_converted_to_empty_success_or_retried(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context, _, _, _ = setup_context(repo)
    provider = StubProvider("{}")

    result = run_intelligence_operation(Op001ModelAssistedOperation(provider), context, repo)

    assert result.run.status == "failed"
    assert result.run.failure_category == "execution"
    assert result.run.model_runs_count == 1
    assert "model response does not match OP-001 schema" in result.run.error
    assert provider.calls == 1
    row = repo.connection.execute("SELECT status, error FROM model_runs").fetchone()
    assert row["status"] == "succeeded"
    assert row["error"] is None


def test_operation_projects_input_and_converts_valid_model_output_through_runtime(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context, _, _, _ = setup_context(repo)
    provider = StubProvider(raw_response([raw_pattern()]))

    result = run_intelligence_operation(
        Op001ModelAssistedOperation(provider, inference_parameters={"temperature": 0, "max_output_tokens": 512}),
        context,
        repo,
    )

    assert result.run.status == "succeeded"
    assert result.run.candidates_count == 1
    assert result.run.promoted_count == 1
    assert result.run.model_runs_count == 1
    assert provider.calls == 1
    assert provider.last_task == OP001_INSTRUCTIONS  # operation-owned instructions travel as the generic task
    assert [finding["finding_id"] for finding in provider.last_context["findings"]] == ["F_A", "F_B", "F_C"]
    # Inference parameters come from operation construction and are passed to the provider ...
    assert provider.last_inference_parameters == {"max_output_tokens": 512, "temperature": 0}
    # ... but this provider reports no effective parameters, so none are recorded as effective.
    model_run = repo.connection.execute("SELECT inference_parameters_json FROM model_runs").fetchone()
    assert model_run["inference_parameters_json"] == "null"
    run_row = repo.connection.execute("SELECT effective_configuration_json FROM intelligence_runs").fetchone()
    assert run_row["effective_configuration_json"] == "{}"


def test_model_output_rejections_are_not_runtime_candidate_rejections(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context, _, _, _ = setup_context(repo)
    provider = StubProvider(
        raw_response(
            [
                raw_pattern(support=["F_A", "F_UNKNOWN"]),
                raw_pattern(support=["F_A", "F_B"]),
            ]
        )
    )
    operation = Op001ModelAssistedOperation(provider)

    result = run_intelligence_operation(operation, context, repo)

    assert result.run.status == "succeeded"
    assert result.run.candidates_count == 1
    assert result.run.promoted_count == 1
    assert result.run.rejected_count == 0
    assert len(operation.model_output_rejections) == 1
    assert repo.connection.execute("SELECT COUNT(*) FROM intelligence_candidate_rejections").fetchone()[0] == 0


def test_no_raw_model_io_persistence_columns_added(tmp_path) -> None:
    repo = make_repo(tmp_path)

    model_columns = [row["name"] for row in repo.connection.execute("PRAGMA table_info(model_runs)")]

    assert "raw_prompt" not in model_columns
    assert "raw_model_input" not in model_columns
    assert "raw_response" not in model_columns
    assert "raw_model_output" not in model_columns
    assert "chain_of_thought" not in model_columns
