"""Adapt Ollama's local HTTP API to the provider-neutral LLM contract."""

import logging
from collections.abc import Mapping
from time import perf_counter
from typing import Any

import httpx

from autonomous_ai_company.config import Settings, get_settings
from autonomous_ai_company.exceptions import (
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from autonomous_ai_company.llm.generation_result import GenerationResult


logger = logging.getLogger(__name__)
OLLAMA_PROVIDER_NAME = "ollama"


def _optional_string(value: object) -> str | None:
    """Keep meaningful strings while representing missing telemetry as None."""

    return value if isinstance(value, str) and value else None


def _optional_token_count(value: object) -> int | None:
    """Keep only valid non-negative token counts from the Ollama response."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _translate_http_error(error: httpx.HTTPError) -> LLMError:
    """Map transport/status failures to the shared application hierarchy."""

    if isinstance(error, httpx.TimeoutException):
        return LLMTimeoutError("LLM request timed out")
    if isinstance(error, httpx.HTTPStatusError):
        if error.response.status_code == 429:
            return LLMRateLimitError("LLM request was rate limited")
        if error.response.status_code >= 500:
            return LLMUnavailableError("LLM service is unavailable")
        return LLMError("LLM request failed")
    return LLMUnavailableError("LLM service is unavailable")


class OllamaClient:
    """Call one reusable Ollama async client without requiring an API key.

    Ollama is accessed through its local HTTP boundary. Request payloads remain
    coroutine-local, cancellation propagates naturally through ``httpx``, and
    bounded transport retries cover transient failures without altering the
    agents' separate structured-output correction policy.
    """

    def __init__(
        self,
        timeout_seconds: float | None = None,
        *,
        settings: Settings | None = None,
        max_retries: int = 0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize the local HTTP adapter from centralized configuration."""

        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if isinstance(max_retries, bool) or max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        resolved_settings = settings if settings is not None else get_settings()
        assert resolved_settings.model_ollama is not None
        self._settings = resolved_settings
        self._model_name = resolved_settings.model_ollama
        self._max_tokens = resolved_settings.max_tokens
        self._temperature = resolved_settings.temperature
        self._max_retries = max_retries
        self._client = http_client or httpx.AsyncClient(
            base_url=resolved_settings.ollama_base_url,
            timeout=timeout_seconds,
        )

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> GenerationResult:
        """Generate through ``/api/chat`` and return portable safe telemetry."""

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

        messages: list[dict[str, str]] = []
        if system_prompt is not None:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        body: dict[str, object] = {
            "model": self._model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": (
                    max_tokens if max_tokens is not None else self._max_tokens
                ),
                "temperature": (
                    float(temperature) if temperature is not None else self._temperature
                ),
            },
        }

        request_started = perf_counter()
        response: httpx.Response | None = None
        attempt = 0
        while True:
            try:
                response = await self._client.post("/api/chat", json=body)
                response.raise_for_status()
                break
            except httpx.HTTPError as error:
                translated = _translate_http_error(error)
                retryable = isinstance(
                    translated,
                    (LLMTimeoutError, LLMRateLimitError, LLMUnavailableError),
                )
                if retryable and attempt < self._max_retries:
                    attempt += 1
                    continue
                logger.exception(
                    "Ollama generation request failed",
                    extra={"model_name": self._model_name},
                )
                raise translated from error
        latency_ms = (perf_counter() - request_started) * 1000.0
        assert response is not None

        try:
            payload: Any = response.json()
            if not isinstance(payload, Mapping):
                raise TypeError("Ollama response must be a JSON object")
            message = payload.get("message")
            if not isinstance(message, Mapping):
                raise TypeError("Ollama response did not contain a message")
            generated_text = message.get("content")
            if not isinstance(generated_text, str) or not generated_text:
                raise TypeError("Ollama response did not contain generated text")
        except (TypeError, ValueError) as error:
            raise LLMUnavailableError(str(error)) from error

        input_tokens = _optional_token_count(payload.get("prompt_eval_count"))
        output_tokens = _optional_token_count(payload.get("eval_count"))
        total_tokens = (
            input_tokens + output_tokens
            if input_tokens is not None and output_tokens is not None
            else None
        )
        metadata_values = {
            name: value
            for name in ("total_duration", "load_duration", "eval_duration")
            if isinstance((value := payload.get(name)), (int, float))
            and not isinstance(value, bool)
            and value >= 0
        }
        return GenerationResult(
            text=generated_text,
            model_name=_optional_string(payload.get("model")),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            request_id=_optional_string(response.headers.get("x-request-id")),
            stop_reason=_optional_string(payload.get("done_reason")),
            provider=OLLAMA_PROVIDER_NAME,
            metadata=metadata_values or None,
        )
