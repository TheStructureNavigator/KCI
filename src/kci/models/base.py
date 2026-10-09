from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


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
