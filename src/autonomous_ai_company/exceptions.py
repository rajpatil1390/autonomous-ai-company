"""Define provider-neutral failures exposed by application boundaries.

Stable exception types let orchestration classify failures without importing
SDKs, validation frameworks, storage drivers, or domain implementation details.
Every boundary translation retains the original exception as ``__cause__`` so
debuggers and logs preserve the complete traceback.
"""


class ApplicationError(Exception):
    """Base class for expected failures crossing application boundaries."""


class ConfigurationError(ApplicationError):
    """Signal missing or invalid runtime configuration."""


class InvalidDatasetError(ApplicationError):
    """Signal that supplied business data violates its domain contract."""


class UndefinedMetricError(ApplicationError):
    """Signal that valid data cannot produce a mathematically defined metric."""


class AgentOutputValidationError(ApplicationError):
    """Signal that an agent exhausted its structured-output correction policy."""


class LLMError(ApplicationError):
    """Base class for provider-neutral LLM request failures."""


class LLMTimeoutError(LLMError):
    """Signal that an LLM request exceeded its allowed duration."""


class LLMRateLimitError(LLMError):
    """Signal that an LLM provider temporarily rejected request volume."""


class LLMUnavailableError(LLMError):
    """Signal that an LLM service or transport is temporarily unavailable."""


class AuditError(ApplicationError):
    """Signal that an audit event could not be validated, stored, or read."""
