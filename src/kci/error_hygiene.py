"""Rules for what may be persisted as error text (IntelligenceRun.error, ModelRun.error).

Persisted error text must never carry credentials, tokens, passwords, model output, or
deployment details such as absolute paths. Trust is NOT inherited and NOT a class marker:

* ``safe_error_message`` persists ``str(exc)`` only when ``type(exc)`` is *exactly* one of the
  explicitly registered exception types. Subclasses of a registered type are not trusted, so a
  custom subclass cannot gain persistence by inheritance.
* The public extension points (``ConfigurationIssueError`` subclasses and
  ``IntelligencePreconditionFailed``) have closed constructors: their messages are built from
  sanitized field names and a controlled reason code, never from caller-supplied text.
* Everything else is reduced to its exception type name.

Registering a type is a deliberate security decision: every raise site of that exact type must
use fixed text or sanitized names. The registered set is pinned by a test.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import StrEnum
from typing import TypeVar

from pydantic import ValidationError

_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_LIMIT = 10
_MAX_PERSISTED_LENGTH = 1000

_TRUSTED_TYPES: set[type] = set()
_T = TypeVar("_T", bound=type)


def trusted_message_type(cls: _T) -> _T:
    """Register exactly ``cls`` (not its subclasses) as having non-sensitive messages by construction."""
    _TRUSTED_TYPES.add(cls)
    return cls


def trusted_error_types() -> frozenset[type]:
    return frozenset(_TRUSTED_TYPES)


def safe_name(value: object) -> str:
    text = str(value)
    return text if _SAFE_NAME.match(text) else "<invalid-name>"


def safe_key_names(keys: Iterable[object]) -> str:
    names = sorted(safe_name(key) for key in keys)
    shown = names[:_LIMIT]
    if len(names) > _LIMIT:
        shown.append(f"(+{len(names) - _LIMIT} more)")
    return ", ".join(shown)


def describe_validation_errors(exc: ValidationError) -> str:
    """Field names and pydantic error types only; never the offending input values."""
    parts = []
    for error in exc.errors()[:_LIMIT]:
        location = ".".join(safe_name(item) for item in error["loc"]) or "<root>"
        parts.append(f"{location}:{error['type']}")
    return ", ".join(parts)


class ConfigurationReason(StrEnum):
    """Closed set of reasons a configuration can be rejected."""

    UNKNOWN_FIELD = "unknown_field"
    MISSING_FIELD = "missing_field"
    INVALID_TYPE = "invalid_type"
    INVALID_VALUE = "invalid_value"


ConfigurationIssue = tuple[str, ConfigurationReason]


def _reason_for(error_type: str) -> ConfigurationReason:
    if error_type == "extra_forbidden":
        return ConfigurationReason.UNKNOWN_FIELD
    if error_type == "missing":
        return ConfigurationReason.MISSING_FIELD
    if "type" in error_type or "parsing" in error_type:
        return ConfigurationReason.INVALID_TYPE
    return ConfigurationReason.INVALID_VALUE


def issues_from_validation_error(exc: ValidationError) -> tuple[ConfigurationIssue, ...]:
    issues: list[ConfigurationIssue] = []
    for error in exc.errors():
        location = ".".join(safe_name(item) for item in error["loc"]) or "<root>"
        issues.append((location, _reason_for(error["type"])))
    return tuple(issues)


class ConfigurationIssueError(ValueError):
    """Base for configuration rejections. The constructor accepts only (field, reason) pairs.

    Free-form text is impossible by construction: ``ConfigurationIssueError("secret")`` raises
    ``TypeError``. Subclasses must be registered with ``trusted_message_type`` to be persisted.
    """

    label = "invalid configuration"

    def __init__(self, issues: Iterable[ConfigurationIssue]) -> None:
        if isinstance(issues, (str, bytes)):
            raise TypeError("issues must be (field, ConfigurationReason) pairs")
        pairs = tuple(issues)
        for pair in pairs:
            if not (isinstance(pair, tuple) and len(pair) == 2 and isinstance(pair[1], ConfigurationReason)):
                raise TypeError("issues must be (field, ConfigurationReason) pairs")
        self.issues: tuple[ConfigurationIssue, ...] = tuple((safe_name(field), reason) for field, reason in pairs)
        shown = ", ".join(f"{field}:{reason.value}" for field, reason in self.issues[:_LIMIT])
        if len(self.issues) > _LIMIT:
            shown += f", (+{len(self.issues) - _LIMIT} more)"
        super().__init__(f"{self.label}: {shown}")


def safe_error_message(exc: BaseException) -> str:
    if type(exc) in _TRUSTED_TYPES:
        return str(exc)[:_MAX_PERSISTED_LENGTH]
    return f"{type(exc).__name__}: message withheld"
