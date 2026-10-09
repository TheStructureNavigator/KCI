"""Wave 2B: analytical / inference / infrastructure configuration boundary and error hygiene."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from kci import error_hygiene
from kci.error_hygiene import ConfigurationIssueError, ConfigurationReason, safe_error_message, trusted_message_type
from kci.models import (
    InferenceParametersError,
    LlamaCppCliProvider,
    LlamaCppCliProviderError,
    ModelProvider,
)
from kci.operations import (
    IntelligenceOperation,
    Op001ModelAssistedOperation,
    OperationConfiguration,
    OperationConfigurationError,
)
from kci.runtime import IntelligencePreconditionFailed, PreconditionReason, run_intelligence_operation
from tests.test_llama_cpp_cli_provider import (
    RecordingRunner,
    ScriptedRunner,
    make_files,
    make_provider,
    make_repo,
    model_run_rows,
    persist_context,
)

SECRET = "sk-SECRET-VALUE-123"


class CapturingProvider(ModelProvider):
    provider_name = "capturing"

    def __init__(self, outcome: Any = '{"patterns":[]}') -> None:
        self.outcome = outcome
        self.calls = 0
        self.received: dict[str, Any] | None = None

    def generate(self, task, context, output_schema, inference_parameters=None):
        self.calls += 1
        self.received = inference_parameters
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def persisted_text(repo) -> str:
    """Everything persisted by a run, as one string, for leak assertions."""
    parts = []
    for table in ("intelligence_runs", "model_runs", "intelligence_candidate_rejections"):
        for row in repo.connection.execute(f"SELECT * FROM {table}"):
            parts.append(json.dumps(dict(row), default=str))
    return "\n".join(parts)


# --- A/B: analytical configuration and runtime lifecycle ---------------------------------------


def test_op001_empty_and_missing_configuration_resolve_to_empty_analytical_configuration(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)

    for requested in (None, {}):
        result = run_intelligence_operation(Op001ModelAssistedOperation(CapturingProvider()), context, repo, requested)
        assert result.run.status == "succeeded"
        assert result.run.effective_configuration == {}

    rows = repo.connection.execute("SELECT effective_configuration_json FROM intelligence_runs").fetchall()
    assert [row[0] for row in rows] == ["{}", "{}"]


@pytest.mark.parametrize(
    "key",
    [
        "unknown_key",  # unknown analytical key
        "executable_path", "model_path", "timeout_s", "api_key", "password", "token", "environment",  # infrastructure
        "threads", "gpu_layers", "ctx_size",  # provider-owned settings
        "temperature", "top_p", "max_output_tokens", "seed",  # inference parameters
    ],
)
def test_op001_rejects_every_key_as_analytical_configuration_without_persisting_it(tmp_path, key) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    provider = CapturingProvider()

    result = run_intelligence_operation(Op001ModelAssistedOperation(provider), context, repo, {key: SECRET})

    assert result.run.status == "requirements_failed"
    assert result.run.failure_category == "requirements"
    assert result.run.effective_configuration == {}
    assert result.run.model_runs_count == 0
    assert provider.calls == 0  # the operation was never invoked
    assert model_run_rows(repo) == []  # and no ModelRun exists
    assert f"{key}:unknown_field" in result.run.error
    persisted = persisted_text(repo)
    assert SECRET not in persisted
    assert SECRET not in result.run.error
    row = repo.connection.execute("SELECT status, failure_category, effective_configuration_json FROM intelligence_runs").fetchone()
    assert tuple(row) == ("requirements_failed", "requirements", "{}")


def test_non_mapping_configuration_is_rejected_as_requirements_failure(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)

    result = run_intelligence_operation(Op001ModelAssistedOperation(CapturingProvider()), context, repo, [SECRET])  # type: ignore[arg-type]

    assert result.run.status == "requirements_failed"
    assert SECRET not in persisted_text(repo)


class TypedOperation(IntelligenceOperation):
    """A future operation: declares its own typed analytical configuration."""

    class Configuration(OperationConfiguration):
        minimum_support: int = 2

    operation_id = "synthetic.typed"
    operation_version = "1"
    deterministic = True
    configuration_model = Configuration

    def __init__(self) -> None:
        self.invoked = False

    def synthesize(self, context, configuration):
        self.invoked = True
        return []


def test_typed_configuration_materializes_defaults_and_is_extensible(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)

    defaulted = run_intelligence_operation(TypedOperation(), context, repo)
    explicit = run_intelligence_operation(TypedOperation(), context, repo, {"minimum_support": 3})

    assert defaulted.run.effective_configuration == {"minimum_support": 2}
    assert explicit.run.effective_configuration == {"minimum_support": 3}
    assert [r[0] for r in repo.connection.execute("SELECT effective_configuration_json FROM intelligence_runs")] == [
        '{"minimum_support":2}',
        '{"minimum_support":3}',
    ]


@pytest.mark.parametrize("bad", [{"minimum_support": "not-a-number-" + SECRET}, {"minimum_support": True}, {"extra": 1}])
def test_typed_configuration_type_errors_and_unknown_keys_fail_before_invocation(tmp_path, bad) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    operation = TypedOperation()

    result = run_intelligence_operation(operation, context, repo, bad)

    assert operation.invoked is False
    assert result.run.status == "requirements_failed"
    assert result.run.failure_category == "requirements"
    assert result.run.effective_configuration == {}
    assert SECRET not in persisted_text(repo)


def test_invalid_configuration_never_invokes_operation_even_when_context_is_valid(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    operation = TypedOperation()

    run_intelligence_operation(operation, context, repo, {"minimum_support": "x"})

    assert operation.invoked is False
    assert repo.connection.execute("SELECT COUNT(*) FROM insights").fetchone()[0] == 0


def test_valid_configuration_keeps_existing_lifecycle(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    operation = TypedOperation()

    result = run_intelligence_operation(operation, context, repo, {"minimum_support": 4})

    assert operation.invoked is True
    assert result.run.status == "succeeded"
    assert result.run.finished_at is not None


def test_configuration_error_is_a_persistable_non_sensitive_message() -> None:
    with pytest.raises(OperationConfigurationError) as caught:
        TypedOperation().effective_configuration({"minimum_support": SECRET, SECRET: 1})
    assert SECRET not in str(caught.value)


# --- C: inference ownership at operation construction ------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"temperature": -0.1},
        {"temperature": "hot"},
        {"temperature": True},
        {"temperature": float("nan")},
        {"top_p": 0},
        {"top_p": 1.5},
        {"max_output_tokens": 0},
        {"max_output_tokens": 1.5},
        {"max_output_tokens": True},
        {"seed": -1},
        {"seed": "7"},
        {"threads": 4},  # provider-owned, not an operation inference parameter
        {"gpu_layers": 1},
        {"ctx_size": 2048},
        {"bogus": SECRET},
    ],
)
def test_operation_construction_rejects_invalid_inference_parameters(bad) -> None:
    with pytest.raises(InferenceParametersError) as caught:
        Op001ModelAssistedOperation(CapturingProvider(), bad)

    assert SECRET not in str(caught.value)
    assert "message withheld" not in str(caught.value)


def test_inference_parameters_supplied_at_construction_reach_the_provider_and_not_the_run_configuration(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    provider = CapturingProvider()
    inference = {"temperature": 0.2, "top_p": 0.9, "max_output_tokens": 256, "seed": 3}

    result = run_intelligence_operation(Op001ModelAssistedOperation(provider, inference), context, repo)

    assert provider.received == inference
    assert result.run.effective_configuration == {}
    row = repo.connection.execute("SELECT effective_configuration_json FROM intelligence_runs").fetchone()
    assert row[0] == "{}"


def test_operation_inference_parameters_are_a_snapshot(tmp_path) -> None:
    source = {"temperature": 0.2}
    operation = Op001ModelAssistedOperation(CapturingProvider(), source)

    source["temperature"] = 99
    operation.inference_parameters["temperature"] = 98  # a returned copy

    assert operation.inference_parameters == {"temperature": 0.2}


# --- D/E: provider validation, defaults and effective-parameter telemetry ----------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"temperature": "hot"},
        {"temperature": -1},
        {"top_p": [1, 2]},
        {"max_output_tokens": -5},
        {"seed": True},
        {"threads": 0},  # provider-owned: rejected as a per-call value (see next test) and as a default
    ],
)
def test_provider_rejects_invalid_values_before_any_process_starts(tmp_path, bad) -> None:
    runner = RecordingRunner()
    provider = make_provider(tmp_path, runner)

    with pytest.raises(LlamaCppCliProviderError) as caught:
        provider.generate("task", {}, {"type": "object"}, bad)

    assert caught.value.category == "configuration"
    assert caught.value.duration_ms is None
    assert caught.value.inference_parameters is None
    assert runner.calls == []


@pytest.mark.parametrize("owned", ["threads", "gpu_layers", "ctx_size"])
def test_provider_owned_settings_cannot_be_set_per_call(tmp_path, owned) -> None:
    runner = RecordingRunner()
    provider = make_provider(tmp_path, runner, default_inference_parameters={owned: 2})

    with pytest.raises(LlamaCppCliProviderError) as caught:
        provider.generate("task", {}, {"type": "object"}, {owned: 3})

    assert "provider-owned" in str(caught.value) and owned in str(caught.value)
    assert runner.calls == []


@pytest.mark.parametrize(
    "bad_default",
    [{"threads": 0}, {"ctx_size": "big"}, {"gpu_layers": -1}, {"gpu_layers": "most"}, {"temperature": -1}, {"bogus": 1}],
)
def test_provider_construction_rejects_invalid_defaults(tmp_path, bad_default) -> None:
    executable, model = make_files(tmp_path)

    with pytest.raises(LlamaCppCliProviderError) as caught:
        LlamaCppCliProvider(executable, model, timeout_s=3, default_inference_parameters=bad_default)

    assert caught.value.category == "configuration"


def test_provider_accepts_existing_default_forms(tmp_path) -> None:
    make_provider(tmp_path, RecordingRunner(), default_inference_parameters={"gpu_layers": "all", "ctx_size": 4096, "threads": 4, "top_p": 0.9})
    make_provider(tmp_path, RecordingRunner(), default_inference_parameters={"gpu_layers": 0, "temperature": 0})


def test_effective_parameters_merge_provider_defaults_and_operation_parameters_into_the_model_run(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    provider = make_provider(
        tmp_path, ScriptedRunner('{"patterns":[]}'), default_inference_parameters={"threads": 4, "ctx_size": 2048, "seed": 1}
    )

    result = run_intelligence_operation(Op001ModelAssistedOperation(provider, {"temperature": 0.2}), context, repo)

    (row,) = model_run_rows(repo)
    assert json.loads(row["inference_parameters_json"]) == {"ctx_size": 2048, "seed": 1, "temperature": 0.2, "threads": 4}
    assert result.run.effective_configuration == {}  # provider-owned settings never enter run configuration


def test_engine_defaults_are_not_invented(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    provider = make_provider(tmp_path, ScriptedRunner('{"patterns":[]}'))

    run_intelligence_operation(Op001ModelAssistedOperation(provider), context, repo)

    (row,) = model_run_rows(repo)
    assert row["inference_parameters_json"] == "{}"  # nothing was resolved explicitly, nothing is claimed


def test_unknown_effective_parameters_are_json_null(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)

    run_intelligence_operation(Op001ModelAssistedOperation(CapturingProvider(), {"temperature": 0.2}), context, repo)
    run_intelligence_operation(Op001ModelAssistedOperation(CapturingProvider(RuntimeError("x")), {"temperature": 0.2}), context, repo)

    assert [r["inference_parameters_json"] for r in model_run_rows(repo)] == ["null", "null"]


# --- F: error hygiene -------------------------------------------------------------------------


def test_foreign_exception_text_is_not_persisted(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    leaky = RuntimeError(f"cannot open /home/deploy/models/secret.gguf token={SECRET} C:\\llama\\llama-completion.exe")

    result = run_intelligence_operation(Op001ModelAssistedOperation(CapturingProvider(leaky)), context, repo)

    persisted = persisted_text(repo)
    for fragment in (SECRET, "/home/deploy", "secret.gguf", "C:\\\\llama", "llama-completion.exe"):
        assert fragment not in persisted
    assert result.run.error == "RuntimeError: message withheld"
    assert model_run_rows(repo)[0]["error"] == "RuntimeError: message withheld"


@pytest.mark.parametrize(
    "outcome, expected",
    [
        (FileNotFoundError(2, "No such file or directory", "/opt/llama/llama-completion"), "could not start llama.cpp CLI process"),
        (RuntimeError(f"runner crashed with password={SECRET}"), "provider process runner failed"),
    ],
)
def test_real_provider_failures_persist_only_stable_messages(tmp_path, outcome, expected) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    provider = make_provider(tmp_path, ScriptedRunner(outcome))

    result = run_intelligence_operation(Op001ModelAssistedOperation(provider), context, repo)

    assert result.run.status == "failed"
    assert result.run.error == expected
    assert model_run_rows(repo)[0]["error"] == expected
    persisted = persisted_text(repo)
    assert SECRET not in persisted and "/opt/llama" not in persisted and str(tmp_path) not in persisted


def test_malformed_model_output_is_not_persisted_in_error_text(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    leaked = f'{{"patterns":[{{"title":"{SECRET}","unexpected":"{SECRET}"}}]}}'

    result = run_intelligence_operation(Op001ModelAssistedOperation(CapturingProvider(leaked)), context, repo)

    assert result.run.status == "failed"
    assert "model response does not match OP-001 schema" in result.run.error
    assert SECRET not in persisted_text(repo)


def test_operation_exception_text_is_not_persisted(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)

    class Leaky(TypedOperation):
        def synthesize(self, context, configuration):
            raise RuntimeError(f"opened /var/lib/kci/private.db with {SECRET}")

    result = run_intelligence_operation(Leaky(), context, repo)

    assert result.run.status == "failed"
    assert result.run.failure_category == "execution"
    assert SECRET not in persisted_text(repo) and "/var/lib" not in persisted_text(repo)


def test_provider_error_messages_contain_no_paths_or_values(tmp_path) -> None:
    executable, model = make_files(tmp_path)

    with pytest.raises(LlamaCppCliProviderError) as missing_exe:
        LlamaCppCliProvider(tmp_path / "nope" / "llama.exe", model, timeout_s=3)
    with pytest.raises(LlamaCppCliProviderError) as missing_model:
        LlamaCppCliProvider(executable, tmp_path / "nope" / "m.gguf", timeout_s=3)
    provider = make_provider(tmp_path, RecordingRunner())
    with pytest.raises(LlamaCppCliProviderError) as bad_value:
        provider.generate("t", {}, {"type": "object"}, {"temperature": SECRET})
    with pytest.raises(LlamaCppCliProviderError) as bad_key:
        provider.generate("t", {}, {"type": "object"}, {SECRET + "/with/path": 1})

    for error in (missing_exe, missing_model, bad_value, bad_key):
        assert str(tmp_path) not in str(error.value)
        assert SECRET not in str(error.value)
    assert "temperature" in str(bad_value.value)
    assert "<invalid-name>" in str(bad_key.value)


def test_timeout_and_nonzero_exit_messages_are_stable(tmp_path) -> None:
    for runner, expected in (
        (ScriptedRunner(subprocess.TimeoutExpired(["llama"], 1, stderr=b"/secret/path")), "llama.cpp CLI invocation timed out"),
        (RecordingRunner(returncode=2, stderr=f"token={SECRET}"), "llama.cpp CLI process exited with non-zero status"),
    ):
        provider = make_provider(tmp_path, runner)
        with pytest.raises(LlamaCppCliProviderError) as caught:
            provider.generate("t", {}, {"type": "object"})
        assert str(caught.value) == expected


# --- hardening: trust is explicit, exact-type and never inherited -------------------------------


class Legacy(IntelligenceOperation):
    operation_id = "legacy.custom"
    operation_version = "1"
    deterministic = True

    def synthesize(self, context, configuration):
        return []


def test_custom_operation_cannot_persist_free_form_text_through_operation_configuration_error(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)

    class Leaky(Legacy):
        def effective_configuration(self, requested_configuration=None):
            raise OperationConfigurationError(f"minimum_support invalid, got {SECRET}")  # type: ignore[arg-type]

    result = run_intelligence_operation(Leaky(), context, repo)

    # The closed constructor refuses free text, so the author sees a TypeError, not a persisted secret.
    assert result.run.status == "failed"
    assert result.run.error == "TypeError: message withheld"
    assert SECRET not in persisted_text(repo)


def test_operation_configuration_error_accepts_only_field_and_reason_pairs() -> None:
    for bad in (SECRET, [SECRET], [("field", "invalid_value")], [("field", SECRET, ConfigurationReason.INVALID_VALUE)]):
        with pytest.raises(TypeError) as caught:
            OperationConfigurationError(bad)  # type: ignore[arg-type]
        assert SECRET not in str(caught.value)
    with pytest.raises(TypeError):
        InferenceParametersError(SECRET)  # type: ignore[arg-type]


def test_custom_operation_can_still_reject_configuration_with_controlled_reasons(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)

    class Strict(Legacy):
        def effective_configuration(self, requested_configuration=None):
            raise OperationConfigurationError([("minimum_support", ConfigurationReason.INVALID_VALUE), (SECRET, ConfigurationReason.UNKNOWN_FIELD)])

    result = run_intelligence_operation(Strict(), context, repo)

    assert result.run.status == "requirements_failed"
    assert result.run.failure_category == "requirements"
    assert result.run.error == "invalid operation configuration: minimum_support:invalid_value, <invalid-name>:unknown_field"
    assert SECRET not in persisted_text(repo)


def test_subclass_of_a_trusted_error_gains_no_persistence_trust_by_inheritance(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)

    class LeakyConfigError(OperationConfigurationError):
        def __init__(self, message: str) -> None:  # an author bypassing the closed constructor
            ValueError.__init__(self, message)

    class LeakyProviderError(LlamaCppCliProviderError):
        pass

    class Config(Legacy):
        def effective_configuration(self, requested_configuration=None):
            raise LeakyConfigError(f"bad value {SECRET}")

    config_result = run_intelligence_operation(Config(), context, repo)
    provider_result = run_intelligence_operation(
        Op001ModelAssistedOperation(CapturingProvider(LeakyProviderError("timeout", f"leaked {SECRET}"))), context, repo
    )

    # Still classified by isinstance (status/category preserved), but the text is withheld.
    assert config_result.run.status == "requirements_failed"
    assert config_result.run.failure_category == "requirements"
    assert config_result.run.error == "LeakyConfigError: message withheld"
    assert provider_result.run.status == "failed"
    assert provider_result.run.error == "LeakyProviderError: message withheld"
    assert model_run_rows(repo)[0]["error"] == "LeakyProviderError: message withheld"
    assert SECRET not in persisted_text(repo)


def test_unregistered_error_types_are_withheld_even_if_they_look_like_kci_errors() -> None:
    class Unapproved(ConfigurationIssueError):
        pass

    class Plain(RuntimeError):
        pass

    assert safe_error_message(Unapproved([("a", ConfigurationReason.INVALID_TYPE)])) == "Unapproved: message withheld"
    assert safe_error_message(Plain(SECRET)) == "Plain: message withheld"
    assert safe_error_message(ValueError(SECRET)) == "ValueError: message withheld"
    assert not hasattr(error_hygiene, "PersistableError")  # the inheritable marker no longer exists


def test_registering_a_type_trusts_only_that_exact_type() -> None:
    @trusted_message_type
    class Approved(RuntimeError):
        pass

    class Child(Approved):
        pass

    assert safe_error_message(Approved("fixed text")) == "fixed text"
    assert safe_error_message(Child("fixed text")) == "Child: message withheld"
    error_hygiene._TRUSTED_TYPES.discard(Approved)  # keep the pinned registry clean


def test_trusted_error_registry_is_pinned() -> None:
    assert {f"{cls.__module__}.{cls.__qualname__}" for cls in error_hygiene.trusted_error_types()} == {
        "kci.models.base.InferenceParametersError",
        "kci.models.llama_cpp.LlamaCppCliProviderError",
        "kci.operations.base.OperationConfigurationError",
        "kci.operations.uatu_op001.Op001MalformedModelResponse",
        "kci.operations.uatu_op001.Op001ModelInvocationError",
        "kci.runtime.intelligence_runner.IntelligencePreconditionFailed",
    }


def test_precondition_error_has_a_closed_constructor_and_keeps_its_messages() -> None:
    with pytest.raises(TypeError):
        IntelligencePreconditionFailed(f"free text {SECRET}")  # type: ignore[arg-type]
    assert safe_error_message(IntelligencePreconditionFailed(PreconditionReason.CONTEXT_NOT_PERSISTED)) == (
        "intelligence_context_id is not persisted"
    )


def test_unpersisted_context_still_reports_a_useful_requirements_message(tmp_path) -> None:
    from kci.contracts import IntelligenceContext

    repo = make_repo(tmp_path)
    persist_context(repo)

    result = run_intelligence_operation(
        Op001ModelAssistedOperation(CapturingProvider()), IntelligenceContext(finding_ids=("F_A", "NOPE")), repo
    )

    assert result.run.status == "requirements_failed"
    assert result.run.failure_category == "requirements"
    assert result.run.error == "intelligence_context_id is not persisted"


def test_approved_messages_remain_useful(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)

    config = run_intelligence_operation(Op001ModelAssistedOperation(CapturingProvider()), context, repo, {"api_key": SECRET})
    with pytest.raises(InferenceParametersError) as inference:
        Op001ModelAssistedOperation(CapturingProvider(), {"temperature": -1, "bogus": SECRET})
    provider = make_provider(tmp_path, RecordingRunner())
    with pytest.raises(LlamaCppCliProviderError) as value_error:
        provider.generate("t", {}, {"type": "object"}, {"temperature": SECRET})

    assert config.run.error == "invalid operation configuration: api_key:unknown_field"
    assert str(inference.value).startswith("invalid inference parameters: ")
    assert "bogus:unknown_field" in str(inference.value) and "temperature:invalid_value" in str(inference.value)
    assert SECRET not in str(inference.value)
    assert str(value_error.value) == "invalid inference parameter value(s): temperature"
    assert safe_error_message(value_error.value) == "invalid inference parameter value(s): temperature"
