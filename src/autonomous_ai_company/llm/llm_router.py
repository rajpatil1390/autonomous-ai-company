"""Expose a provider-neutral boundary for text generation.

Centralizing provider selection prevents agents from importing SDK adapters or
repeating provider-specific branching throughout the application.
"""

from collections.abc import Callable, Mapping
from typing import Protocol

from autonomous_ai_company.llm.claude_client import ClaudeClient
from autonomous_ai_company.llm.generation_result import GenerationResult
from autonomous_ai_company.exceptions import ConfigurationError


ANTHROPIC_PROVIDER_NAME = "anthropic"
OPENAI_PROVIDER_NAME = "openai"
GROK_PROVIDER_NAME = "grok"
OLLAMA_PROVIDER_NAME = "ollama"
FAKE_PROVIDER_NAME = "fake"
CLAUDE_PROVIDER_NAME = ANTHROPIC_PROVIDER_NAME
DEFAULT_PROVIDER_NAME = ANTHROPIC_PROVIDER_NAME


class LLMProvider(Protocol):
    """Define the async capability agents require without naming an SDK.

    Structural typing lets any current or future provider participate when it
    implements this contract; providers do not need to inherit project classes.
    Implementations must be reusable across concurrent calls, keep request state
    local to each coroutine, propagate cancellation, and surface timeouts through
    their provider-neutral exception contract.
    """

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> GenerationResult:
        """Await and return one provider-neutral generation result."""

        ...


type ProviderFactory = Callable[[], LLMProvider]


class LLMRouter:
    """Select one configured provider and forward generation requests to it.

    The registry is the single provider-selection boundary. Injecting factories
    keeps construction testable and allows new adapters to be registered without
    adding conditional provider logic to agents or other consumers. A resolved
    provider is constructed once and safely reused by concurrent callers.
    """

    def __init__(
        self,
        provider_name: str = DEFAULT_PROVIDER_NAME,
        provider_factories: Mapping[str, ProviderFactory] | None = None,
    ) -> None:
        """Resolve and construct the requested provider exactly once.

        Args:
            provider_name: Case-insensitive provider key selected by composition
                code or deployment configuration.
            provider_factories: Optional dependency-injected provider registry.
                Keys should be normalized provider names.

        Raises:
            ConfigurationError: If the provider name is empty or unsupported.
        """

        if not isinstance(provider_name, str) or not provider_name.strip():
            raise ConfigurationError("provider_name must be a non-empty string")

        factories = (
            {ANTHROPIC_PROVIDER_NAME: ClaudeClient}
            if provider_factories is None
            else provider_factories
        )
        normalized_name = provider_name.strip().casefold()
        if normalized_name == "claude":
            normalized_name = ANTHROPIC_PROVIDER_NAME

        try:
            provider_factory = factories[normalized_name]
        except KeyError as error:
            available_providers = ", ".join(sorted(factories)) or "none"
            raise ConfigurationError(
                f"Unsupported LLM provider '{provider_name}'. "
                f"Available providers: {available_providers}"
            ) from error

        self._provider = provider_factory()

    def get_provider(self) -> LLMProvider:
        """Return the configured provider through its abstract contract.

        Exposing the protocol rather than a concrete SDK adapter keeps callers
        dependent on the generation capability instead of provider internals.
        """

        return self._provider

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> GenerationResult:
        """Await and forward a result without changing it or its errors.

        The router intentionally adds no retry or exception translation so the
        selected provider and calling agent retain their established behavior.
        Direct awaiting also preserves cancellation and timeout propagation.
        """

        return await self._provider.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
