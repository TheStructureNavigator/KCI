from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from kci.contracts import DatasetRequirement, FindingCandidate, ObservationContext


class Observer(ABC):
    id: str
    version: str
    required_datasets: tuple[DatasetRequirement, ...]
    deterministic: bool = False

    def effective_configuration(self, requested_configuration: dict[str, Any] | None = None) -> dict[str, Any]:
        if requested_configuration:
            raise ValueError(f"unsupported observer configuration key(s): {', '.join(sorted(requested_configuration))}")
        return {}

    def apply_configuration(self, effective_configuration: dict[str, Any]) -> None:
        if effective_configuration:
            raise ValueError("observer does not accept analytical configuration")

    @abstractmethod
    def observe(self, context: ObservationContext) -> list[FindingCandidate]:
        raise NotImplementedError
