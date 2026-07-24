"""Unit tests for the provider-specific Anthropic SDK wrapper."""

import asyncio
import logging
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from anthropic import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    RateLimitError,
)
from anthropic.types import TextBlock
from pydantic import SecretStr

from autonomous_ai_company.config import Settings
from autonomous_ai_company.exceptions import (
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from autonomous_ai_company.llm.claude_client import ClaudeClient
from autonomous_ai_company.llm.generation_result import GenerationResult


@pytest.fixture
def settings() -> Mock:
    """Provide the exact centralized values expected by the wrapper."""

    configured = Mock(spec=Settings)
    configured.anthropic_api_key = SecretStr("test-api-key")
    configured.model_name = "test-model"
    configured.max_tokens = 1024
    configured.temperature = 0.2
    return configured


@pytest.fixture
def sdk_client() -> Mock:
    """Provide an SDK double so tests can never make a real API request."""

    client = Mock()
    client.messages.create = AsyncMock(
        return_value=Mock(
            content=[TextBlock(type="text", text="Generated answer")],
            id="message-1",
            model="test-model",
            stop_reason="end_turn",
            usage=Mock(input_tokens=12, output_tokens=5),
        )
    )
    return client


def test_constructor_loads_configuration_and_initializes_sdk(
    settings: Mock,
    sdk_client: Mock,
) -> None:
    """The SDK should receive its credential only from centralized settings."""

    with (
        patch(
            "autonomous_ai_company.llm.claude_client.get_settings",
            return_value=settings,
        ) as mocked_get_settings,
        patch(
            "autonomous_ai_company.llm.claude_client.AsyncAnthropic",
            return_value=sdk_client,
        ) as mocked_anthropic,
    ):
        ClaudeClient(timeout_seconds=12.5)

    mocked_get_settings.assert_called_once_with()
    mocked_anthropic.assert_called_once_with(
        api_key="test-api-key",
        max_retries=0,
        timeout=12.5,
    )


def test_constructor_uses_sdk_default_timeout_when_not_overridden(
    settings: Mock,
    sdk_client: Mock,
) -> None:
    """Omitting a timeout should leave timeout selection with the SDK."""

    with (
        patch(
            "autonomous_ai_company.llm.claude_client.get_settings",
            return_value=settings,
        ),
        patch(
            "autonomous_ai_company.llm.claude_client.AsyncAnthropic",
            return_value=sdk_client,
        ) as mocked_anthropic,
    ):
        ClaudeClient()

    mocked_anthropic.assert_called_once_with(
        api_key="test-api-key",
        max_retries=0,
    )


def test_constructor_uses_injected_settings_without_loading_another_instance(
    settings: Mock,
    sdk_client: Mock,
) -> None:
    """Composition should supply one shared settings object to the adapter."""

    with (
        patch(
            "autonomous_ai_company.llm.claude_client.get_settings"
        ) as mocked_get_settings,
        patch(
            "autonomous_ai_company.llm.claude_client.AsyncAnthropic",
            return_value=sdk_client,
        ),
    ):
        client = ClaudeClient(settings=settings)

    assert client._settings is settings
    mocked_get_settings.assert_not_called()


def test_constructor_rejects_non_positive_timeout() -> None:
    """Invalid timeout values should fail before constructing an SDK client."""

    with pytest.raises(ValueError, match="greater than zero"):
        ClaudeClient(timeout_seconds=0)


def test_generate_uses_configured_request_defaults(
    settings: Mock,
    sdk_client: Mock,
) -> None:
    """A basic request should use model and generation settings from config."""

    with (
        patch(
            "autonomous_ai_company.llm.claude_client.get_settings",
            return_value=settings,
        ),
        patch(
            "autonomous_ai_company.llm.claude_client.AsyncAnthropic",
            return_value=sdk_client,
        ),
        patch(
            "autonomous_ai_company.llm.claude_client.perf_counter",
            side_effect=(10.0, 10.125),
        ),
    ):
        client = ClaudeClient()
        result = asyncio.run(client.generate("Explain the results"))

    assert result == GenerationResult(
        text="Generated answer",
        model_name="test-model",
        input_tokens=12,
        output_tokens=5,
        total_tokens=17,
        latency_ms=125.0,
        request_id="message-1",
        stop_reason="end_turn",
        provider="anthropic",
    )
    sdk_client.messages.create.assert_awaited_once_with(
        model="test-model",
        max_tokens=1024,
        temperature=0.2,
        messages=[{"role": "user", "content": "Explain the results"}],
    )


def test_generate_uses_system_prompt_and_request_overrides(
    settings: Mock,
    sdk_client: Mock,
) -> None:
    """Per-call overrides should replace defaults without mutating settings."""

    sdk_client.messages.create.return_value = Mock(
        content=[
            TextBlock(type="text", text="First "),
            TextBlock(type="text", text="second"),
        ]
    )

    with (
        patch(
            "autonomous_ai_company.llm.claude_client.get_settings",
            return_value=settings,
        ),
        patch(
            "autonomous_ai_company.llm.claude_client.AsyncAnthropic",
            return_value=sdk_client,
        ),
    ):
        client = ClaudeClient()
        result = asyncio.run(
            client.generate(
                "Explain the results",
                system_prompt="You are a finance analyst.",
                max_tokens=256,
                temperature=0.0,
            )
        )

    assert isinstance(result, GenerationResult)
    assert result.text == "First second"
    sdk_client.messages.create.assert_awaited_once_with(
        model="test-model",
        max_tokens=256,
        temperature=0.0,
        messages=[{"role": "user", "content": "Explain the results"}],
        system="You are a finance analyst.",
    )


def test_generate_uses_none_for_unavailable_sdk_telemetry(
    settings: Mock,
    sdk_client: Mock,
) -> None:
    """The adapter should never fabricate telemetry absent from the SDK."""

    sdk_client.messages.create.return_value = Mock(
        content=[TextBlock(type="text", text="Generated answer")]
    )

    with (
        patch(
            "autonomous_ai_company.llm.claude_client.get_settings",
            return_value=settings,
        ),
        patch(
            "autonomous_ai_company.llm.claude_client.AsyncAnthropic",
            return_value=sdk_client,
        ),
    ):
        result = asyncio.run(ClaudeClient().generate("Explain the results"))

    assert result.model_name is None
    assert result.input_tokens is None
    assert result.output_tokens is None
    assert result.total_tokens is None
    assert result.request_id is None
    assert result.stop_reason is None
    assert result.latency_ms is not None


@pytest.mark.parametrize(
    ("keyword_arguments", "message"),
    (
        ({"prompt": ""}, "prompt must be"),
        ({"prompt": 123}, "prompt must be"),
        (
            {"prompt": "valid", "system_prompt": "  "},
            "system_prompt must be",
        ),
        ({"prompt": "valid", "max_tokens": 0}, "max_tokens must be"),
        ({"prompt": "valid", "max_tokens": True}, "max_tokens must be"),
        ({"prompt": "valid", "temperature": 1.1}, "temperature must be"),
        ({"prompt": "valid", "temperature": True}, "temperature must be"),
    ),
)
def test_generate_rejects_invalid_arguments(
    settings: Mock,
    sdk_client: Mock,
    keyword_arguments: dict[str, object],
    message: str,
) -> None:
    """Malformed requests should fail locally and never reach Anthropic."""

    with (
        patch(
            "autonomous_ai_company.llm.claude_client.get_settings",
            return_value=settings,
        ),
        patch(
            "autonomous_ai_company.llm.claude_client.AsyncAnthropic",
            return_value=sdk_client,
        ),
    ):
        client = ClaudeClient()
        with pytest.raises(ValueError, match=message):
            asyncio.run(
                client.generate(**keyword_arguments)  # type: ignore[arg-type]
            )

    sdk_client.messages.create.assert_not_awaited()


def test_generate_logs_and_propagates_sdk_error(
    settings: Mock,
    sdk_client: Mock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unexpected non-SDK errors should retain their original traceback."""

    sdk_error = RuntimeError("simulated SDK failure")
    sdk_client.messages.create.side_effect = sdk_error

    with (
        patch(
            "autonomous_ai_company.llm.claude_client.get_settings",
            return_value=settings,
        ),
        patch(
            "autonomous_ai_company.llm.claude_client.AsyncAnthropic",
            return_value=sdk_client,
        ),
        caplog.at_level(
            logging.ERROR,
            logger="autonomous_ai_company.llm.claude_client",
        ),
    ):
        client = ClaudeClient()
        with pytest.raises(RuntimeError) as captured:
            asyncio.run(client.generate("Explain the results"))

    assert captured.value is sdk_error
    assert "Claude generation request failed" in caplog.text
    sdk_client.messages.create.assert_awaited_once()


def anthropic_error_cases() -> tuple[tuple[APIError, type[LLMError]], ...]:
    """Build representative Anthropic failures with valid HTTP context."""

    request = httpx.Request("POST", "https://api.anthropic.test/messages")
    rate_response = httpx.Response(429, request=request)
    server_response = httpx.Response(503, request=request)
    client_response = httpx.Response(400, request=request)
    return (
        (APITimeoutError(request), LLMTimeoutError),
        (
            RateLimitError(
                "rate limited",
                response=rate_response,
                body=None,
            ),
            LLMRateLimitError,
        ),
        (APIConnectionError(request=request), LLMUnavailableError),
        (
            APIStatusError(
                "server unavailable",
                response=server_response,
                body=None,
            ),
            LLMUnavailableError,
        ),
        (
            APIStatusError(
                "invalid request",
                response=client_response,
                body=None,
            ),
            LLMError,
        ),
        (
            APIError("generic SDK error", request, body=None),
            LLMError,
        ),
    )


@pytest.mark.parametrize(("sdk_error", "application_error"), anthropic_error_cases())
def test_generate_translates_anthropic_errors_with_chained_causes(
    settings: Mock,
    sdk_client: Mock,
    sdk_error: APIError,
    application_error: type[LLMError],
) -> None:
    """Provider failures should cross the adapter as neutral application types."""

    sdk_client.messages.create.side_effect = sdk_error

    with (
        patch(
            "autonomous_ai_company.llm.claude_client.get_settings",
            return_value=settings,
        ),
        patch(
            "autonomous_ai_company.llm.claude_client.AsyncAnthropic",
            return_value=sdk_client,
        ),
    ):
        client = ClaudeClient()
        with pytest.raises(application_error) as captured:
            asyncio.run(client.generate("Explain the results"))

    assert type(captured.value) is application_error
    assert captured.value.__cause__ is sdk_error


def test_generate_rejects_response_without_text(
    settings: Mock,
    sdk_client: Mock,
) -> None:
    """A successful transport response without text is not a valid generation."""

    sdk_client.messages.create.return_value = Mock(content=[])

    with (
        patch(
            "autonomous_ai_company.llm.claude_client.get_settings",
            return_value=settings,
        ),
        patch(
            "autonomous_ai_company.llm.claude_client.AsyncAnthropic",
            return_value=sdk_client,
        ),
    ):
        client = ClaudeClient()
        with pytest.raises(
            LLMUnavailableError,
            match="did not contain generated text",
        ) as captured:
            asyncio.run(client.generate("Explain the results"))

    assert isinstance(captured.value.__cause__, RuntimeError)


def test_client_reuses_one_async_sdk_for_concurrent_requests(
    settings: Mock,
    sdk_client: Mock,
) -> None:
    """Concurrent calls should share transport without sharing request state."""

    async def create(**arguments: object) -> Mock:
        await asyncio.sleep(0)
        messages = arguments["messages"]
        prompt = messages[0]["content"]  # type: ignore[index]
        return Mock(
            content=[TextBlock(type="text", text=f"result:{prompt}")],
            model="test-model",
        )

    sdk_client.messages.create.side_effect = create
    with (
        patch(
            "autonomous_ai_company.llm.claude_client.get_settings",
            return_value=settings,
        ),
        patch(
            "autonomous_ai_company.llm.claude_client.AsyncAnthropic",
            return_value=sdk_client,
        ) as mocked_anthropic,
    ):
        client = ClaudeClient()

        async def run_concurrently() -> list[GenerationResult]:
            return await asyncio.gather(
                *(client.generate(f"request-{index}") for index in range(6))
            )

        results = asyncio.run(run_concurrently())

    assert [result.text for result in results] == [
        f"result:request-{index}" for index in range(6)
    ]
    mocked_anthropic.assert_called_once_with(
        api_key="test-api-key",
        max_retries=0,
    )
    assert sdk_client.messages.create.await_count == 6


def test_client_propagates_cancellation_to_async_sdk(
    settings: Mock,
    sdk_client: Mock,
) -> None:
    """Cancelling generation must cancel the in-flight Anthropic coroutine."""

    request_started: asyncio.Event
    sdk_cancelled = False

    async def create(**arguments: object) -> Mock:
        nonlocal sdk_cancelled
        request_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            sdk_cancelled = True
            raise
        raise AssertionError("unreachable")

    sdk_client.messages.create.side_effect = create
    with (
        patch(
            "autonomous_ai_company.llm.claude_client.get_settings",
            return_value=settings,
        ),
        patch(
            "autonomous_ai_company.llm.claude_client.AsyncAnthropic",
            return_value=sdk_client,
        ),
    ):
        client = ClaudeClient()

        async def cancel_generation() -> None:
            nonlocal request_started
            request_started = asyncio.Event()
            task = asyncio.create_task(client.generate("cancel request"))
            await request_started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(cancel_generation())

    assert sdk_cancelled is True
    sdk_client.messages.create.assert_awaited_once()
