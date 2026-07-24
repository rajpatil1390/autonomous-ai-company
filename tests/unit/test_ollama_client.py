"""No-network tests for the local Ollama HTTP adapter."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from autonomous_ai_company.config import Settings
from autonomous_ai_company.exceptions import (
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from autonomous_ai_company.llm.ollama_client import (
    OllamaClient,
    _optional_string,
    _optional_token_count,
)


@pytest.fixture
def settings() -> Mock:
    """Return local provider configuration without environment access."""

    configured = Mock(spec=Settings)
    configured.model_ollama = "llama-model"
    configured.ollama_base_url = "http://localhost:11434"
    configured.max_tokens = 100
    configured.temperature = 0.2
    return configured


def response_payload(**overrides: object) -> dict[str, object]:
    """Build one successful Ollama response body."""

    payload: dict[str, object] = {
        "message": {"role": "assistant", "content": "Local answer"},
        "model": "llama-model",
        "prompt_eval_count": 9,
        "eval_count": 4,
        "done_reason": "stop",
        "total_duration": 1000,
        "load_duration": 200,
        "eval_duration": 700,
    }
    payload.update(overrides)
    return payload


def successful_response(**overrides: object) -> httpx.Response:
    """Create a real in-memory HTTP response without a network call."""

    request = httpx.Request("POST", "http://localhost:11434/api/chat")
    return httpx.Response(
        200,
        request=request,
        json=response_payload(**overrides),
        headers={"x-request-id": "ollama-request"},
    )


def client_with_response(
    settings: Mock, response: httpx.Response
) -> tuple[OllamaClient, Mock]:
    """Construct an adapter with a fully injected async HTTP client."""

    http_client = Mock(spec=httpx.AsyncClient)
    http_client.post = AsyncMock(return_value=response)
    return OllamaClient(settings=settings, http_client=http_client), http_client


def test_constructor_loads_settings_and_builds_async_http_client(
    settings: Mock,
) -> None:
    """Direct construction should use the central base URL and timeout."""

    http_client = Mock(spec=httpx.AsyncClient)
    with (
        patch(
            "autonomous_ai_company.llm.ollama_client.get_settings",
            return_value=settings,
        ) as loader,
        patch(
            "autonomous_ai_company.llm.ollama_client.httpx.AsyncClient",
            return_value=http_client,
        ) as constructor,
    ):
        client = OllamaClient(timeout_seconds=15.0, max_retries=2)

    loader.assert_called_once_with()
    constructor.assert_called_once_with(
        base_url="http://localhost:11434",
        timeout=15.0,
    )
    assert client._client is http_client
    assert client._max_retries == 2


@pytest.mark.parametrize(
    "arguments",
    [
        {"timeout_seconds": 0},
        {"max_retries": True},
        {"max_retries": -1},
    ],
)
def test_constructor_rejects_invalid_transport_settings(
    settings: Mock,
    arguments: dict[str, object],
) -> None:
    """Invalid timeout and retry policies fail before HTTP construction."""

    with pytest.raises(ValueError):
        OllamaClient(settings=settings, **arguments)  # type: ignore[arg-type]


def test_generate_builds_chat_request_and_returns_telemetry(settings: Mock) -> None:
    """Ollama responses should become the shared immutable DTO."""

    client, http_client = client_with_response(settings, successful_response())
    result = asyncio.run(
        client.generate(
            "Explain",
            system_prompt="Follow schema",
            max_tokens=40,
            temperature=0.1,
        )
    )

    http_client.post.assert_awaited_once_with(
        "/api/chat",
        json={
            "model": "llama-model",
            "messages": [
                {"role": "system", "content": "Follow schema"},
                {"role": "user", "content": "Explain"},
            ],
            "stream": False,
            "options": {"num_predict": 40, "temperature": 0.1},
        },
    )
    assert result.provider == "ollama"
    assert result.text == "Local answer"
    assert result.total_tokens == 13
    assert result.request_id == "ollama-request"
    assert result.metadata == {
        "total_duration": 1000,
        "load_duration": 200,
        "eval_duration": 700,
    }


def test_generate_uses_defaults_and_preserves_missing_telemetry(settings: Mock) -> None:
    """Unavailable Ollama values must remain None instead of being invented."""

    response = successful_response(
        model=None,
        prompt_eval_count=None,
        eval_count=None,
        done_reason=None,
        total_duration=True,
        load_duration=-1,
        eval_duration="unknown",
    )
    response.headers.pop("x-request-id")
    client, http_client = client_with_response(settings, response)

    result = asyncio.run(client.generate("Explain"))

    assert http_client.post.await_args.kwargs["json"]["options"] == {
        "num_predict": 100,
        "temperature": 0.2,
    }
    assert result.model_name is None
    assert result.total_tokens is None
    assert result.stop_reason is None
    assert result.request_id is None
    assert result.metadata is None


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
    arguments: dict[str, object],
    message: str,
) -> None:
    """Strict request validation matches the other provider adapters."""

    client, _ = client_with_response(settings, successful_response())
    with pytest.raises(ValueError, match=message):
        asyncio.run(client.generate(**arguments))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("status", "expected"),
    [(400, LLMError), (429, LLMRateLimitError), (503, LLMUnavailableError)],
)
def test_generate_translates_http_status_errors(
    settings: Mock,
    status: int,
    expected: type[LLMError],
) -> None:
    """Ollama status codes should cross the adapter as neutral exceptions."""

    request = httpx.Request("POST", "http://localhost:11434/api/chat")
    response = httpx.Response(status, request=request)
    client, _ = client_with_response(settings, response)
    with pytest.raises(expected) as captured:
        asyncio.run(client.generate("Explain"))
    assert isinstance(captured.value.__cause__, httpx.HTTPStatusError)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            httpx.ReadTimeout(
                "timeout",
                request=httpx.Request("POST", "http://localhost/api/chat"),
            ),
            LLMTimeoutError,
        ),
        (
            httpx.ConnectError(
                "offline",
                request=httpx.Request("POST", "http://localhost/api/chat"),
            ),
            LLMUnavailableError,
        ),
    ],
)
def test_generate_translates_transport_errors(
    settings: Mock,
    error: httpx.HTTPError,
    expected: type[LLMError],
) -> None:
    """Timeout and connection failures should preserve their original cause."""

    http_client = Mock(spec=httpx.AsyncClient)
    http_client.post = AsyncMock(side_effect=error)
    client = OllamaClient(settings=settings, http_client=http_client)
    with pytest.raises(expected) as captured:
        asyncio.run(client.generate("Explain"))
    assert captured.value.__cause__ is error


def test_generate_retries_transient_failure_once(settings: Mock) -> None:
    """Configured transport retry is independent of agent schema correction."""

    request = httpx.Request("POST", "http://localhost/api/chat")
    connection_error = httpx.ConnectError("offline", request=request)
    http_client = Mock(spec=httpx.AsyncClient)
    http_client.post = AsyncMock(side_effect=[connection_error, successful_response()])
    client = OllamaClient(
        settings=settings,
        http_client=http_client,
        max_retries=1,
    )

    result = asyncio.run(client.generate("Explain"))

    assert result.text == "Local answer"
    assert http_client.post.await_count == 2


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(
            200,
            request=httpx.Request("POST", "http://localhost/api/chat"),
            content=b"{",
        ),
        httpx.Response(
            200,
            request=httpx.Request("POST", "http://localhost/api/chat"),
            json=[],
        ),
        httpx.Response(
            200,
            request=httpx.Request("POST", "http://localhost/api/chat"),
            json={},
        ),
        httpx.Response(
            200,
            request=httpx.Request("POST", "http://localhost/api/chat"),
            json={"message": []},
        ),
        httpx.Response(
            200,
            request=httpx.Request("POST", "http://localhost/api/chat"),
            json={"message": {"content": None}},
        ),
    ],
)
def test_generate_rejects_malformed_provider_responses(
    settings: Mock,
    response: httpx.Response,
) -> None:
    """Malformed local responses must not escape as partial DTOs."""

    client, _ = client_with_response(settings, response)
    with pytest.raises(LLMUnavailableError) as captured:
        asyncio.run(client.generate("Explain"))
    assert isinstance(captured.value.__cause__, (TypeError, ValueError))


def test_optional_telemetry_helpers_reject_invalid_values() -> None:
    """Ollama telemetry is kept only when its type and range are trustworthy."""

    assert _optional_string(1) is None
    assert _optional_string("") is None
    assert _optional_token_count(True) is None
    assert _optional_token_count("1") is None
    assert _optional_token_count(-1) is None
    assert _optional_token_count(0) == 0


def test_generate_propagates_cancellation(settings: Mock) -> None:
    """Cancelling a workflow should cancel its local HTTP request."""

    started: asyncio.Event
    cancelled = False
    http_client = Mock(spec=httpx.AsyncClient)

    async def post(*_: object, **__: object) -> httpx.Response:
        nonlocal cancelled
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled = True
            raise
        raise AssertionError("unreachable")

    http_client.post = AsyncMock(side_effect=post)
    client = OllamaClient(settings=settings, http_client=http_client)

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
