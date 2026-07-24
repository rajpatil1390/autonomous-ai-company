"""No-network tests for OpenAI and shared OpenAI-compatible behavior."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    RateLimitError,
)
from pydantic import SecretStr

from autonomous_ai_company.config import Settings
from autonomous_ai_company.exceptions import (
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from autonomous_ai_company.llm.openai_client import (
    OpenAIClient,
    OpenAICompatibleClient,
    _optional_string,
    _optional_token_count,
)


@pytest.fixture
def settings() -> Mock:
    """Return centralized OpenAI configuration without environment access."""

    configured = Mock(spec=Settings)
    configured.openai_api_key = SecretStr("openai-key")
    configured.model_openai = "openai-model"
    configured.max_tokens = 200
    configured.temperature = 0.2
    return configured


@pytest.fixture
def sdk_client() -> Mock:
    """Return an async official-SDK double."""

    client = Mock()
    client.chat.completions.create = AsyncMock(
        return_value=Mock(
            choices=[
                Mock(message=Mock(content="Generated answer"), finish_reason="stop")
            ],
            model="reported-model",
            id="completion-id",
            _request_id="request-id",
            usage=Mock(prompt_tokens=11, completion_tokens=7, total_tokens=18),
            system_fingerprint="fingerprint",
        )
    )
    return client


def build_client(settings: Mock, sdk_client: Mock) -> OpenAIClient:
    """Construct an OpenAI client with its SDK fully mocked."""

    with patch(
        "autonomous_ai_company.llm.openai_client.AsyncOpenAI",
        return_value=sdk_client,
    ):
        return OpenAIClient(settings=settings)


def test_constructor_loads_settings_and_supports_timeout_and_retries(
    settings: Mock,
    sdk_client: Mock,
) -> None:
    """Construction should forward only safe transport configuration."""

    with (
        patch(
            "autonomous_ai_company.llm.openai_client.get_settings",
            return_value=settings,
        ) as get_settings,
        patch(
            "autonomous_ai_company.llm.openai_client.AsyncOpenAI",
            return_value=sdk_client,
        ) as sdk,
    ):
        client = OpenAIClient(timeout_seconds=12.0, max_retries=2)

    get_settings.assert_called_once_with()
    sdk.assert_called_once_with(
        api_key="openai-key",
        max_retries=2,
        timeout=12.0,
    )
    assert client._settings is settings


@pytest.mark.parametrize(
    "arguments",
    [
        {"api_key": ""},
        {"model_name": ""},
        {"provider_name": ""},
        {"timeout_seconds": 0},
        {"max_retries": True},
        {"max_retries": -1},
    ],
)
def test_compatible_constructor_rejects_invalid_configuration(
    arguments: dict[str, object],
) -> None:
    """Invalid adapter construction must fail before SDK initialization."""

    values: dict[str, object] = {
        "api_key": "key",
        "model_name": "model",
        "provider_name": "provider",
        "max_tokens": 10,
        "temperature": 0.2,
    }
    values.update(arguments)
    with pytest.raises(ValueError):
        OpenAICompatibleClient(**values)  # type: ignore[arg-type]


def test_generate_constructs_request_and_returns_complete_telemetry(
    settings: Mock,
    sdk_client: Mock,
) -> None:
    """The adapter should preserve system separation and portable telemetry."""

    client = build_client(settings, sdk_client)
    result = asyncio.run(
        client.generate(
            "Explain results",
            system_prompt="Follow the schema",
            max_tokens=50,
            temperature=0.1,
        )
    )

    sdk_client.chat.completions.create.assert_awaited_once_with(
        model="openai-model",
        messages=[
            {"role": "system", "content": "Follow the schema"},
            {"role": "user", "content": "Explain results"},
        ],
        max_tokens=50,
        temperature=0.1,
    )
    assert result.model_dump(mode="json") == {
        "text": "Generated answer",
        "model_name": "reported-model",
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
        "latency_ms": result.latency_ms,
        "request_id": "request-id",
        "stop_reason": "stop",
        "provider": "openai",
        "metadata": {"system_fingerprint": "fingerprint"},
    }


def test_generate_uses_defaults_and_fallback_telemetry(
    settings: Mock,
    sdk_client: Mock,
) -> None:
    """Missing optional SDK values should stay None or use exact known totals."""

    sdk_client.chat.completions.create.return_value = Mock(
        choices=[Mock(message=Mock(content="Text"), finish_reason=None)],
        model=None,
        id="completion-id",
        _request_id=None,
        usage=Mock(prompt_tokens=3, completion_tokens=4, total_tokens=None),
        system_fingerprint=None,
    )
    client = build_client(settings, sdk_client)

    result = asyncio.run(client.generate("Explain"))

    sdk_client.chat.completions.create.assert_awaited_once_with(
        model="openai-model",
        messages=[{"role": "user", "content": "Explain"}],
        max_tokens=200,
        temperature=0.2,
    )
    assert result.total_tokens == 7
    assert result.request_id == "completion-id"
    assert result.metadata is None
    assert result.stop_reason is None


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"prompt": ""}, "prompt"),
        ({"prompt": 1}, "prompt"),
        ({"prompt": "ok", "system_prompt": ""}, "system_prompt"),
        ({"prompt": "ok", "system_prompt": 1}, "system_prompt"),
        ({"prompt": "ok", "max_tokens": True}, "max_tokens"),
        ({"prompt": "ok", "max_tokens": "1"}, "max_tokens"),
        ({"prompt": "ok", "max_tokens": 0}, "max_tokens"),
        ({"prompt": "ok", "temperature": True}, "temperature"),
        ({"prompt": "ok", "temperature": "0.2"}, "temperature"),
        ({"prompt": "ok", "temperature": -0.1}, "temperature"),
        ({"prompt": "ok", "temperature": 1.1}, "temperature"),
    ],
)
def test_generate_rejects_invalid_request_values(
    settings: Mock,
    sdk_client: Mock,
    arguments: dict[str, object],
    message: str,
) -> None:
    """Strict provider inputs prevent accidental SDK coercion."""

    client = build_client(settings, sdk_client)
    with pytest.raises(ValueError, match=message):
        asyncio.run(client.generate(**arguments))  # type: ignore[arg-type]


def sdk_errors() -> list[tuple[APIError, type[LLMError]]]:
    """Build representative official-SDK errors and expected translations."""

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    rate_response = httpx.Response(429, request=request)
    server_response = httpx.Response(503, request=request)
    client_response = httpx.Response(400, request=request)
    return [
        (APITimeoutError(request), LLMTimeoutError),
        (RateLimitError("rate", response=rate_response, body=None), LLMRateLimitError),
        (APIConnectionError(request=request), LLMUnavailableError),
        (
            APIStatusError("server", response=server_response, body=None),
            LLMUnavailableError,
        ),
        (APIStatusError("bad", response=client_response, body=None), LLMError),
        (APIError("generic", request, body=None), LLMError),
    ]


@pytest.mark.parametrize(("sdk_error", "expected"), sdk_errors())
def test_generate_translates_sdk_errors_with_chained_causes(
    settings: Mock,
    sdk_client: Mock,
    sdk_error: APIError,
    expected: type[LLMError],
) -> None:
    """SDK types must never escape the provider adapter."""

    sdk_client.chat.completions.create.side_effect = sdk_error
    client = build_client(settings, sdk_client)

    with pytest.raises(expected) as captured:
        asyncio.run(client.generate("Explain"))

    assert type(captured.value) is expected
    assert captured.value.__cause__ is sdk_error


def test_generate_propagates_unexpected_errors(
    settings: Mock,
    sdk_client: Mock,
) -> None:
    """Unexpected programming errors retain their identity and traceback."""

    error = RuntimeError("unexpected")
    sdk_client.chat.completions.create.side_effect = error
    client = build_client(settings, sdk_client)
    with pytest.raises(RuntimeError) as captured:
        asyncio.run(client.generate("Explain"))
    assert captured.value is error


@pytest.mark.parametrize(
    "response",
    [
        Mock(choices=[]),
        Mock(choices=[Mock(message=Mock(content=None))]),
    ],
)
def test_generate_rejects_responses_without_text(
    settings: Mock,
    sdk_client: Mock,
    response: Mock,
) -> None:
    """A successful transport without text is not a usable generation."""

    sdk_client.chat.completions.create.return_value = response
    client = build_client(settings, sdk_client)
    with pytest.raises(LLMUnavailableError) as captured:
        asyncio.run(client.generate("Explain"))
    assert isinstance(captured.value.__cause__, RuntimeError)


def test_optional_telemetry_helpers_reject_invalid_values() -> None:
    """Provider telemetry is never coerced or invented."""

    assert _optional_string(1) is None
    assert _optional_string("") is None
    assert _optional_token_count(True) is None
    assert _optional_token_count("1") is None
    assert _optional_token_count(-1) is None
    assert _optional_token_count(0) == 0


def test_generate_propagates_cancellation(
    settings: Mock,
    sdk_client: Mock,
) -> None:
    """Cancelling the caller must cancel the in-flight SDK coroutine."""

    started: asyncio.Event
    cancelled = False

    async def create(**_: object) -> Mock:
        nonlocal cancelled
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled = True
            raise
        raise AssertionError("unreachable")

    sdk_client.chat.completions.create.side_effect = create
    client = build_client(settings, sdk_client)

    async def run() -> None:
        nonlocal started
        started = asyncio.Event()
        task = asyncio.create_task(client.generate("cancel"))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert cancelled is True
