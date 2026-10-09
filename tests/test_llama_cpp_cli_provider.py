from __future__ import annotations

import hashlib
import json
import subprocess
import threading
from unittest import mock
from typing import Any

import pytest

from kci.contracts import EntityReference, EvidenceReference, Finding, IntelligenceContext, ObserverRun
from kci.models import LlamaCppCliProvider, LlamaCppCliProviderError, ModelProvider
from kci.models.llama_cpp import _decode_llama_completion_framing
from kci.operations import Op001ModelAssistedOperation
from kci.persistence import KciRepository, connect, initialize_database
from kci.runtime import run_intelligence_operation


class RecordingRunner:
    def __init__(self, returncode: int = 0, stdout: str = '{"patterns":[]}', stderr: str = "diagnostic") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": argv, **kwargs})
        return subprocess.CompletedProcess(argv, self.returncode, stdout=self.stdout, stderr=self.stderr)


def make_files(tmp_path):
    executable = tmp_path / "llama-completion.exe"
    model = tmp_path / "model.gguf"
    executable.write_text("fake executable", encoding="utf-8")
    model.write_bytes(b"tiny fake gguf bytes")
    return executable, model


def make_provider(tmp_path, runner=None, **kwargs) -> LlamaCppCliProvider:
    executable, model = make_files(tmp_path)
    return LlamaCppCliProvider(
        executable,
        model,
        timeout_s=kwargs.pop("timeout_s", 3),
        process_runner=runner or RecordingRunner(),
        **kwargs,
    )


def test_provider_boundary_is_generic_and_requires_explicit_configuration(tmp_path) -> None:
    executable, model = make_files(tmp_path)
    provider = LlamaCppCliProvider(executable, model, timeout_s=3, process_runner=RecordingRunner())

    assert provider.provider_name == "llama_cpp_cli"
    assert provider.executable == executable
    assert provider.model_path == model
    assert not hasattr(provider, "Op001ModelInput")


def test_missing_executable_or_model_is_configuration_failure(tmp_path) -> None:
    executable, model = make_files(tmp_path)

    with pytest.raises(LlamaCppCliProviderError) as missing_exe:
        LlamaCppCliProvider(tmp_path / "missing.exe", model, timeout_s=1)
    with pytest.raises(LlamaCppCliProviderError) as missing_model:
        LlamaCppCliProvider(executable, tmp_path / "missing.gguf", timeout_s=1)

    assert missing_exe.value.category == "configuration"
    assert missing_model.value.category == "configuration"


def test_direct_subprocess_invocation_sends_dynamic_request_on_prompt_argv(tmp_path) -> None:
    runner = RecordingRunner(stdout='{"ok":true}', stderr="stderr text")
    provider = make_provider(tmp_path, runner, default_inference_parameters={"temperature": 0, "max_output_tokens": 5})

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    output = provider.generate("task.α", {"hello": "zażółć"}, schema, inference_parameters={"seed": 7})

    call = runner.calls[0]
    argv = call["argv"]
    assert output == '{"ok":true}'
    assert argv[0].endswith("llama-completion.exe")
    assert call["shell"] is False
    assert call["text"] is True
    assert call["encoding"] == "utf-8"
    assert call["capture_output"] is True
    assert "input" not in call
    assert "--offline" in argv
    assert "--no-conversation" in argv
    assert "--no-display-prompt" in argv
    assert "--json-schema" in argv
    schema_index = argv.index("--json-schema")
    assert json.loads(argv[schema_index + 1]) == schema
    assert isinstance(argv[schema_index + 1], str)
    assert "--json-schema-file" not in argv
    assert "--prompt" in argv
    prompt_index = argv.index("--prompt")
    assert json.loads(argv[prompt_index + 1]) == {"task": "task.α", "context": {"hello": "zażółć"}}
    assert "--temp" in argv
    assert "--predict" in argv
    assert "--seed" in argv
    assert provider.last_invocation is not None
    assert provider.last_invocation.stdout == '{"ok":true}'
    assert provider.last_invocation.stderr == "stderr text"
    assert provider.last_invocation.provider_duration_ms >= 0


def test_effective_completion_parameters_are_mapped_explicitly(tmp_path) -> None:
    runner = RecordingRunner()
    provider = make_provider(
        tmp_path,
        runner,
        default_inference_parameters={"gpu_layers": "all", "ctx_size": 4096, "threads": 4, "top_p": 0.9},
    )

    provider.generate("task", {}, {"type": "object"})

    argv = runner.calls[0]["argv"]
    assert "--gpu-layers" in argv
    assert "all" in argv
    assert "--ctx-size" in argv
    assert "4096" in argv
    assert "--threads" in argv
    assert "4" in argv
    assert "--top-p" in argv
    assert "0.9" in argv


@pytest.mark.parametrize(
    ("stdout", "decoded"),
    [
        ('{"x":1} [end of text]', '{"x":1}'),
        ('{"x":1}', '{"x":1}'),
        ("text [end of text] more text", "text [end of text] more text"),
        ('{"message":"[end of text]"}', '{"message":"[end of text]"}'),
        ('{"x": [end of text]', '{"x":'),
        ('```json\n{"x":1}\n``` [end of text]', '```json\n{"x":1}\n```'),
        ("first [end of text] second [end of text]", "first [end of text] second"),
        ('{"x":1} [end of text]\n\n\n', '{"x":1}'),
        ('{"x":1} [end of text]\r\n', '{"x":1}'),
    ],
)
def test_llama_completion_terminal_framing_decoder_only_removes_terminal_sentinel(stdout, decoded) -> None:
    assert _decode_llama_completion_framing(stdout) == decoded


def test_successful_provider_response_decodes_llama_completion_terminal_framing(tmp_path) -> None:
    provider = make_provider(tmp_path, RecordingRunner(stdout='{"patterns":[]} [end of text]\n\n\n'))

    result = provider.generate("task", {}, {"type": "object"})

    assert result == '{"patterns":[]}'
    assert provider.last_invocation is not None
    assert provider.last_invocation.stdout == '{"patterns":[]} [end of text]\n\n\n'


def test_nonzero_exit_code_is_process_execution_failure(tmp_path) -> None:
    runner = RecordingRunner(returncode=42, stdout="", stderr="bad things happened")
    provider = make_provider(tmp_path, runner)

    with pytest.raises(LlamaCppCliProviderError) as exc_info:
        provider.generate("task", {}, {"type": "object"})

    assert exc_info.value.category == "process_execution"
    assert exc_info.value.exit_code == 42
    assert exc_info.value.stderr_excerpt == "bad things happened"


def test_os_start_failure_is_process_start_failure(tmp_path) -> None:
    def fail_start(*args, **kwargs):
        raise OSError("cannot spawn")

    provider = make_provider(tmp_path, fail_start)

    with pytest.raises(LlamaCppCliProviderError) as exc_info:
        provider.generate("task", {}, {"type": "object"})

    assert exc_info.value.category == "process_start"


def test_timeout_is_timeout_category_and_releases_active_invocation(tmp_path) -> None:
    calls = {"count": 0}

    def timeout_then_success(argv, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"], stderr=b"too slow")
        return subprocess.CompletedProcess(argv, 0, stdout='{"patterns":[]}', stderr="")

    provider = make_provider(tmp_path, timeout_then_success, timeout_s=0.1)

    with pytest.raises(LlamaCppCliProviderError) as exc_info:
        provider.generate("task", {}, {"type": "object"})
    provider.generate("task", {}, {"type": "object"})

    assert exc_info.value.category == "timeout"
    assert exc_info.value.stderr_excerpt == "too slow"
    assert calls["count"] == 2


def test_required_schema_is_applied_and_missing_schema_fails_explicitly(tmp_path) -> None:
    runner = RecordingRunner()
    provider = make_provider(tmp_path, runner)

    with pytest.raises(LlamaCppCliProviderError) as exc_info:
        provider.generate("task", {}, {})
    provider.generate("task", {}, {"type": "object", "properties": {"patterns": {"type": "array"}}})

    assert exc_info.value.category == "configuration"
    assert "--json-schema" in runner.calls[0]["argv"]


def test_provider_returns_raw_output_not_op001_response(tmp_path) -> None:
    runner = RecordingRunner(stdout='{"patterns":[]}')
    provider = make_provider(tmp_path, runner)

    result = provider.generate("task", {}, {"type": "object"})

    assert result == '{"patterns":[]}'
    assert isinstance(result, str)


def test_model_artifact_hash_is_sha256_and_not_filename_identity(tmp_path) -> None:
    executable, model = make_files(tmp_path)
    provider = LlamaCppCliProvider(executable, model, timeout_s=3, process_runner=RecordingRunner())

    assert provider.model_artifact_hash == hashlib.sha256(b"tiny fake gguf bytes").hexdigest()
    assert provider.model_artifact_hash != model.name
    assert provider.runtime_version == "unknown"
    before = provider.model_artifact_hash
    provider.generate("task", {}, {"type": "object"})
    assert provider.model_artifact_hash == before


def test_unsupported_inference_parameter_fails_without_unconstrained_fallback(tmp_path) -> None:
    provider = make_provider(tmp_path)

    with pytest.raises(LlamaCppCliProviderError) as exc_info:
        provider.generate("task", {}, {"type": "object"}, inference_parameters={"unsupported": True})

    assert exc_info.value.category == "configuration"


def test_at_most_one_active_inference_per_provider_instance(tmp_path) -> None:
    provider_holder: dict[str, LlamaCppCliProvider] = {}

    def nested_call(argv, **kwargs):
        with pytest.raises(LlamaCppCliProviderError) as exc_info:
            provider_holder["provider"].generate("nested", {}, {"type": "object"})
        assert exc_info.value.category == "provider_internal"
        return subprocess.CompletedProcess(argv, 0, stdout='{"patterns":[]}', stderr="")

    provider = make_provider(tmp_path, nested_call)
    provider_holder["provider"] = provider

    provider.generate("task", {}, {"type": "object"})


def test_no_temp_prompt_file_or_network_download_behavior(tmp_path) -> None:
    runner = RecordingRunner()
    provider = make_provider(tmp_path, runner)
    before = {path.name for path in tmp_path.iterdir()}

    provider.generate("task", {"request": "sensitive"}, {"type": "object"})

    after = {path.name for path in tmp_path.iterdir()}
    assert after == before
    assert len(runner.calls) == 1
    assert "--json-schema-file" not in runner.calls[0]["argv"]


def make_repo(tmp_path) -> KciRepository:
    connection = connect(tmp_path / "kci.sqlite3")
    initialize_database(connection)
    return KciRepository(connection)


def persist_context(repository: KciRepository) -> IntelligenceContext:
    run = ObserverRun.started("observer.alpha", "1", "ctx", {}, "dataset", "snapshot")
    run.status = "succeeded"
    repository.save_observer_run(run)
    for finding_id in ["F_A", "F_B"]:
        finding = Finding(
            finding_id=finding_id,
            observer_run_id=run.run_id,
            observer_id=run.observer_id,
            observer_version=run.observer_version,
            category="synthetic.finding",
            severity="medium",
            subjects=[EntityReference(entity_type="machine", entity_id="M14")],
            title=f"{finding_id} title",
            observation=f"{finding_id} observation",
            evidence=[EvidenceReference(dataset="dataset", snapshot_id="snapshot", ref=f"event:{finding_id}")],
            metadata={},
        )
        repository.save_finding(run.run_id, finding)
    context = IntelligenceContext(finding_ids=("F_A", "F_B"))
    repository.save_intelligence_context(context)
    return context


def test_op001_integration_with_cli_provider_success_and_zero_output(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    provider = make_provider(tmp_path, RecordingRunner(stdout='{"patterns":[]}'), default_inference_parameters={"temperature": 0})

    result = run_intelligence_operation(Op001ModelAssistedOperation(provider), context, repo)

    assert result.run.status == "succeeded"
    assert result.run.candidates_count == 0
    assert result.run.model_runs_count == 1
    row = repo.connection.execute(
        "SELECT provider, model_artifact_hash, inference_parameters_json, status, total_ms FROM model_runs"
    ).fetchone()
    assert row["provider"] == "llama_cpp_cli"
    assert row["model_artifact_hash"] == provider.model_artifact_hash
    assert row["inference_parameters_json"] == '{"temperature":0}'
    assert row["status"] == "succeeded"
    assert row["total_ms"] is not None


def test_op001_integration_provider_failure_fails_model_run_and_intelligence_run(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    provider = make_provider(tmp_path, RecordingRunner(returncode=2, stdout="", stderr="failed"))

    result = run_intelligence_operation(Op001ModelAssistedOperation(provider), context, repo)

    assert result.run.status == "failed"
    assert result.run.failure_category == "execution"
    assert result.run.model_runs_count == 1
    row = repo.connection.execute("SELECT status, error FROM model_runs").fetchone()
    assert row["status"] == "failed"
    assert "process exited" in row["error"]


def test_op001_integration_malformed_output_is_operation_failure_not_provider_failure(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    provider = make_provider(tmp_path, RecordingRunner(stdout="not json"))

    result = run_intelligence_operation(Op001ModelAssistedOperation(provider), context, repo)

    assert result.run.status == "failed"
    assert result.run.model_runs_count == 1
    row = repo.connection.execute("SELECT status, error FROM model_runs").fetchone()
    assert row["status"] == "succeeded"
    assert row["error"] is None


class ScriptedRunner:
    """Process runner that replays one scripted outcome per call (value or exception)."""

    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)

    def __call__(self, argv, **kwargs):
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return subprocess.CompletedProcess(argv, 0, stdout=outcome, stderr="")


class FakeClock:
    """Deterministic replacement for the provider's perf_counter (seconds)."""

    def __init__(self, *readings: float) -> None:
        self.readings = list(readings)

    def __call__(self) -> float:
        return self.readings.pop(0)


def with_clock(*readings: float):
    return mock.patch("kci.models.llama_cpp.perf_counter", FakeClock(*readings))


def model_run_rows(repo: KciRepository):
    return repo.connection.execute(
        "SELECT status, total_ms, inference_parameters_json, error FROM model_runs ORDER BY created_at, rowid"
    ).fetchall()


def run_op001(provider, context, repo, configuration):
    return run_intelligence_operation(Op001ModelAssistedOperation(provider), context, repo, configuration)


class StubTelemetryProvider(ModelProvider):
    """Backend-neutral double: returns a plain str or raises a prepared exception."""

    provider_name = "stub-telemetry"

    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome

    def generate(self, task, context, output_schema, inference_parameters=None):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


# --- Part A / D.1, D.2: duration semantics ---------------------------------------------------


def test_successful_invocation_records_its_measured_duration_and_effective_parameters(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    provider = make_provider(tmp_path, ScriptedRunner('{"patterns":[]}'), default_inference_parameters={"seed": 7})

    with with_clock(10.0, 10.25):
        run_op001(provider, context, repo, {"temperature": 0.1})

    (row,) = model_run_rows(repo)
    assert row["status"] == "succeeded"
    assert row["total_ms"] == 250.0
    assert json.loads(row["inference_parameters_json"]) == {"seed": 7, "temperature": 0.1}


def test_pre_execution_rejection_records_null_duration_and_null_parameters(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    provider = make_provider(tmp_path, ScriptedRunner())

    with with_clock():  # any clock read would raise: nothing may be timed before execution
        result = run_op001(provider, context, repo, {"temperature": 0.9, "bogus": 1})

    (row,) = model_run_rows(repo)
    assert result.run.status == "failed"
    assert "unsupported inference parameter(s): bogus" in row["error"]
    assert row["total_ms"] is None
    # Rejected, unvalidated parameters are never recorded as parameters that were used.
    assert row["inference_parameters_json"] == "null"


def test_failure_duration_comes_from_the_actual_exception(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    error = LlamaCppCliProviderError(
        "timeout", "timed out", duration_ms=12345.0, inference_parameters={"temperature": 0.7}
    )

    run_op001(StubTelemetryProvider(error), context, repo, {"temperature": 0.7})

    (row,) = model_run_rows(repo)
    assert row["total_ms"] == 12345.0
    assert json.loads(row["inference_parameters_json"]) == {"temperature": 0.7}


@pytest.mark.parametrize(
    "outcome, category, expected_ms",
    [
        (subprocess.TimeoutExpired(["llama"], 1), "timeout", 40.0),
        (OSError("cannot start"), "process_start", 40.0),
        (RuntimeError("runner exploded"), "provider_internal", 40.0),
    ],
)
def test_real_provider_failures_record_the_measured_duration(tmp_path, outcome, category, expected_ms) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    provider = make_provider(tmp_path, ScriptedRunner(outcome))

    with with_clock(5.0, 5.04):
        run_op001(provider, context, repo, {"temperature": 0.2})

    (row,) = model_run_rows(repo)
    assert row["status"] == "failed"
    assert row["total_ms"] == pytest.approx(expected_ms)
    assert json.loads(row["inference_parameters_json"]) == {"temperature": 0.2}


def test_nonzero_exit_records_the_measured_duration(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    provider = make_provider(tmp_path, RecordingRunner(returncode=2, stderr="failed"))

    with with_clock(1.0, 1.5):
        run_op001(provider, context, repo, {"temperature": 0.2})

    (row,) = model_run_rows(repo)
    assert row["total_ms"] == 500.0


def test_provider_without_telemetry_gets_null_duration_not_operation_wall_clock(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)

    run_op001(StubTelemetryProvider('{"patterns":[]}'), context, repo, {"temperature": 0.3})
    run_op001(StubTelemetryProvider(RuntimeError("boom")), context, repo, {"temperature": 0.3})

    ok, failed = model_run_rows(repo)
    assert ok["total_ms"] is None
    assert failed["total_ms"] is None


# --- Part B / D.3: requested versus effective parameters -------------------------------------


def test_failed_invocation_records_effective_not_requested_parameters(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    provider = make_provider(
        tmp_path,
        ScriptedRunner(subprocess.TimeoutExpired(["llama"], 1)),
        default_inference_parameters={"seed": 7, "top_p": 0.9},
    )

    run_op001(provider, context, repo, {"temperature": 0.7})

    (row,) = model_run_rows(repo)
    assert json.loads(row["inference_parameters_json"]) == {"seed": 7, "temperature": 0.7, "top_p": 0.9}


def test_unresolved_parameters_are_unknown_not_empty_and_not_requested(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)

    run_op001(StubTelemetryProvider(RuntimeError("boom")), context, repo, {"temperature": 0.3})

    (row,) = model_run_rows(repo)
    assert row["inference_parameters_json"] == "null"
    assert row["inference_parameters_json"] != "{}"


def test_succeeding_provider_without_telemetry_records_the_accepted_request(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)

    run_op001(StubTelemetryProvider('{"patterns":[]}'), context, repo, {"temperature": 0.3})

    (row,) = model_run_rows(repo)
    assert json.loads(row["inference_parameters_json"]) == {"temperature": 0.3}


def test_error_carries_effective_parameters_only_after_resolution(tmp_path) -> None:
    provider = make_provider(tmp_path, RecordingRunner(returncode=3), default_inference_parameters={"seed": 1})

    with pytest.raises(LlamaCppCliProviderError) as executed:
        provider.generate("task", {}, {"type": "object"}, {"temperature": 0.2})
    with pytest.raises(LlamaCppCliProviderError) as rejected:
        provider.generate("task", {}, {"type": "object"}, {"bogus": 1})

    assert executed.value.inference_parameters == {"seed": 1, "temperature": 0.2}
    assert executed.value.duration_ms is not None
    assert rejected.value.category == "configuration"
    assert rejected.value.inference_parameters is None
    assert rejected.value.duration_ms is None


# --- Part C / D.4, D.5: attribution under interleaving, sequential regression ---------------


class InterleavingProvider(LlamaCppCliProvider):
    """Runs a second, complete invocation after the first returned but before the caller used it."""

    def generate(self, *args, **kwargs):
        first = super().generate(*args, **kwargs)
        if not getattr(self, "_interleaved", False):
            self._interleaved = True
            super().generate("intruder", {}, {"type": "object"}, {"temperature": 0.99})
        return first


def test_success_telemetry_is_attributed_to_its_own_call_under_interleaving(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    executable, model = make_files(tmp_path)
    provider = InterleavingProvider(
        executable, model, timeout_s=3, process_runner=ScriptedRunner('{"patterns":[]}', '{"patterns":[]}')
    )

    with with_clock(0.0, 0.2, 1.0, 1.01):  # call A: 200 ms, interleaved call C: 10 ms
        run_op001(provider, context, repo, {"temperature": 0.1})

    (row,) = model_run_rows(repo)
    assert row["total_ms"] == pytest.approx(200.0)
    assert json.loads(row["inference_parameters_json"]) == {"temperature": 0.1}
    # The intruding call really did overwrite the provider-wide diagnostic state.
    assert provider.last_effective_inference_parameters == {"temperature": 0.99}


def test_returned_telemetry_is_call_local_and_immutable(tmp_path) -> None:
    provider = make_provider(tmp_path, ScriptedRunner('{"a":1}', '{"b":2}'))

    with with_clock(0.0, 0.1, 1.0, 1.3):
        first = provider.generate("t", {}, {"type": "object"}, {"temperature": 0.1})
        second = provider.generate("t", {}, {"type": "object"}, {"temperature": 0.2})

    assert first == '{"a":1}' and isinstance(first, str)
    assert first.telemetry.duration_ms == pytest.approx(100.0)
    assert dict(first.telemetry.inference_parameters) == {"temperature": 0.1}
    assert second.telemetry.duration_ms == pytest.approx(300.0)
    with pytest.raises(TypeError):
        first.telemetry.inference_parameters["temperature"] = 5  # type: ignore[index]


def test_concurrent_rejection_does_not_touch_the_active_call_or_time_the_rejection(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    started, release = threading.Event(), threading.Event()

    def blocking_runner(argv, **kwargs):
        started.set()
        assert release.wait(5)
        return subprocess.CompletedProcess(argv, 0, stdout='{"patterns":[]}', stderr="")

    provider = make_provider(tmp_path, blocking_runner)
    results: list[Any] = []
    worker = threading.Thread(
        target=lambda: results.append(provider.generate("t", {}, {"type": "object"}, {"temperature": 0.1}))
    )
    worker.start()
    assert started.wait(5)
    try:
        result = run_op001(provider, context, repo, {"temperature": 0.5})
    finally:
        release.set()
        worker.join(5)

    (row,) = model_run_rows(repo)
    assert result.run.status == "failed"
    assert "active inference" in row["error"]
    assert row["total_ms"] is None
    assert row["inference_parameters_json"] == "null"
    assert dict(results[0].telemetry.inference_parameters) == {"temperature": 0.1}


def test_sequential_invocations_each_record_their_own_telemetry(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = persist_context(repo)
    provider = make_provider(
        tmp_path,
        ScriptedRunner('{"patterns":[]}', subprocess.TimeoutExpired(["llama"], 1), '{"patterns":[]}'),
        default_inference_parameters={"seed": 7},
    )

    with with_clock(0.0, 0.1, 1.0, 1.02, 2.0, 2.3):
        run_op001(provider, context, repo, {"temperature": 0.1})
        run_op001(provider, context, repo, {"temperature": 0.5})
        run_op001(provider, context, repo, {"temperature": 0.9})

    rows = model_run_rows(repo)
    assert [r["status"] for r in rows] == ["succeeded", "failed", "succeeded"]
    assert [r["total_ms"] for r in rows] == [pytest.approx(100.0), pytest.approx(20.0), pytest.approx(300.0)]
    assert [json.loads(r["inference_parameters_json"]) for r in rows] == [
        {"seed": 7, "temperature": 0.1},
        {"seed": 7, "temperature": 0.5},
        {"seed": 7, "temperature": 0.9},
    ]


def test_provider_diagnostic_state_is_still_reset_at_start_of_every_call(tmp_path) -> None:
    provider = make_provider(tmp_path, ScriptedRunner('{"patterns":[]}'))
    provider.generate("task", {}, {"type": "object"}, {"temperature": 0.3})
    assert provider.last_invocation is not None

    with pytest.raises(LlamaCppCliProviderError):
        provider.generate("task", {}, {}, {"temperature": 0.4})

    assert provider.last_invocation is None
    assert provider.last_effective_inference_parameters is None
