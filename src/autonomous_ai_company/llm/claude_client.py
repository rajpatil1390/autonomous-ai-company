"""Provide the provider-specific boundary for Anthropic message generation.

Keeping SDK details in this thin adapter prevents the rest of the application
from depending directly on Anthropic request and response structures.
"""

import logging
from time import perf_counter

from anthropic import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
    RateLimitError,
)
from anthropic.types import MessageParam, TextBlock

from autonomous_ai_company.config import Settings, get_settings
from autonomous_ai_company.exceptions import (
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from autonomous_ai_company.llm.generation_result import GenerationResult


logger = logging.getLogger(__name__)
ANTHROPIC_PROVIDER_NAME = "anthropic"


def _optional_string(value: object) -> str | None:
    """Return provider telemetry only when it is a meaningful string."""

    return value if isinstance(value, str) and value else None


def _optional_token_count(value: object) -> int | None:
    """Return a valid SDK token count without coercing unknown values."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _translate_sdk_error(error: APIError) -> LLMError:
    """Map Anthropic failures to stable application exception categories."""

    if isinstance(error, APITimeoutError):
        return LLMTimeoutError("LLM request timed out")
    if isinstance(error, RateLimitError):
        return LLMRateLimitError("LLM request was rate limited")
    if isinstance(error, APIConnectionError):
        return LLMUnavailableError("LLM service is unavailable")
    if isinstance(error, APIStatusError) and error.status_code >= 500:
        return LLMUnavailableError("LLM service is unavailable")
    return LLMError("LLM request failed")


class ClaudeClient:
    """Translate application prompts into one Anthropic SDK request.

    The wrapper owns provider-specific transport details but deliberately owns
    no retry policy, prompt construction, schema validation, or business logic.
    Those decisions belong to the agent that understands the use case. One
    async SDK client is reusable across concurrent calls; every request keeps
    its mutable state in coroutine-local variables. Awaiting the SDK directly
    preserves task cancellation and configured timeout behavior.
    """

    def __init__(
        self,
        timeout_seconds: float | None = None,
        *,
        settings: Settings | None = None,
    ) -> None:
        """Initialize the SDK from centralized configuration.

        An optional timeout supports different execution environments without
        introducing another source of secrets or model configuration. Automatic
        SDK retries are disabled so the calling agent retains retry ownership.

        Args:
            timeout_seconds: Optional positive request timeout in seconds. When
                omitted, the official SDK's configured default is used.
            settings: Optional injected configuration. The composition root
                supplies this so every dependency shares one validated instance;
                direct callers retain centralized loading as the default.

        Raises:
            ValueError: If ``timeout_seconds`` is not positive.
        """

        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

        resolved_settings = settings if settings is not None else get_settings()
        self._settings = resolved_settings
        self._model_name = resolved_settings.model_name
        self._max_tokens = resolved_settings.max_tokens
        self._temperature = resolved_settings.temperature

        client_arguments = {
            "api_key": resolved_settings.anthropic_api_key.get_secret_value(),
            "max_retries": 0,
        }
        if timeout_seconds is not None:
            client_arguments["timeout"] = timeout_seconds

        self._client = AsyncAnthropic(**client_arguments)
        logger.debug(
            "Initialized Claude client",
            extra={"model_name": self._model_name},
        )

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> GenerationResult:
        """Asynchronously generate one result using one cancellable SDK request.

        Defaults come from centralized settings, while explicit overrides let
        an agent constrain a particular call without changing process-wide
        configuration. Failures are logged without prompt contents or secrets
        and then re-raised unchanged for the agent to handle.

        Args:
            prompt: Non-empty user prompt sent to Claude.
            system_prompt: Optional non-empty provider system instruction.
            max_tokens: Optional positive per-request output-token limit.
            temperature: Optional per-request sampling value from zero to one.

        Returns:
            Generated text and available telemetry without SDK response objects.

        Raises:
            ValueError: If a prompt or override is invalid.
            RuntimeError: If Anthropic returns no generated text.
            Exception: Re-raises SDK exceptions unchanged after logging them.
        """

        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        if system_prompt is not None and (
            not isinstance(system_prompt, str) or not system_prompt.strip()
        ):
            raise ValueError("system_prompt must be a non-empty string when set")
        if max_tokens is not None and (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or max_tokens <= 0
        ):
            raise ValueError("max_tokens must be a positive integer when set")
        if temperature is not None and (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not 0.0 <= temperature <= 1.0
        ):
            raise ValueError("temperature must be between zero and one when set")

        resolved_max_tokens = max_tokens if max_tokens is not None else self._max_tokens
        resolved_temperature = (
            float(temperature) if temperature is not None else self._temperature
        )
        messages: list[MessageParam] = [
            {"role": "user", "content": prompt},
        ]

        logger.debug(
            "Sending Claude generation request",
            extra={
                "model_name": self._model_name,
                "max_tokens": resolved_max_tokens,
                "temperature": resolved_temperature,
                "has_system_prompt": system_prompt is not None,
            },
        )

        request_started = perf_counter()
        try:
            if system_prompt is None:
                response = await self._client.messages.create(
                    model=self._model_name,
                    max_tokens=resolved_max_tokens,
                    temperature=resolved_temperature,
                    messages=messages,
                )
            else:
                response = await self._client.messages.create(
                    model=self._model_name,
                    max_tokens=resolved_max_tokens,
                    temperature=resolved_temperature,
                    messages=messages,
                    system=system_prompt,
                )
        except APIError as error:
            logger.exception(
                "Claude generation request failed",
                extra={"model_name": self._model_name},
            )
            raise _translate_sdk_error(error) from error
        except Exception:
            logger.exception(
                "Claude generation request failed",
                extra={"model_name": self._model_name},
            )
            raise
        latency_ms = (perf_counter() - request_started) * 1000.0

        generated_text = "".join(
            block.text for block in response.content if isinstance(block, TextBlock)
        )
        if not generated_text:
            logger.error(
                "Claude response contained no text",
                extra={"model_name": self._model_name},
            )
            cause = RuntimeError("Anthropic response did not contain generated text")
            raise LLMUnavailableError(str(cause)) from cause

        logger.debug(
            "Claude generation request completed",
            extra={"model_name": self._model_name},
        )
        usage = getattr(response, "usage", None)
        input_tokens = _optional_token_count(getattr(usage, "input_tokens", None))
        output_tokens = _optional_token_count(getattr(usage, "output_tokens", None))
        total_tokens = (
            input_tokens + output_tokens
            if input_tokens is not None and output_tokens is not None
            else None
        )
        return GenerationResult(
            text=generated_text,
            model_name=_optional_string(getattr(response, "model", None)),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            request_id=_optional_string(getattr(response, "id", None)),
            stop_reason=_optional_string(getattr(response, "stop_reason", None)),
            provider=ANTHROPIC_PROVIDER_NAME,
        )
