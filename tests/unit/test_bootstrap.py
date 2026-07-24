"""Unit tests for the application composition root."""

from unittest.mock import Mock, patch

from pydantic import SecretStr

from autonomous_ai_company.agents.finance_agent import FinanceAgent
from autonomous_ai_company.audit.audit_logger import (
    AuditLogger,
    InMemoryAuditStorage,
)
from autonomous_ai_company.bootstrap import build_finance_agent
from autonomous_ai_company.config import Settings
from autonomous_ai_company.llm.claude_client import ClaudeClient
from autonomous_ai_company.llm.llm_router import LLMRouter


def configured_settings() -> Settings:
    """Return complete configuration without reading a developer environment."""

    return Settings(
        ANTHROPIC_API_KEY=SecretStr("test-api-key"),
        MODEL_NAME="test-model",
        TEMPERATURE=0.2,
        MAX_TOKENS=1024,
        LOG_LEVEL="INFO",
        _env_file=None,
    )


def test_build_finance_agent_creates_the_correct_shared_dependency_graph() -> None:
    """The returned agent should reference one instance of every dependency."""

    settings = configured_settings()
    sdk_client = Mock()

    with (
        patch(
            "autonomous_ai_company.bootstrap.get_settings",
            return_value=settings,
        ) as mocked_get_settings,
        patch(
            "autonomous_ai_company.llm.claude_client.AsyncAnthropic",
            return_value=sdk_client,
        ) as mocked_anthropic,
    ):
        agent = build_finance_agent()

    assert isinstance(agent, FinanceAgent)
    assert isinstance(agent._audit_logger, AuditLogger)
    assert isinstance(agent._audit_logger._storage, InMemoryAuditStorage)
    assert isinstance(agent._llm_provider, LLMRouter)

    provider = agent._llm_provider.get_provider()
    assert isinstance(provider, ClaudeClient)
    assert provider._settings is settings
    assert agent._llm_provider.get_provider() is provider
    mocked_get_settings.assert_called_once_with()
    mocked_anthropic.assert_called_once_with(
        api_key="test-api-key",
        max_retries=0,
    )


def test_build_finance_agent_constructs_each_dependency_exactly_once() -> None:
    """Bootstrap should inject shared objects instead of rebuilding them."""

    settings = configured_settings()
    storage = Mock(spec=InMemoryAuditStorage)
    audit_logger = Mock(spec=AuditLogger)
    provider = Mock(spec=ClaudeClient)
    router = Mock(spec=LLMRouter)
    agent = Mock(spec=FinanceAgent)

    with (
        patch(
            "autonomous_ai_company.bootstrap.get_settings",
            return_value=settings,
        ) as settings_factory,
        patch(
            "autonomous_ai_company.bootstrap.InMemoryAuditStorage",
            return_value=storage,
        ) as storage_factory,
        patch(
            "autonomous_ai_company.bootstrap.AuditLogger",
            return_value=audit_logger,
        ) as logger_factory,
        patch(
            "autonomous_ai_company.bootstrap.build_provider_factories",
            return_value={"anthropic": lambda: provider},
        ) as provider_factories_builder,
        patch(
            "autonomous_ai_company.bootstrap.LLMRouter",
            return_value=router,
        ) as router_factory,
        patch(
            "autonomous_ai_company.bootstrap.FinanceAgent",
            return_value=agent,
        ) as agent_factory,
    ):
        result = build_finance_agent()

    assert result is agent
    settings_factory.assert_called_once_with()
    storage_factory.assert_called_once_with()
    logger_factory.assert_called_once_with(storage=storage)
    provider_factories_builder.assert_called_once_with(settings)
    router_factory.assert_called_once()
    router_arguments = router_factory.call_args.kwargs
    injected_factory = router_arguments["provider_factories"]["anthropic"]
    assert injected_factory() is provider
    assert router_arguments["provider_name"] == "anthropic"
    agent_factory.assert_called_once_with(
        llm_provider=router,
        audit_logger=audit_logger,
    )
