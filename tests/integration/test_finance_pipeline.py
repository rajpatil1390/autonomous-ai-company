"""Component integration test for the complete real Finance Agent pipeline."""

import asyncio
from collections.abc import Iterator
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import pytest

from autonomous_ai_company.agents.finance_agent import FinanceAgent
from autonomous_ai_company.audit.audit_logger import (
    AuditLogger,
    InMemoryAuditStorage,
)
from autonomous_ai_company.bootstrap import build_finance_agent
from autonomous_ai_company.config import Settings, get_settings
from autonomous_ai_company.llm.generation_result import GenerationResult
from autonomous_ai_company.llm.llm_router import LLMProvider, LLMRouter
from autonomous_ai_company.schemas.agent_outputs import FinanceAgentOutput
from autonomous_ai_company.schemas.audit import AuditEventType
from autonomous_ai_company.tools.finance_tools import FinancialDataset


CURRENT_PERIOD: FinancialDataset = (
    {"revenue": Decimal("100.10"), "cost": Decimal("60.03")},
    {"revenue": Decimal("200.20"), "cost": Decimal("120.06")},
)
PREVIOUS_PERIOD: FinancialDataset = (
    {"revenue": Decimal("80.08"), "cost": Decimal("50.00")},
    {"revenue": Decimal("120.12"), "cost": Decimal("70.00")},
)
EXPECTED_OUTPUT = FinanceAgentOutput(
    executive_summary="Revenue grew while the business remained profitable.",
    key_findings=["Revenue growth was positive."],
    recommendations=["Continue monitoring cost growth."],
    risk_level="low",
    confidence_score=0.95,
)


class FakeLLMProvider:
    """Return deterministic validated text without external communication."""

    def __init__(self, settings: Settings, response: FinanceAgentOutput) -> None:
        """Retain injected configuration and the fixed response for assertions."""

        self.settings = settings
        self.response = response
        self.prompts: list[str] = []

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> GenerationResult:
        """Record the real prompt and return schema-compatible provider data."""

        self.prompts.append(prompt)
        return GenerationResult(
            text=self.response.model_dump_json(),
            model_name="fake-model",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            latency_ms=10.0,
            request_id="fake-request",
            stop_reason="end_turn",
            provider="fake",
        )


@pytest.fixture
def application_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[Settings]:
    """Load real cached settings from an isolated process environment."""

    monkeypatch.chdir(tmp_path)
    environment = {
        "ANTHROPIC_API_KEY": "integration-test-key",
        "MODEL_NAME": "integration-test-model",
        "TEMPERATURE": "0.2",
        "MAX_TOKENS": "1024",
        "LOG_LEVEL": "INFO",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    settings = get_settings()

    yield settings

    get_settings.cache_clear()


def test_real_finance_pipeline_with_only_llm_provider_replaced(
    application_settings: Settings,
) -> None:
    """Execute every real component while preventing file and network I/O."""

    fake_provider = FakeLLMProvider(application_settings, EXPECTED_OUTPUT)
    provider_contract: LLMProvider = fake_provider
    assert provider_contract is fake_provider

    blocked_operation = AssertionError("external I/O is forbidden in this test")
    with (
        patch(
            "autonomous_ai_company.bootstrap.build_provider_factories",
            return_value={"anthropic": lambda: fake_provider},
        ) as provider_factories_builder,
        patch(
            "autonomous_ai_company.llm.claude_client.AsyncAnthropic"
        ) as anthropic_constructor,
        patch("builtins.open", side_effect=blocked_operation) as open_guard,
        patch.object(Path, "open", side_effect=blocked_operation) as path_guard,
        patch(
            "socket.create_connection",
            side_effect=blocked_operation,
        ) as socket_guard,
        patch(
            "httpx.Client.send",
            side_effect=blocked_operation,
        ) as httpx_guard,
        patch(
            "httpx.AsyncClient.send",
            side_effect=blocked_operation,
        ) as async_httpx_guard,
        patch(
            "urllib.request.urlopen",
            side_effect=blocked_operation,
        ) as urlopen_guard,
    ):
        agent = build_finance_agent()
        output = asyncio.run(
            agent.run(
                run_id="real-finance-pipeline",
                current_period=CURRENT_PERIOD,
                previous_period=PREVIOUS_PERIOD,
                business_context="Subscription software company.",
                user_question="What should leadership monitor?",
            )
        )

    assert isinstance(agent, FinanceAgent)
    assert isinstance(agent._llm_provider, LLMRouter)
    assert isinstance(agent._audit_logger, AuditLogger)
    assert isinstance(agent._audit_logger._storage, InMemoryAuditStorage)
    assert agent._llm_provider.get_provider() is fake_provider
    assert fake_provider.settings is application_settings
    provider_factories_builder.assert_called_once_with(application_settings)

    assert fake_provider.prompts and len(fake_provider.prompts) == 1
    prompt = fake_provider.prompts[0]
    expected_decimal_kpis = {
        "total_revenue": "300.30",
        "total_profit": "120.21",
        "total_cost": "180.09",
        "average_order_value": "150.15",
        "profit_margin": "40.03",
        "revenue_growth_rate": "50.00",
    }
    for name, value in expected_decimal_kpis.items():
        assert f'"{name}": "{value}"' in prompt
    assert "Subscription software company." in prompt
    assert "What should leadership monitor?" in prompt

    assert output == EXPECTED_OUTPUT
    assert isinstance(output, FinanceAgentOutput)

    events = agent._audit_logger.get_events()
    assert tuple(event.event_type for event in events) == (
        AuditEventType.START,
        AuditEventType.TOOL_CALL,
        AuditEventType.TOOL_CALL,
        AuditEventType.LLM_REQUEST,
        AuditEventType.LLM_RESPONSE,
        AuditEventType.FINISH,
    )
    assert events[0].payload == {}
    assert events[1].payload == {}
    assert events[2].payload == {}
    prompt_hash = events[3].payload["prompt_hash"]
    expected_prompt_hash = f"sha256:{sha256(prompt.encode('utf-8')).hexdigest()}"
    assert events[3].payload == {
        "prompt_hash": expected_prompt_hash,
        "prompt_length": len(prompt),
        "attempt": 1,
    }
    assert prompt_hash == expected_prompt_hash
    algorithm, digest = prompt_hash.split(":", maxsplit=1)
    assert algorithm == "sha256"
    assert len(digest) == 64
    assert digest == digest.lower()
    assert all(character in "0123456789abcdef" for character in digest)
    deterministic_hash = f"sha256:{sha256(prompt.encode('utf-8')).hexdigest()}"
    changed_hash = f"sha256:{sha256(f'{prompt} changed'.encode('utf-8')).hexdigest()}"
    assert prompt_hash == deterministic_hash
    assert prompt_hash != changed_hash
    assert events[4].payload == {
        "provider": "fake",
        "model_name": "fake-model",
        "latency_ms": 10.0,
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
        "stop_reason": "end_turn",
        "request_id": "fake-request",
    }
    assert events[-1].payload == {"status": "success"}
    assert all(event.metadata is None for event in events)
    serialized_audit = "".join(event.model_dump_json() for event in events)
    assert prompt not in serialized_audit
    assert EXPECTED_OUTPUT.model_dump_json() not in serialized_audit
    for forbidden_field in (
        "raw_prompt",
        "system_prompt",
        "user_prompt",
        "messages",
        "raw_response",
        "generated_text",
    ):
        assert forbidden_field not in serialized_audit

    anthropic_constructor.assert_not_called()
    open_guard.assert_not_called()
    path_guard.assert_not_called()
    socket_guard.assert_not_called()
    httpx_guard.assert_not_called()
    async_httpx_guard.assert_not_called()
    urlopen_guard.assert_not_called()
