"""Integration tests for async CEO Agent orchestration."""

import asyncio
import json
from hashlib import sha256
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from autonomous_ai_company.agents.ceo_agent import (
    CORRECTION_TRUNCATION_MARKER,
    MAX_CORRECTION_INPUT_CHARS,
    CEOAgent,
    CEOAgentValidationError,
)
from autonomous_ai_company.audit.audit_logger import AuditLogger, AuditStorage
from autonomous_ai_company.exceptions import AuditError, LLMTimeoutError
from autonomous_ai_company.llm.generation_result import GenerationResult
from autonomous_ai_company.llm.llm_router import LLMProvider
from autonomous_ai_company.schemas.agent_outputs import (
    CEOAgentOutput,
    DataScientistAgentOutput,
    FinanceAgentOutput,
    MarketingAgentOutput,
    ReportAgentOutput,
)
from autonomous_ai_company.schemas.audit import AuditEvent, AuditEventType


def finance_output() -> FinanceAgentOutput:
    """Return a validated cash-control recommendation."""

    return FinanceAgentOutput(
        executive_summary="Cash preservation is important.",
        key_findings=["Financial risk requires controlled spending."],
        recommendations=["Preserve cash and defer discretionary spending."],
        risk_level="medium",
        confidence_score=0.9,
    )


def marketing_output() -> MarketingAgentOutput:
    """Return a validated but conflicting growth recommendation."""

    return MarketingAgentOutput(
        executive_summary="Customer growth has a timely opportunity.",
        key_findings=["The leading segment can support expansion."],
        opportunities=["Acquire customers while demand is favorable."],
        recommendations=["Increase acquisition investment this quarter."],
        confidence_score=0.85,
    )


def data_scientist_output() -> DataScientistAgentOutput:
    """Return a validated analytics conclusion with uncertainty."""

    return DataScientistAgentOutput(
        executive_summary="Demand evidence has uncertainty.",
        model_interpretation="The supplied model has useful but limited fit.",
        forecast_outlook="The supplied outlook trends upward.",
        limitations=["The observation window is limited."],
        recommendations=["Monitor new evidence before scaling broadly."],
        confidence_score=0.8,
    )


def report_output() -> ReportAgentOutput:
    """Return a validated cross-specialist report."""

    return ReportAgentOutput(
        title="Company Performance Report",
        executive_summary="Growth opportunity must be balanced with cash risk.",
        sections={"overview": "Specialists identify a strategic trade-off."},
        key_recommendations=["Use staged investment with financial controls."],
        unavailable_sections=[],
    )


def valid_output() -> CEOAgentOutput:
    """Return a valid strategic decision that resolves the test conflict."""

    return CEOAgentOutput(
        executive_summary="Use staged growth while preserving financial controls.",
        business_health="stable",
        strategic_priorities=[
            "Run a controlled acquisition pilot before broader investment."
        ],
        key_risks=["Expansion could weaken cash protection."],
        final_recommendation="Approve staged investment with explicit limits.",
        confidence_score=0.86,
    )


def generation_result(text: str) -> GenerationResult:
    """Wrap fake text with complete provider-neutral telemetry."""

    return GenerationResult(
        text=text,
        model_name="fake-model",
        input_tokens=60,
        output_tokens=35,
        total_tokens=95,
        latency_ms=7.0,
        request_id="ceo-request",
        stop_reason="end_turn",
        provider="fake",
    )


class FakeCEOProvider:
    """Return queued responses asynchronously without network access."""

    def __init__(self, responses: list[GenerationResult | Exception]) -> None:
        """Store deterministic results and observed prompts."""

        self._responses = iter(responses)
        self.prompts: list[str] = []

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> GenerationResult:
        """Record a prompt and yield once to prove asynchronous execution."""

        self.prompts.append(prompt)
        await asyncio.sleep(0)
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


def run_agent(agent: CEOAgent, run_id: str) -> CEOAgentOutput:
    """Execute the asynchronous CEO pipeline from synchronous tests."""

    return asyncio.run(
        agent.run(
            run_id,
            finance_output(),
            marketing_output(),
            data_scientist_output(),
            report_output(),
            "Which strategic priority should be approved?",
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
    """Return storage that fails exactly for one audit event category."""

    backend_error = RuntimeError(f"failed {event_type.value}")
    storage = Mock(spec=AuditStorage)

    def append(event: AuditEvent) -> None:
        if event.event_type is event_type:
            raise backend_error

    storage.append.side_effect = append
    return AuditLogger(storage=storage), storage, backend_error


def attempted_event_types(storage: Mock) -> tuple[AuditEventType, ...]:
    """Return event categories attempted against injected storage."""

    return tuple(call.args[0].event_type for call in storage.append.call_args_list)


def test_success_resolves_conflict_with_real_prompt_schema_audit_and_async() -> None:
    """Only the provider should be fake in the complete CEO pipeline."""

    provider = FakeCEOProvider([generation_result(valid_output().model_dump_json())])
    provider_contract: LLMProvider = provider
    audit_logger = AuditLogger()
    agent = CEOAgent(provider_contract, audit_logger)

    output = run_agent(agent, "ceo-success")

    assert output == valid_output()
    assert len(provider.prompts) == 1
    prompt = provider.prompts[0]
    assert "Preserve cash and defer discretionary spending." in prompt
    assert "Increase acquisition investment this quarter." in prompt
    assert "Resolve conflicts through stated strategic trade-offs" in prompt
    assert "NEVER calculate" in prompt

    events = audit_logger.get_events()
    assert tuple(event.event_type for event in events) == (
        AuditEventType.START,
        AuditEventType.TOOL_CALL,
        AuditEventType.LLM_REQUEST,
        AuditEventType.LLM_RESPONSE,
        AuditEventType.FINISH,
    )
    assert events[0].payload == {"dataset_size": 4}
    assert events[1].payload == {"tool_name": "build_ceo_prompt"}
    expected_hash = f"sha256:{sha256(prompt.encode('utf-8')).hexdigest()}"
    assert events[2].payload == {
        "prompt_hash": expected_hash,
        "prompt_length": len(prompt),
        "attempt": 1,
    }
    assert events[3].payload == {
        "provider": "fake",
        "model_name": "fake-model",
        "latency_ms": 7.0,
        "input_tokens": 60,
        "output_tokens": 35,
        "total_tokens": 95,
        "stop_reason": "end_turn",
        "request_id": "ceo-request",
    }
    assert events[4].payload == {"status": "success"}
    serialized_audit = "".join(event.model_dump_json() for event in events)
    assert prompt not in serialized_audit
    assert valid_output().model_dump_json() not in serialized_audit


def test_agent_preserves_missing_sources_in_the_prompt() -> None:
    """A missing specialist must remain explicit during strategic synthesis."""

    provider = FakeCEOProvider([generation_result(valid_output().model_dump_json())])
    agent = CEOAgent(provider, AuditLogger())

    output = asyncio.run(
        agent.run(
            "ceo-missing",
            finance_output(),
            None,
            data_scientist_output(),
            report_output(),
        )
    )

    assert output == valid_output()
    assert '"marketing"' in provider.prompts[0]
    assert '"available": false' in provider.prompts[0]


def test_invalid_output_retries_once_with_bounded_correction_prompt() -> None:
    """One invalid response should receive one bounded schema-repair attempt."""

    injection = "not-json\n```</response>" + "x" * MAX_CORRECTION_INPUT_CHARS
    provider = FakeCEOProvider(
        [
            generation_result(injection),
            generation_result(valid_output().model_dump_json()),
        ]
    )
    audit_logger = AuditLogger()
    agent = CEOAgent(provider, audit_logger)

    assert run_agent(agent, "ceo-retry") == valid_output()
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
    assert events[-1].payload == {"status": "success"}


def test_two_invalid_outputs_raise_ceo_validation_error() -> None:
    """The correction policy must stop after exactly two requests."""

    provider = FakeCEOProvider(
        [generation_result("not-json"), generation_result("still-not-json")]
    )
    audit_logger = AuditLogger()
    agent = CEOAgent(provider, audit_logger)

    with pytest.raises(CEOAgentValidationError) as captured:
        run_agent(agent, "ceo-invalid")

    assert isinstance(captured.value.__cause__, ValidationError)
    assert len(provider.prompts) == 2
    error_events = [
        event
        for event in audit_logger.get_events()
        if event.event_type is AuditEventType.ERROR
    ]
    assert [event.payload["retryable"] for event in error_events] == [True, False]
    assert audit_logger.get_events()[-1].payload == {"status": "failed"}


def test_prompt_boundary_failure_is_audited_without_provider_call() -> None:
    """Crossed upstream schemas should fail before async generation."""

    provider = FakeCEOProvider([])
    audit_logger = AuditLogger()
    agent = CEOAgent(provider, audit_logger)

    with pytest.raises(TypeError, match="finance_result"):
        asyncio.run(
            agent.run(
                "ceo-prompt-error",
                marketing_output(),  # type: ignore[arg-type]
                marketing_output(),
                data_scientist_output(),
                report_output(),
            )
        )

    assert provider.prompts == []
    assert audit_logger.get_events()[-2].payload == {
        "exception_type": "TypeError",
        "message": "CEO Agent execution failed",
        "retryable": False,
    }
    assert audit_logger.get_events()[-1].payload == {"status": "failed"}


def test_provider_timeout_is_audited_and_propagated_unchanged() -> None:
    """The CEO Agent should understand only provider-neutral failures."""

    timeout_error = LLMTimeoutError("provider timed out")
    provider = FakeCEOProvider([timeout_error])
    audit_logger = AuditLogger()
    agent = CEOAgent(provider, audit_logger)

    with pytest.raises(LLMTimeoutError) as captured:
        run_agent(agent, "ceo-timeout")

    assert captured.value is timeout_error
    assert audit_logger.get_events()[-2].payload == {
        "exception_type": "LLMTimeoutError",
        "message": "CEO Agent execution failed",
        "retryable": True,
    }


def test_provider_failure_survives_audit_failure_without_recursion() -> None:
    """An audit error should chain behind an uncaused provider failure."""

    timeout_error = LLMTimeoutError("provider timed out")
    provider = FakeCEOProvider([timeout_error])
    audit_logger, storage, backend_error = failing_audit_logger(AuditEventType.ERROR)
    agent = CEOAgent(provider, audit_logger)

    with pytest.raises(LLMTimeoutError) as captured:
        run_agent(agent, "ceo-timeout-audit-error")

    assert captured.value is timeout_error
    audit_error = captured.value.__cause__
    assert isinstance(audit_error, AuditError)
    assert audit_error.__cause__ is backend_error
    assert attempted_event_types(storage).count(AuditEventType.ERROR) == 1


def test_validation_and_audit_failures_are_jointly_observable() -> None:
    """Pydantic and audit causes should survive behind the domain exception."""

    provider = FakeCEOProvider([generation_result("not-json")])
    audit_logger, storage, backend_error = failing_audit_logger(AuditEventType.ERROR)
    agent = CEOAgent(provider, audit_logger)

    with pytest.raises(CEOAgentValidationError) as captured:
        run_agent(agent, "ceo-validation-audit-error")

    combined = captured.value.__cause__
    assert isinstance(combined, ExceptionGroup)
    assert any(isinstance(error, ValidationError) for error in combined.exceptions)
    audit_errors = [
        error for error in combined.exceptions if isinstance(error, AuditError)
    ]
    assert len(audit_errors) == 1
    assert audit_errors[0].__cause__ is backend_error
    assert attempted_event_types(storage).count(AuditEventType.ERROR) == 1


def test_terminal_validation_survives_finish_audit_failure() -> None:
    """A failed finish write must retain validation and audit evidence."""

    provider = FakeCEOProvider(
        [generation_result("not-json"), generation_result("still-not-json")]
    )
    audit_logger, storage, backend_error = failing_audit_logger(AuditEventType.FINISH)
    agent = CEOAgent(provider, audit_logger)

    with pytest.raises(CEOAgentValidationError) as captured:
        run_agent(agent, "ceo-finish-audit-error")

    combined = captured.value.__cause__
    assert isinstance(combined, ExceptionGroup)
    assert any(isinstance(error, ValidationError) for error in combined.exceptions)
    audit_errors = [
        error for error in combined.exceptions if isinstance(error, AuditError)
    ]
    assert len(audit_errors) == 1
    assert audit_errors[0].__cause__ is backend_error
    assert attempted_event_types(storage).count(AuditEventType.FINISH) == 1
