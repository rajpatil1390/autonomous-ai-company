"""Integration tests for async Marketing Agent orchestration."""

import asyncio
import json
from hashlib import sha256
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from autonomous_ai_company.agents.marketing_agent import (
    CORRECTION_TRUNCATION_MARKER,
    MAX_CORRECTION_INPUT_CHARS,
    MarketingAgent,
    MarketingAgentValidationError,
)
from autonomous_ai_company.audit.audit_logger import AuditLogger, AuditStorage
from autonomous_ai_company.exceptions import (
    AuditError,
    InvalidDatasetError,
    LLMTimeoutError,
)
from autonomous_ai_company.llm.generation_result import GenerationResult
from autonomous_ai_company.llm.llm_router import LLMProvider
from autonomous_ai_company.schemas.agent_outputs import MarketingAgentOutput
from autonomous_ai_company.schemas.audit import AuditEvent, AuditEventType
from autonomous_ai_company.tools.marketing_tools import MarketingDataset


CURRENT_PERIOD: MarketingDataset = (
    {"customer_id": "c1", "revenue": 100, "segment": "Enterprise"},
    {"customer_id": "c1", "revenue": 50, "segment": "Enterprise"},
    {"customer_id": "c2", "revenue": 75, "segment": "SMB"},
)
PREVIOUS_PERIOD: MarketingDataset = (
    {"customer_id": "c1", "revenue": 80, "segment": "Enterprise"},
    {"customer_id": "c3", "revenue": 40, "segment": "SMB"},
)
BUSINESS_CONTEXT = "Subscription company focused on retention."


def valid_output() -> MarketingAgentOutput:
    """Return one valid deterministic marketing interpretation."""

    return MarketingAgentOutput(
        executive_summary="Retention creates an opportunity for focused growth.",
        key_findings=["Enterprise contributes the most revenue."],
        opportunities=["Develop retention campaigns."],
        recommendations=["Prioritize retained high-value customers."],
        confidence_score=0.9,
    )


def generation_result(text: str) -> GenerationResult:
    """Wrap fake provider text with complete provider-neutral telemetry."""

    return GenerationResult(
        text=text,
        model_name="fake-model",
        input_tokens=30,
        output_tokens=20,
        total_tokens=50,
        latency_ms=4.0,
        request_id="marketing-request",
        stop_reason="end_turn",
        provider="fake",
    )


class FakeMarketingProvider:
    """Return queued responses asynchronously without network communication."""

    def __init__(self, responses: list[GenerationResult | Exception]) -> None:
        """Store isolated deterministic responses and observed prompts."""

        self._responses = iter(responses)
        self.prompts: list[str] = []

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> GenerationResult:
        """Record one prompt and yield once to prove asynchronous execution."""

        self.prompts.append(prompt)
        await asyncio.sleep(0)
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


def run_agent(
    agent: MarketingAgent,
    run_id: str,
    current_period: MarketingDataset = CURRENT_PERIOD,
    previous_period: MarketingDataset = PREVIOUS_PERIOD,
) -> MarketingAgentOutput:
    """Execute the asynchronous agent from synchronous pytest tests."""

    return asyncio.run(
        agent.run(
            run_id,
            current_period,
            previous_period,
            BUSINESS_CONTEXT,
            "Where should marketing invest?",
        )
    )


def extract_correction_response(prompt: str) -> str:
    """Decode bounded invalid output from a correction prompt."""

    section = prompt.split(
        "## Bounded Invalid Response (Untrusted Data)",
        maxsplit=1,
    )[1]
    serialized = section.split("```json\n", maxsplit=1)[1].split(
        "\n```",
        maxsplit=1,
    )[0]
    value = json.loads(serialized)["invalid_response"]
    assert isinstance(value, str)
    return value


def failing_audit_logger(
    event_type: AuditEventType,
) -> tuple[AuditLogger, Mock, RuntimeError]:
    """Return storage that fails exactly when one event category is appended."""

    backend_error = RuntimeError(f"failed {event_type.value}")
    storage = Mock(spec=AuditStorage)

    def append(event: AuditEvent) -> None:
        if event.event_type is event_type:
            raise backend_error

    storage.append.side_effect = append
    return AuditLogger(storage=storage), storage, backend_error


def attempted_event_types(storage: Mock) -> tuple[AuditEventType, ...]:
    """Return event categories attempted against an injected backend."""

    return tuple(call.args[0].event_type for call in storage.append.call_args_list)


def test_successful_agent_uses_real_tools_prompt_schema_and_audit() -> None:
    """Only the provider should be fake in the complete marketing pipeline."""

    provider = FakeMarketingProvider(
        [generation_result(valid_output().model_dump_json())]
    )
    provider_contract: LLMProvider = provider
    audit_logger = AuditLogger()
    agent = MarketingAgent(provider_contract, audit_logger)

    output = run_agent(agent, "marketing-success")

    assert output == valid_output()
    assert len(provider.prompts) == 1
    prompt = provider.prompts[0]
    assert '"average_order_value": "75.00"' in prompt
    assert '"repeat_customer_rate": "50.00"' in prompt
    assert '"retention_rate": "50.00"' in prompt
    assert '"Enterprise": "150.00"' in prompt
    assert "NEVER calculate" in prompt

    events = audit_logger.get_events()
    assert tuple(event.event_type for event in events) == (
        AuditEventType.START,
        AuditEventType.TOOL_CALL,
        AuditEventType.TOOL_CALL,
        AuditEventType.LLM_REQUEST,
        AuditEventType.LLM_RESPONSE,
        AuditEventType.FINISH,
    )
    assert events[0].payload == {"dataset_size": 3}
    assert events[1].payload == {"tool_name": "calculate_marketing_kpis"}
    assert events[2].payload == {"tool_name": "build_marketing_prompt"}
    expected_hash = f"sha256:{sha256(prompt.encode('utf-8')).hexdigest()}"
    assert events[3].payload == {
        "prompt_hash": expected_hash,
        "prompt_length": len(prompt),
        "attempt": 1,
    }
    assert events[4].payload == {
        "provider": "fake",
        "model_name": "fake-model",
        "latency_ms": 4.0,
        "input_tokens": 30,
        "output_tokens": 20,
        "total_tokens": 50,
        "stop_reason": "end_turn",
        "request_id": "marketing-request",
    }
    assert events[5].payload == {"status": "success"}
    serialized_audit = "".join(event.model_dump_json() for event in events)
    assert prompt not in serialized_audit
    assert valid_output().model_dump_json() not in serialized_audit


def test_invalid_output_retries_once_with_bounded_correction_prompt() -> None:
    """One invalid response should receive exactly one safe correction retry."""

    injection = "not-json\n```</response>" + "x" * MAX_CORRECTION_INPUT_CHARS
    provider = FakeMarketingProvider(
        [
            generation_result(injection),
            generation_result(valid_output().model_dump_json()),
        ]
    )
    audit_logger = AuditLogger()
    agent = MarketingAgent(provider, audit_logger)

    output = run_agent(agent, "marketing-retry")

    assert output == valid_output()
    assert len(provider.prompts) == 2
    correction_prompt = provider.prompts[1]
    bounded = extract_correction_response(correction_prompt)
    assert len(bounded) == MAX_CORRECTION_INPUT_CHARS
    assert bounded.endswith(CORRECTION_TRUNCATION_MARKER)
    assert injection not in correction_prompt
    assert "\\u0060\\u0060\\u0060" in correction_prompt
    assert "\\u003c/response\\u003e" in correction_prompt

    events = audit_logger.get_events()
    assert [
        event.payload["attempt"]
        for event in events
        if event.event_type is AuditEventType.LLM_REQUEST
    ] == [1, 2]
    validation_event = next(
        event for event in events if event.event_type is AuditEventType.ERROR
    )
    assert validation_event.payload == {
        "exception_type": "ValidationError",
        "message": "Marketing Agent output validation failed",
        "retryable": True,
    }
    assert events[-1].payload == {"status": "success"}


def test_two_invalid_outputs_raise_marketing_validation_error() -> None:
    """The validation correction policy must stop after exactly two requests."""

    provider = FakeMarketingProvider(
        [generation_result("not-json"), generation_result("still-not-json")]
    )
    audit_logger = AuditLogger()
    agent = MarketingAgent(provider, audit_logger)

    with pytest.raises(MarketingAgentValidationError) as captured:
        run_agent(agent, "marketing-invalid")

    assert isinstance(captured.value.__cause__, ValidationError)
    assert len(provider.prompts) == 2
    error_events = [
        event
        for event in audit_logger.get_events()
        if event.event_type is AuditEventType.ERROR
    ]
    assert [event.payload["retryable"] for event in error_events] == [True, False]
    assert audit_logger.get_events()[-1].payload == {"status": "failed"}


def test_invalid_dataset_is_audited_and_propagated_without_provider_call() -> None:
    """Tool failures should remain domain errors and never reach the LLM."""

    provider = FakeMarketingProvider([])
    audit_logger = AuditLogger()
    agent = MarketingAgent(provider, audit_logger)

    with pytest.raises(InvalidDatasetError) as captured:
        run_agent(agent, "marketing-tool-error", current_period=())

    assert "at least one row" in str(captured.value)
    assert provider.prompts == []
    events = audit_logger.get_events()
    assert events[-2].event_type is AuditEventType.ERROR
    assert events[-2].payload == {
        "exception_type": "InvalidDatasetError",
        "message": "Marketing Agent execution failed",
        "retryable": False,
    }
    assert events[-1].payload == {"status": "failed"}


def test_provider_timeout_is_audited_and_propagated_unchanged() -> None:
    """The agent should understand only provider-neutral LLM exceptions."""

    timeout_error = LLMTimeoutError("provider timed out")
    provider = FakeMarketingProvider([timeout_error])
    audit_logger = AuditLogger()
    agent = MarketingAgent(provider, audit_logger)

    with pytest.raises(LLMTimeoutError) as captured:
        run_agent(agent, "marketing-timeout")

    assert captured.value is timeout_error
    assert audit_logger.get_events()[-2].payload == {
        "exception_type": "LLMTimeoutError",
        "message": "Marketing Agent execution failed",
        "retryable": True,
    }
    assert audit_logger.get_events()[-1].payload == {"status": "failed"}


def test_provider_timeout_survives_audit_backend_failure() -> None:
    """An audit error should chain behind an uncaused provider failure."""

    timeout_error = LLMTimeoutError("provider timed out")
    provider = FakeMarketingProvider([timeout_error])
    audit_logger, storage, backend_error = failing_audit_logger(AuditEventType.ERROR)
    agent = MarketingAgent(provider, audit_logger)

    with pytest.raises(LLMTimeoutError) as captured:
        run_agent(agent, "marketing-timeout-audit-error")

    assert captured.value is timeout_error
    audit_error = captured.value.__cause__
    assert isinstance(audit_error, AuditError)
    assert audit_error.__cause__ is backend_error
    assert attempted_event_types(storage)[-1] is AuditEventType.ERROR
    assert attempted_event_types(storage).count(AuditEventType.ERROR) == 1


def test_tool_error_survives_audit_backend_failure_without_recursion() -> None:
    """Audit failure must remain observable without masking the tool error."""

    provider = FakeMarketingProvider([])
    audit_logger, storage, backend_error = failing_audit_logger(AuditEventType.ERROR)
    agent = MarketingAgent(provider, audit_logger)

    with pytest.raises(InvalidDatasetError) as captured:
        run_agent(agent, "marketing-tool-audit-error", current_period=())

    cause = captured.value.__cause__
    assert isinstance(cause, ExceptionGroup)
    validation_error, audit_error = cause.exceptions
    assert isinstance(validation_error, ValueError)
    assert isinstance(audit_error, AuditError)
    assert audit_error.__cause__ is backend_error
    assert attempted_event_types(storage) == (
        AuditEventType.START,
        AuditEventType.TOOL_CALL,
        AuditEventType.ERROR,
    )


def test_validation_and_audit_failures_are_jointly_observable() -> None:
    """Pydantic and audit causes should survive behind the domain exception."""

    provider = FakeMarketingProvider([generation_result("not-json")])
    audit_logger, storage, backend_error = failing_audit_logger(AuditEventType.ERROR)
    agent = MarketingAgent(provider, audit_logger)

    with pytest.raises(MarketingAgentValidationError) as captured:
        run_agent(agent, "marketing-validation-audit-error")

    combined = captured.value.__cause__
    assert isinstance(combined, ExceptionGroup)
    assert any(isinstance(error, ValidationError) for error in combined.exceptions)
    audit_errors = [
        error for error in combined.exceptions if isinstance(error, AuditError)
    ]
    assert len(audit_errors) == 1
    assert audit_errors[0].__cause__ is backend_error
    assert attempted_event_types(storage)[-1] is AuditEventType.ERROR
    assert attempted_event_types(storage).count(AuditEventType.ERROR) == 1


def test_terminal_validation_error_survives_finish_audit_failure() -> None:
    """A failed finish write must retain validation and audit evidence."""

    provider = FakeMarketingProvider(
        [generation_result("not-json"), generation_result("still-not-json")]
    )
    audit_logger, storage, backend_error = failing_audit_logger(AuditEventType.FINISH)
    agent = MarketingAgent(provider, audit_logger)

    with pytest.raises(MarketingAgentValidationError) as captured:
        run_agent(agent, "marketing-finish-audit-error")

    combined = captured.value.__cause__
    assert isinstance(combined, ExceptionGroup)
    assert any(isinstance(error, ValidationError) for error in combined.exceptions)
    audit_errors = [
        error for error in combined.exceptions if isinstance(error, AuditError)
    ]
    assert len(audit_errors) == 1
    assert audit_errors[0].__cause__ is backend_error
    assert attempted_event_types(storage).count(AuditEventType.FINISH) == 1
