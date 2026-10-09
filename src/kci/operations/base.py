from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from kci.contracts import InsightCandidate, IntelligenceContext
from kci.error_hygiene import ConfigurationIssueError, issues_from_validation_error, trusted_message_type


@trusted_message_type
class OperationConfigurationError(ConfigurationIssueError):
    """Analytical configuration was rejected. Built only from (field, ConfigurationReason) pairs."""

    label = "invalid operation configuration"


class OperationConfiguration(BaseModel):
    """Base for an operation's typed analytical configuration.

    Analytical parameters only (Contract 007.2). Inference parameters and provider
    infrastructure settings are not analytical configuration and are rejected as unknown keys.
    The base model declares no parameters, so any supplied key is rejected.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class IntelligenceOperation(ABC):
    operation_id: str
    operation_version: str
    deterministic: bool = False
    configuration_model: type[OperationConfiguration] = OperationConfiguration

    def effective_configuration(self, requested_configuration: dict[str, Any] | None = None) -> dict[str, Any]:
        requested = {} if requested_configuration is None else requested_configuration
        try:
            return self.configuration_model.model_validate(requested).model_dump(mode="json")
        except ValidationError as exc:
            raise OperationConfigurationError(issues_from_validation_error(exc)) from None

    @abstractmethod
    def synthesize(
        self,
        context: IntelligenceContext,
        configuration: dict[str, Any],
    ) -> list[InsightCandidate]:
        raise NotImplementedError
