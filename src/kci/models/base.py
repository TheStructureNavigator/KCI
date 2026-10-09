from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


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
