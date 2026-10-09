from __future__ import annotations

import hashlib
import json
import subprocess
import threading
from types import MappingProxyType
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, Protocol

from pydantic import ValidationError

from kci.error_hygiene import safe_key_names, trusted_message_type
from kci.models.base import GenerationText, InferenceParameters, InvocationTelemetry, ModelProvider


LlamaCppFailureCategory = Literal[
    "configuration",
    "process_start",
    "timeout",
    "process_execution",
    "provider_internal",
]


@trusted_message_type
class LlamaCppCliProviderError(RuntimeError):
    # Registered for persistence by exact type. Every raise site in this module uses fixed text
    # plus sanitized parameter names (no paths, values or OS error text); keep it that way.
    def __init__(
        self,
        category: LlamaCppFailureCategory,
        message: str,
        *,
        exit_code: int | None = None,
        duration_ms: float | None = None,
        stderr_excerpt: str | None = None,
        inference_parameters: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.exit_code = exit_code
        self.duration_ms = duration_ms
        self.stderr_excerpt = stderr_excerpt
        # Effective parameters of the failing invocation; None if they were never resolved.
        self.inference_parameters = inference_parameters


@dataclass(frozen=True)
class LlamaCppCliInvocation:
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: float

    @property
    def provider_duration_ms(self) -> float:
        return self.duration_ms


class _ProcessRunner(Protocol):
    def __call__(
        self,
        argv: list[str],
        *,
        text: bool,
        encoding: str,
        capture_output: bool,
        shell: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        ...


class LlamaCppCliProvider(ModelProvider):
    provider_name = "llama_cpp_cli"
    runtime_version = "unknown"
    # Generation parameters an operation may request per call.
    per_call_inference_parameters = frozenset({"temperature", "top_p", "max_output_tokens", "seed"})
    # Provider-owned infrastructure settings: configured at construction only, never per call.
    provider_owned_parameters = frozenset({"threads", "ctx_size", "gpu_layers"})
    supported_inference_parameters = per_call_inference_parameters | provider_owned_parameters

    def __init__(
        self,
        executable: str | Path,
        model_path: str | Path,
        *,
        timeout_s: float,
        default_inference_parameters: dict[str, Any] | None = None,
        process_runner: _ProcessRunner = subprocess.run,
    ) -> None:
        self.executable = Path(executable)
        self.model_path = Path(model_path)
        self.timeout_s = timeout_s
        self.default_inference_parameters = dict(default_inference_parameters or {})
        self._process_runner = process_runner
        self._active_lock = threading.Lock()
        self._last_invocation: LlamaCppCliInvocation | None = None
        self.last_effective_inference_parameters: dict[str, Any] | None = None
        self._validate_static_configuration()
        self.model_artifact_hash = self._compute_sha256(self.model_path)
        self.model_name = self.model_path.name
        self.quantization = None

    @property
    def last_invocation(self) -> LlamaCppCliInvocation | None:
        return self._last_invocation

    def generate(
        self,
        task: str,
        context: dict[str, Any],
        output_schema: dict[str, Any],
        inference_parameters: dict[str, Any] | None = None,
    ) -> str:
        if not self._active_lock.acquire(blocking=False):
            raise LlamaCppCliProviderError("provider_internal", "provider already has an active inference")
        try:
            # Per-invocation telemetry must never be inherited from an earlier call.
            self._last_invocation = None
            self.last_effective_inference_parameters = None
            self._validate_output_schema(output_schema)
            effective_parameters = self._effective_inference_parameters(inference_parameters)
            self.last_effective_inference_parameters = effective_parameters
            request = self._request_payload(task, context)
            argv = self._argv(output_schema, effective_parameters, request)
            started = perf_counter()
            try:
                completed = self._process_runner(
                    argv,
                    text=True,
                    encoding="utf-8",
                    capture_output=True,
                    shell=False,
                    timeout=self.timeout_s,
                )
            except subprocess.TimeoutExpired as exc:
                duration_ms = (perf_counter() - started) * 1000
                raise LlamaCppCliProviderError(
                    "timeout",
                    "llama.cpp CLI invocation timed out",
                    duration_ms=duration_ms,
                    stderr_excerpt=_bounded_text(_to_text(exc.stderr)),
                    inference_parameters=effective_parameters,
                ) from exc
            except OSError as exc:
                duration_ms = (perf_counter() - started) * 1000
                raise LlamaCppCliProviderError(
                    "process_start",
                    "could not start llama.cpp CLI process",
                    duration_ms=duration_ms,
                    inference_parameters=effective_parameters,
                ) from exc
            except Exception as exc:
                duration_ms = (perf_counter() - started) * 1000
                raise LlamaCppCliProviderError(
                    "provider_internal",
                    "provider process runner failed",
                    duration_ms=duration_ms,
                    inference_parameters=effective_parameters,
                ) from exc

            duration_ms = (perf_counter() - started) * 1000
            invocation = LlamaCppCliInvocation(
                stdout=completed.stdout or "",
                stderr=completed.stderr or "",
                exit_code=completed.returncode,
                duration_ms=duration_ms,
            )
            self._last_invocation = invocation
            if completed.returncode != 0:
                raise LlamaCppCliProviderError(
                    "process_execution",
                    "llama.cpp CLI process exited with non-zero status",
                    exit_code=completed.returncode,
                    duration_ms=duration_ms,
                    stderr_excerpt=_bounded_text(completed.stderr),
                    inference_parameters=effective_parameters,
                )
            return GenerationText(
                _decode_llama_completion_framing(completed.stdout or ""),
                InvocationTelemetry(
                    duration_ms=duration_ms,
                    inference_parameters=MappingProxyType(dict(effective_parameters)),
                ),
            )
        finally:
            self._active_lock.release()

    def _validate_static_configuration(self) -> None:
        if self.timeout_s <= 0:
            raise LlamaCppCliProviderError("configuration", "timeout_s must be greater than zero")
        if not self.executable.exists() or not self.executable.is_file():
            raise LlamaCppCliProviderError("configuration", "llama.cpp executable does not exist")
        if not self.model_path.exists() or not self.model_path.is_file():
            raise LlamaCppCliProviderError("configuration", "GGUF model file does not exist")
        self._reject_unsupported_or_invalid(self.default_inference_parameters)

    def _validate_output_schema(self, output_schema: dict[str, Any]) -> None:
        if not output_schema:
            raise LlamaCppCliProviderError("configuration", "structured output schema is required")
        if not isinstance(output_schema, dict):
            raise LlamaCppCliProviderError("configuration", "structured output schema must be a JSON object")

    def _effective_inference_parameters(self, inference_parameters: dict[str, Any] | None) -> dict[str, Any]:
        requested = dict(inference_parameters or {})
        owned = sorted(set(requested) & self.provider_owned_parameters)
        if owned:
            raise LlamaCppCliProviderError(
                "configuration", f"provider-owned setting(s) cannot be set per call: {safe_key_names(owned)}"
            )
        effective = {**self.default_inference_parameters, **requested}
        self._reject_unsupported_or_invalid(effective)
        return json.loads(json.dumps(effective, separators=(",", ":"), sort_keys=True))

    def _reject_unsupported_or_invalid(self, parameters: dict[str, Any]) -> None:
        unsupported = set(parameters) - self.supported_inference_parameters
        if unsupported:
            raise LlamaCppCliProviderError(
                "configuration", f"unsupported inference parameter(s): {safe_key_names(unsupported)}"
            )
        invalid = _invalid_parameter_names(parameters)
        if invalid:
            raise LlamaCppCliProviderError(
                "configuration", f"invalid inference parameter value(s): {safe_key_names(invalid)}"
            )

    def _argv(self, output_schema: dict[str, Any], inference_parameters: dict[str, Any], request: str) -> list[str]:
        argv = [
            str(self.executable),
            "-m",
            str(self.model_path),
            "--offline",
            "--no-conversation",
            "--no-display-prompt",
            "--json-schema",
            json.dumps(output_schema, separators=(",", ":"), sort_keys=True),
            "--prompt",
            request,
        ]
        mapping = {
            "ctx_size": "--ctx-size",
            "gpu_layers": "--gpu-layers",
            "max_output_tokens": "--predict",
            "seed": "--seed",
            "temperature": "--temp",
            "threads": "--threads",
            "top_p": "--top-p",
        }
        for key in sorted(inference_parameters):
            argv.extend([mapping[key], str(inference_parameters[key])])
        return argv

    def _request_payload(self, task: str, context: dict[str, Any]) -> str:
        return json.dumps(
            {"task": task, "context": context},
            separators=(",", ":"),
            sort_keys=True,
            ensure_ascii=False,
        )

    def _compute_sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


class LlamaCppProvider(LlamaCppCliProvider):
    pass


_LLAMA_COMPLETION_TERMINAL_SENTINEL = " [end of text]"


def _decode_llama_completion_framing(stdout: str) -> str:
    terminal_index = len(stdout)
    while terminal_index > 0 and stdout[terminal_index - 1] in "\r\n":
        terminal_index -= 1
    if stdout[:terminal_index].endswith(_LLAMA_COMPLETION_TERMINAL_SENTINEL):
        return stdout[: terminal_index - len(_LLAMA_COMPLETION_TERMINAL_SENTINEL)]
    return stdout


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _invalid_parameter_names(parameters: dict[str, Any]) -> list[str]:
    """Names of parameters whose value is not a usable type or range (values are never reported)."""
    invalid: list[str] = []
    neutral = {key: parameters[key] for key in LlamaCppCliProvider.per_call_inference_parameters if key in parameters}
    try:
        InferenceParameters.model_validate(neutral)
    except ValidationError as exc:
        invalid.extend(str(error["loc"][0]) for error in exc.errors() if error["loc"])
    for key in ("threads", "ctx_size"):
        if key in parameters and not (_is_int(parameters[key]) and parameters[key] >= 1):
            invalid.append(key)
    if "gpu_layers" in parameters:
        value = parameters["gpu_layers"]
        if not ((_is_int(value) and value >= 0) or value == "all"):
            invalid.append("gpu_layers")
    return sorted(set(invalid))


def _bounded_text(value: str | None, limit: int = 1000) -> str | None:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[:limit]


def _to_text(value: str | bytes | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
