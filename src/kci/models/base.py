from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from kci.error_hygiene import ConfigurationIssueError, trusted_message_type


@trusted_message_type
class InferenceParametersError(ConfigurationIssueError):
    """Inference parameters were rejected. Built only from (field, ConfigurationReason) pairs."""

    label = "invalid inference parameters"


class InferenceParameters(BaseModel):
    """Backend-neutral generation parameters an operation may request.

    Resource and runtime settings (threads, GPU layers, context size) are provider-owned
    infrastructure and are deliberately absent. Engine defaults are never invented: an
    unset parameter stays unset.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    temperature: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    top_p: float | None = Field(default=None, gt=0, le=1, allow_inf_nan=False)
    max_output_tokens: int | None = Field(default=None, ge=1)
    seed: int | None = Field(default=None, ge=0)


@dataclass(frozen=True)
class InvocationTelemetry:
    """Immutable telemetry of exactly one provider invocation."""

    duration_ms: float
    inference_parameters: Mapping[str, Any]


class GenerationText(str):
    """Raw generated text that carries the telemetry of the call that produced it.

    It is a plain ``str`` for every consumer, so the ``ModelProvider.generate`` contract is
    unchanged. Attaching telemetry to the returned value (instead of provider-wide ``last_*``
    state) keeps attribution correct when invocations interleave.
    """

    def __new__(cls, text: str, telemetry: InvocationTelemetry) -> "GenerationText":
        instance = super().__new__(cls, text)
        instance._telemetry = telemetry
        return instance

    @property
    def telemetry(self) -> InvocationTelemetry:
        return self._telemetry


class ModelProvider(ABC):
    provider_name: str

    @abstractmethod
    def generate(
        self,
        task: str,
        context: dict[str, Any],
        output_schema: dict[str, Any],
        inference_parameters: dict[str, Any] | None = None,
    ) -> str:
        raise NotImplementedError
