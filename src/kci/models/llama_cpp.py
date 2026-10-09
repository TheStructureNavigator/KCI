from __future__ import annotations

import hashlib
import json
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, Protocol

from kci.models.base import ModelProvider


LlamaCppFailureCategory = Literal[
    "configuration",
    "process_start",
    "timeout",
    "process_execution",
    "provider_internal",
]


class LlamaCppCliProviderError(RuntimeError):
    def __init__(
        self,
        category: LlamaCppFailureCategory,
        message: str,
        *,
        exit_code: int | None = None,
        duration_ms: float | None = None,
        stderr_excerpt: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.exit_code = exit_code
        self.duration_ms = duration_ms
        self.stderr_excerpt = stderr_excerpt


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
    supported_inference_parameters = {
        "temperature",
        "top_p",
        "max_output_tokens",
        "seed",
        "threads",
        "ctx_size",
        "gpu_layers",
    }

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
        self.last_effective_inference_parameters: dict[str, Any] = {}
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
                ) from exc
            except OSError as exc:
                duration_ms = (perf_counter() - started) * 1000
                raise LlamaCppCliProviderError(
                    "process_start",
                    f"could not start llama.cpp CLI process: {exc}",
                    duration_ms=duration_ms,
                ) from exc
            except Exception as exc:
                duration_ms = (perf_counter() - started) * 1000
                raise LlamaCppCliProviderError(
                    "provider_internal",
                    f"provider process runner failed: {exc}",
                    duration_ms=duration_ms,
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
                )
            return _decode_llama_completion_framing(completed.stdout or "")
        finally:
            self._active_lock.release()

    def _validate_static_configuration(self) -> None:
        if self.timeout_s <= 0:
            raise LlamaCppCliProviderError("configuration", "timeout_s must be greater than zero")
        if not self.executable.exists() or not self.executable.is_file():
            raise LlamaCppCliProviderError("configuration", f"llama.cpp executable does not exist: {self.executable}")
        if not self.model_path.exists() or not self.model_path.is_file():
            raise LlamaCppCliProviderError("configuration", f"GGUF model file does not exist: {self.model_path}")
        unsupported = sorted(set(self.default_inference_parameters) - self.supported_inference_parameters)
        if unsupported:
            raise LlamaCppCliProviderError("configuration", f"unsupported inference parameter(s): {', '.join(unsupported)}")

    def _validate_output_schema(self, output_schema: dict[str, Any]) -> None:
        if not output_schema:
            raise LlamaCppCliProviderError("configuration", "structured output schema is required")
        if not isinstance(output_schema, dict):
            raise LlamaCppCliProviderError("configuration", "structured output schema must be a JSON object")

    def _effective_inference_parameters(self, inference_parameters: dict[str, Any] | None) -> dict[str, Any]:
        effective = dict(self.default_inference_parameters)
        if inference_parameters:
            effective.update(inference_parameters)
        unsupported = sorted(set(effective) - self.supported_inference_parameters)
        if unsupported:
            raise LlamaCppCliProviderError("configuration", f"unsupported inference parameter(s): {', '.join(unsupported)}")
        return json.loads(json.dumps(effective, separators=(",", ":"), sort_keys=True))

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
