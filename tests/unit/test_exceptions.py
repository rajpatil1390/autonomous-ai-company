"""Unit tests for the provider-neutral application exception hierarchy."""

import pytest

from autonomous_ai_company.exceptions import (
    AgentOutputValidationError,
    ApplicationError,
    AuditError,
    ConfigurationError,
    InvalidDatasetError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    UndefinedMetricError,
)


@pytest.mark.parametrize(
    "exception_type",
    (
        ConfigurationError,
        InvalidDatasetError,
        UndefinedMetricError,
        AgentOutputValidationError,
        LLMError,
        LLMTimeoutError,
        LLMRateLimitError,
        LLMUnavailableError,
        AuditError,
    ),
)
def test_every_application_exception_has_one_stable_root(
    exception_type: type[ApplicationError],
) -> None:
    """Orchestration should catch all expected failures through one base."""

    assert issubclass(exception_type, ApplicationError)


@pytest.mark.parametrize(
    "exception_type",
    (LLMTimeoutError, LLMRateLimitError, LLMUnavailableError),
)
def test_specialized_llm_exceptions_share_the_llm_boundary(
    exception_type: type[LLMError],
) -> None:
    """Graph retry policy should classify every transient LLM failure alike."""

    assert issubclass(exception_type, LLMError)
