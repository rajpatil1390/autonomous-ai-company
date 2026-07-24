"""Tests for centralized multi-provider adapter construction."""

from unittest.mock import Mock, patch

import pytest

from autonomous_ai_company.config import Settings
from autonomous_ai_company.exceptions import ConfigurationError
from autonomous_ai_company.llm.generation_result import GenerationResult
from autonomous_ai_company.llm.llm_router import LLMProvider, LLMRouter
from autonomous_ai_company.llm.provider_factory import build_provider_factories


def settings_for(provider: str) -> Settings:
    """Build complete synthetic settings for one selected provider."""

    values: dict[str, object] = {
        "LLM_PROVIDER": provider,
        "TEMPERATURE": 0.2,
        "MAX_TOKENS": 100,
        "LOG_LEVEL": "INFO",
    }
    selected = {
        "anthropic": ("ANTHROPIC_API_KEY", "MODEL_ANTHROPIC"),
        "openai": ("OPENAI_API_KEY", "MODEL_OPENAI"),
        "grok": ("XAI_API_KEY", "MODEL_GROK"),
        "ollama": (None, "MODEL_OLLAMA"),
    }
    if provider in selected:
        credential, model = selected[provider]
        values[model] = "test-model"
        if credential is not None:
            values[credential] = "test-key"
    return Settings.model_validate(values)


@pytest.mark.parametrize(
    ("provider_name", "client_symbol"),
    [
        ("anthropic", "ClaudeClient"),
        ("openai", "OpenAIClient"),
        ("grok", "GrokClient"),
        ("ollama", "OllamaClient"),
    ],
)
def test_factory_builds_only_the_router_selected_adapter(
    provider_name: str,
    client_symbol: str,
) -> None:
    """Lazy registry construction must not initialize unused providers."""

    settings = settings_for(provider_name)
    provider = Mock(spec=LLMProvider)
    with patch(
        f"autonomous_ai_company.llm.provider_factory.{client_symbol}",
        return_value=provider,
    ) as client:
        factories = build_provider_factories(settings)
        router = LLMRouter(provider_name, factories)

    client.assert_called_once_with(settings=settings)
    assert router.get_provider() is provider


def test_factory_returns_injected_fake_without_hidden_construction() -> None:
    """Tests control fake behavior through explicit dependency injection."""

    settings = settings_for("fake")
    fake = Mock(spec=LLMProvider)
    fake.generate.return_value = GenerationResult(text="{}", provider="fake")

    factories = build_provider_factories(settings, fake_provider=fake)
    router = LLMRouter("fake", factories)

    assert router.get_provider() is fake


def test_factory_rejects_uninjected_fake_provider() -> None:
    """Production composition must not silently invent test responses."""

    with pytest.raises(ConfigurationError, match="explicitly injected"):
        build_provider_factories(settings_for("fake"))
