"""Unit tests for centralized provider selection and request forwarding."""

import asyncio
from unittest.mock import Mock, patch

import pytest

from autonomous_ai_company.llm.generation_result import GenerationResult
from autonomous_ai_company.llm.llm_router import (
    ANTHROPIC_PROVIDER_NAME,
    CLAUDE_PROVIDER_NAME,
    LLMProvider,
    LLMRouter,
)
from autonomous_ai_company.exceptions import LLMTimeoutError
from autonomous_ai_company.exceptions import ConfigurationError


GENERATED_RESULT = GenerationResult(
    text="generated text",
    provider="fake",
)


def test_router_selects_mocked_claude_provider_by_default() -> None:
    """Phase A's default registry should construct Claude exactly once."""

    mocked_provider = Mock()

    with patch(
        "autonomous_ai_company.llm.llm_router.ClaudeClient",
        return_value=mocked_provider,
    ) as mocked_claude_client:
        router = LLMRouter()

    mocked_claude_client.assert_called_once_with()
    assert router.get_provider() is mocked_provider


def test_router_uses_injected_factory_and_normalizes_provider_name() -> None:
    """Composition code should be able to inject provider construction."""

    mocked_provider = Mock()
    mocked_factory = Mock(return_value=mocked_provider)

    router = LLMRouter(
        provider_name="  CLAUDE  ",
        provider_factories={CLAUDE_PROVIDER_NAME: mocked_factory},
    )

    mocked_factory.assert_called_once_with()
    assert router.get_provider() is mocked_provider


@pytest.mark.parametrize("provider_name", ("", "   ", 123))
def test_router_rejects_invalid_provider_name(provider_name: object) -> None:
    """Invalid configuration should fail before constructing a provider."""

    with pytest.raises(ConfigurationError, match="non-empty string"):
        LLMRouter(provider_name=provider_name)  # type: ignore[arg-type]


def test_router_rejects_unsupported_provider() -> None:
    """Unsupported selections should identify the currently available option."""

    with pytest.raises(ConfigurationError, match="Available providers: anthropic"):
        LLMRouter(provider_name="openai")


def test_router_reports_when_injected_registry_is_empty() -> None:
    """An empty registry should produce an actionable configuration error."""

    with pytest.raises(ConfigurationError, match="Available providers: none"):
        LLMRouter(provider_factories={})


def test_router_accepts_legacy_claude_alias() -> None:
    """Older composition code may still name Claude while migrating config."""

    provider = Mock(spec=LLMProvider)
    router = LLMRouter(
        provider_name="claude",
        provider_factories={ANTHROPIC_PROVIDER_NAME: lambda: provider},
    )

    assert router.get_provider() is provider


def test_router_forwards_default_request_arguments_unchanged() -> None:
    """The router should not invent provider parameters for a basic request."""

    mocked_provider = Mock(spec=LLMProvider)
    mocked_provider.generate.return_value = GENERATED_RESULT
    router = LLMRouter(
        provider_factories={CLAUDE_PROVIDER_NAME: lambda: mocked_provider}
    )

    result = asyncio.run(router.generate("Explain the analysis"))

    assert result is GENERATED_RESULT
    mocked_provider.generate.assert_awaited_once_with(
        prompt="Explain the analysis",
        system_prompt=None,
        max_tokens=None,
        temperature=None,
    )


def test_router_forwards_all_request_overrides_unchanged() -> None:
    """System and generation overrides should reach the selected provider."""

    mocked_provider = Mock(spec=LLMProvider)
    mocked_provider.generate.return_value = GENERATED_RESULT
    router = LLMRouter(
        provider_factories={CLAUDE_PROVIDER_NAME: lambda: mocked_provider}
    )

    result = asyncio.run(
        router.generate(
            "Explain the analysis",
            system_prompt="You are an analyst.",
            max_tokens=512,
            temperature=0.1,
        )
    )

    assert result is GENERATED_RESULT
    mocked_provider.generate.assert_awaited_once_with(
        prompt="Explain the analysis",
        system_prompt="You are an analyst.",
        max_tokens=512,
        temperature=0.1,
    )


def test_router_propagates_provider_exception_unchanged() -> None:
    """Agent-level error policy requires the original provider exception."""

    provider_error = RuntimeError("provider failed")
    mocked_provider = Mock(spec=LLMProvider)
    mocked_provider.generate.side_effect = provider_error
    router = LLMRouter(
        provider_factories={CLAUDE_PROVIDER_NAME: lambda: mocked_provider}
    )

    with pytest.raises(RuntimeError) as captured:
        asyncio.run(router.generate("Explain the analysis"))

    assert captured.value is provider_error


def test_router_reuses_provider_for_concurrent_requests_without_state_leaks() -> None:
    """One provider instance should safely serve interleaved async requests."""

    mocked_provider = Mock(spec=LLMProvider)

    async def generate(
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> GenerationResult:
        await asyncio.sleep(0)
        return GenerationResult(text=f"result:{prompt}", provider="fake")

    mocked_provider.generate.side_effect = generate
    mocked_factory = Mock(return_value=mocked_provider)
    router = LLMRouter(provider_factories={CLAUDE_PROVIDER_NAME: mocked_factory})

    async def run_concurrently() -> list[GenerationResult]:
        return await asyncio.gather(
            *(router.generate(f"request-{index}") for index in range(8))
        )

    results = asyncio.run(run_concurrently())

    assert [result.text for result in results] == [
        f"result:request-{index}" for index in range(8)
    ]
    mocked_factory.assert_called_once_with()
    assert router.get_provider() is mocked_provider
    assert mocked_provider.generate.await_count == 8


def test_router_propagates_timeout_unchanged() -> None:
    """Provider-neutral timeout policy must remain visible to the agent."""

    timeout_error = LLMTimeoutError("provider timed out")
    mocked_provider = Mock(spec=LLMProvider)
    mocked_provider.generate.side_effect = timeout_error
    router = LLMRouter(
        provider_factories={CLAUDE_PROVIDER_NAME: lambda: mocked_provider}
    )

    with pytest.raises(LLMTimeoutError) as captured:
        asyncio.run(router.generate("Explain the analysis"))

    assert captured.value is timeout_error


def test_router_propagates_task_cancellation() -> None:
    """Cancelling a caller must cancel the in-flight provider await."""

    mocked_provider = Mock(spec=LLMProvider)
    provider_started: asyncio.Event
    provider_cancelled = False

    async def generate(
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> GenerationResult:
        nonlocal provider_cancelled
        provider_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            provider_cancelled = True
            raise
        raise AssertionError("unreachable")

    mocked_provider.generate.side_effect = generate
    router = LLMRouter(
        provider_factories={CLAUDE_PROVIDER_NAME: lambda: mocked_provider}
    )

    async def cancel_request() -> None:
        nonlocal provider_started
        provider_started = asyncio.Event()
        task = asyncio.create_task(router.generate("cancel me"))
        await provider_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_request())

    assert provider_cancelled is True
    mocked_provider.generate.assert_awaited_once()
