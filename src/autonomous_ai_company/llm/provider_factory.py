"""Build provider adapter factories at the application composition boundary.

This module is the only registry of concrete LLM adapters. The router chooses
one normalized name, while agents continue to receive only ``LLMProvider``.
"""

from collections.abc import Mapping

from autonomous_ai_company.config import Settings
from autonomous_ai_company.exceptions import ConfigurationError
from autonomous_ai_company.llm.claude_client import ClaudeClient
from autonomous_ai_company.llm.grok_client import GrokClient
from autonomous_ai_company.llm.llm_router import (
    ANTHROPIC_PROVIDER_NAME,
    FAKE_PROVIDER_NAME,
    GROK_PROVIDER_NAME,
    LLMProvider,
    OLLAMA_PROVIDER_NAME,
    OPENAI_PROVIDER_NAME,
    ProviderFactory,
)
from autonomous_ai_company.llm.ollama_client import OllamaClient
from autonomous_ai_company.llm.openai_client import OpenAIClient


def build_provider_factories(
    settings: Settings,
    *,
    fake_provider: LLMProvider | None = None,
) -> Mapping[str, ProviderFactory]:
    """Return lazy constructors sharing one validated settings instance.

    Only the router's selected constructor is called. A fake is deliberately
    dependency-injected because production code must not invent business-schema
    responses or hide a test double behind global mutable state.

    Raises:
        ConfigurationError: When ``LLM_PROVIDER=fake`` lacks an injected fake.
    """

    factories: dict[str, ProviderFactory] = {
        ANTHROPIC_PROVIDER_NAME: lambda: ClaudeClient(settings=settings),
        OPENAI_PROVIDER_NAME: lambda: OpenAIClient(settings=settings),
        GROK_PROVIDER_NAME: lambda: GrokClient(settings=settings),
        OLLAMA_PROVIDER_NAME: lambda: OllamaClient(settings=settings),
    }
    if fake_provider is not None:
        factories[FAKE_PROVIDER_NAME] = lambda: fake_provider
    elif settings.llm_provider == FAKE_PROVIDER_NAME:
        raise ConfigurationError(
            "LLM_PROVIDER=fake requires an explicitly injected fake provider"
        )
    return factories
