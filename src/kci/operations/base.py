from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from kci.contracts import InsightCandidate, IntelligenceContext


class IntelligenceOperation(ABC):
    operation_id: str
    operation_version: str
    deterministic: bool = False

    def effective_configuration(self, requested_configuration: dict[str, Any] | None = None) -> dict[str, Any]:
        if requested_configuration:
            raise ValueError(f"unsupported operation configuration key(s): {', '.join(sorted(requested_configuration))}")
        return {}

    @abstractmethod
    def synthesize(
        self,
        context: IntelligenceContext,
        configuration: dict[str, Any],
    ) -> list[InsightCandidate]:
        raise NotImplementedError
