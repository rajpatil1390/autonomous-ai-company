"""Adapt OpenAI-compatible chat APIs to the provider-neutral LLM contract.

The shared adapter owns SDK request/response details once so OpenAI and xAI can
reuse the same tested transport behavior without leaking compatibility choices
into agents, graphs, or business logic.
"""

import logging
from time import perf_counter

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)
from openai.types.chat import ChatCompletionMessageParam

from autonomous_ai_company.config import Settings, get_settings
from autonomous_ai_company.exceptions import (
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from autonomous_ai_company.llm.generation_result import GenerationResult


logger = logging.getLogger(__name__)
OPENAI_PROVIDER_NAME = "openai"


def _optional_string(value: object) -> str | None:
    """Keep meaningful provider strings and discard unavailable telemetry."""

    return value if isinstance(value, str) and value else None


def _optional_token_count(value: object) -> int | None:
    """Keep non-negative integer token counts without inventing conversions."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _translate_sdk_error(error: APIError) -> LLMError:
    """Translate OpenAI-compatible SDK errors into stable application errors."""

    if isinstance(error, APITimeoutError):
        return LLMTimeoutError("LLM request timed out")
    if isinstance(error, RateLimitError):
        return LLMRateLimitError("LLM request was rate limited")
    if isinstance(error, APIConnectionError):
        return LLMUnavailableError("LLM service is unavailable")
    if isinstance(error, APIStatusError) and error.status_code >= 500:
        return LLMUnavailableError("LLM service is unavailable")
    return LLMError("LLM request failed")


class OpenAICompatibleClient:
    """Implement one reusable async adapter for OpenAI-compatible endpoints.

    Request state stays coroutine-local, so a single instance can serve
    concurrent agents. Awaiting the official async SDK directly preserves task
    cancellation. ``max_retries`` configures transport retries independently
    from the agents' one schema-correction retry.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        provider_name: str,
        max_tokens: int,
        temperature: float,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int = 0,
    ) -> None:
        """Build the SDK client from already validated deployment settings."""

        if not api_key:
            raise ValueError("api_key must be non-empty")
        if not model_name:
            raise ValueError("model_name must be non-empty")
        if not provider_name:
            raise ValueError("provider_name must be non-empty")
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if isinstance(max_retries, bool) or max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")

        self._model_name = model_name
        self._provider_name = provider_name
        self._max_tokens = max_tokens
        self._temperature = temperature
        client_arguments: dict[str, object] = {
            "api_key": api_key,
            "max_retries": max_retries,
        }
        if base_url is not None:
            client_arguments["base_url"] = base_url
        if timeout_seconds is not None:
            client_arguments["timeout"] = timeout_seconds
        self._client = AsyncOpenAI(**client_arguments)

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> GenerationResult:
        """Generate text and reduce SDK telemetry to ``GenerationResult``."""

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

        messages: list[ChatCompletionMessageParam] = []
        if system_prompt is not None:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        request_started = perf_counter()
        try:
            response = await self._client.chat.completions.create(
                model=self._model_name,
                messages=messages,
                max_tokens=max_tokens if max_tokens is not None else self._max_tokens,
                temperature=(
                    float(temperature) if temperature is not None else self._temperature
                ),
            )
        except APIError as error:
            logger.exception(
                "OpenAI-compatible generation request failed",
                extra={
                    "provider": self._provider_name,
                    "model_name": self._model_name,
                },
            )
            raise _translate_sdk_error(error) from error
        except Exception:
            logger.exception(
                "OpenAI-compatible generation request failed",
                extra={
                    "provider": self._provider_name,
                    "model_name": self._model_name,
                },
            )
            raise
        latency_ms = (perf_counter() - request_started) * 1000.0

        generated_text = (
            response.choices[0].message.content if response.choices else None
        )
        if not isinstance(generated_text, str) or not generated_text:
            cause = RuntimeError("Provider response did not contain generated text")
            raise LLMUnavailableError(str(cause)) from cause

        usage = getattr(response, "usage", None)
        input_tokens = _optional_token_count(getattr(usage, "prompt_tokens", None))
        output_tokens = _optional_token_count(getattr(usage, "completion_tokens", None))
        reported_total = _optional_token_count(getattr(usage, "total_tokens", None))
        total_tokens = (
            reported_total
            if reported_total is not None
            else (
                input_tokens + output_tokens
                if input_tokens is not None and output_tokens is not None
                else None
            )
        )
        fingerprint = _optional_string(getattr(response, "system_fingerprint", None))
        metadata = (
            {"system_fingerprint": fingerprint} if fingerprint is not None else None
        )
        stop_reason = (
            _optional_string(response.choices[0].finish_reason)
            if response.choices
            else None
        )
        request_id = _optional_string(getattr(response, "_request_id", None))
        if request_id is None:
            request_id = _optional_string(getattr(response, "id", None))
        return GenerationResult(
            text=generated_text,
            model_name=_optional_string(getattr(response, "model", None)),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            request_id=request_id,
            stop_reason=stop_reason,
            provider=self._provider_name,
            metadata=metadata,
        )


class OpenAIClient(OpenAICompatibleClient):
    """Resolve OpenAI settings and reuse the compatibility adapter."""

    def __init__(
        self,
        timeout_seconds: float | None = None,
        *,
        settings: Settings | None = None,
        max_retries: int = 0,
    ) -> None:
        """Initialize OpenAI exclusively from centralized configuration."""

        resolved_settings = settings if settings is not None else get_settings()
        assert resolved_settings.openai_api_key is not None
        assert resolved_settings.model_openai is not None
        self._settings = resolved_settings
        super().__init__(
            api_key=resolved_settings.openai_api_key.get_secret_value(),
            model_name=resolved_settings.model_openai,
            provider_name=OPENAI_PROVIDER_NAME,
            max_tokens=resolved_settings.max_tokens,
            temperature=resolved_settings.temperature,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
