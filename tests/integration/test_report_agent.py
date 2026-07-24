"""Integration tests for async Report Agent orchestration."""

import asyncio
import json
from hashlib import sha256
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from autonomous_ai_company.agents.report_agent import (
    CORRECTION_TRUNCATION_MARKER,
    MAX_CORRECTION_INPUT_CHARS,
    ReportAgent,
    ReportAgentValidationError,
)
from autonomous_ai_company.audit.audit_logger import AuditLogger, AuditStorage
from autonomous_ai_company.exceptions import AuditError, LLMTimeoutError
from autonomous_ai_company.llm.generation_result import GenerationResult
from autonomous_ai_company.llm.llm_router import LLMProvider
from autonomous_ai_company.schemas.agent_outputs import (
    DataScientistAgentOutput,
    FinanceAgentOutput,
    MarketingAgentOutput,
    ReportAgentOutput,
)
from autonomous_ai_company.schemas.audit import AuditEvent, AuditEventType


def finance_output() -> FinanceAgentOutput:
    """Return one validated Finance Agent result."""

    return FinanceAgentOutput(
        executive_summary="Financial performance is stable.",
        key_findings=["Revenue supports current operations."],
        recommendations=["Maintain cost controls."],
        risk_level="low",
        confidence_score=0.9,
    )


def marketing_output() -> MarketingAgentOutput:
    """Return one validated Marketing Agent result."""

    return MarketingAgentOutput(
        executive_summary="Retention offers a growth opportunity.",
        key_findings=["Enterprise is the leading segment."],
        opportunities=["Develop retention campaigns."],
        recommendations=["Prioritize retained customers."],
        confidence_score=0.85,
    )


def data_scientist_output() -> DataScientistAgentOutput:
    """Return one validated Data Scientist Agent result."""

    return DataScientistAgentOutput(
        executive_summary="Demand has a recurring pattern.",
        model_interpretation="Provided metrics indicate useful fit.",
        forecast_outlook="The supplied forecast trends upward.",
        limitations=["The observation window is limited."],
        recommendations=["Monitor forecast error."],
        confidence_score=0.8,
    )


def valid_output(
    unavailable_sections: list[str] | None = None,
) -> ReportAgentOutput:
    """Return one valid deterministic report contract."""

    return ReportAgentOutput(
        title="Company Performance Report",
        executive_summary="Performance is stable with focused opportunities.",
        sections={
            "finance": "Financial performance remains stable.",
            "marketing": "Retention presents a growth opportunity.",
            "analytics": "Demand evidence shows a recurring pattern.",
        },
        key_recommendations=["Maintain controls and monitor demand."],
        unavailable_sections=unavailable_sections or [],
    )


def generation_result(text: str) -> GenerationResult:
    """Wrap fake text with complete provider-neutral telemetry."""

    return GenerationResult(
        text=text,
        model_name="fake-model",
        input_tokens=50,
        output_tokens=30,
        total_tokens=80,
        latency_ms=6.0,
        request_id="report-request",
        stop_reason="end_turn",
        provider="fake",
    )


class FakeReportProvider:
    """Return queued responses asynchronously without any network access."""

    def __init__(self, responses: list[GenerationResult | Exception]) -> None:
        """Store deterministic responses and observed prompts."""

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


def run_agent(
    agent: ReportAgent,
    run_id: str,
    finance_result: FinanceAgentOutput | None = None,
    marketing_result: MarketingAgentOutput | None = None,
    data_scientist_result: DataScientistAgentOutput | None = None,
) -> ReportAgentOutput:
    """Execute the asynchronous report pipeline from synchronous tests."""

    return asyncio.run(
        agent.run(
            run_id,
            finance_output() if finance_result is None else finance_result,
            marketing_output() if marketing_result is None else marketing_result,
            (
                data_scientist_output()
                if data_scientist_result is None
                else data_scientist_result
            ),
            "Prioritize the most actionable findings.",
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


def test_success_uses_real_prompt_schema_async_provider_and_audit() -> None:
    """Only the provider should be fake in the complete report pipeline."""

    provider = FakeReportProvider([generation_result(valid_output().model_dump_json())])
    provider_contract: LLMProvider = provider
    audit_logger = AuditLogger()
    agent = ReportAgent(provider_contract, audit_logger)

    output = run_agent(agent, "report-success")

    assert output == valid_output()
    assert len(provider.prompts) == 1
    prompt = provider.prompts[0]
    assert "Financial performance is stable." in prompt
    assert "Retention offers a growth opportunity." in prompt
    assert "Demand has a recurring pattern." in prompt
    assert "NEVER calculate" in prompt

    events = audit_logger.get_events()
    assert tuple(event.event_type for event in events) == (
        AuditEventType.START,
        AuditEventType.TOOL_CALL,
        AuditEventType.LLM_REQUEST,
        AuditEventType.LLM_RESPONSE,
        AuditEventType.FINISH,
    )
    assert events[0].payload == {"dataset_size": 3}
    assert events[1].payload == {"tool_name": "build_report_prompt"}
    expected_hash = f"sha256:{sha256(prompt.encode('utf-8')).hexdigest()}"
    assert events[2].payload == {
        "prompt_hash": expected_hash,
        "prompt_length": len(prompt),
        "attempt": 1,
    }
    assert events[3].payload == {
        "provider": "fake",
        "model_name": "fake-model",
        "latency_ms": 6.0,
        "input_tokens": 50,
        "output_tokens": 30,
        "total_tokens": 80,
        "stop_reason": "end_turn",
        "request_id": "report-request",
    }
    assert events[4].payload == {"status": "success"}
    serialized_audit = "".join(event.model_dump_json() for event in events)
    assert prompt not in serialized_audit
    assert valid_output().model_dump_json() not in serialized_audit


def test_agent_preserves_explicit_missing_sections() -> None:
    """Missing specialist inputs should flow through prompt and typed output."""

    expected = valid_output(["marketing"])
    provider = FakeReportProvider([generation_result(expected.model_dump_json())])
    agent = ReportAgent(provider, AuditLogger())

    output = asyncio.run(
        agent.run(
            "report-missing",
            finance_output(),
            None,
            data_scientist_output(),
        )
    )

    assert output == expected
    assert '"marketing"' in provider.prompts[0]
    assert '"available": false' in provider.prompts[0]


def test_invalid_output_retries_once_with_bounded_correction_prompt() -> None:
    """One invalid response should receive one bounded schema-repair attempt."""

    injection = "not-json\n```</response>" + "x" * MAX_CORRECTION_INPUT_CHARS
    provider = FakeReportProvider(
        [
            generation_result(injection),
            generation_result(valid_output().model_dump_json()),
        ]
    )
    audit_logger = AuditLogger()
    agent = ReportAgent(provider, audit_logger)

    assert run_agent(agent, "report-retry") == valid_output()
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


def test_two_invalid_outputs_raise_report_validation_error() -> None:
    """The correction policy must stop after exactly two requests."""

    provider = FakeReportProvider(
        [generation_result("not-json"), generation_result("still-not-json")]
    )
    audit_logger = AuditLogger()
    agent = ReportAgent(provider, audit_logger)

    with pytest.raises(ReportAgentValidationError) as captured:
        run_agent(agent, "report-invalid")

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
    """Crossed specialist schemas should fail before async generation."""

    provider = FakeReportProvider([])
    audit_logger = AuditLogger()
    agent = ReportAgent(provider, audit_logger)

    with pytest.raises(TypeError, match="finance_result"):
        asyncio.run(
            agent.run(
                "report-prompt-error",
                marketing_output(),  # type: ignore[arg-type]
                marketing_output(),
                data_scientist_output(),
            )
        )

    assert provider.prompts == []
    assert audit_logger.get_events()[-2].payload == {
        "exception_type": "TypeError",
        "message": "Report Agent execution failed",
        "retryable": False,
    }
    assert audit_logger.get_events()[-1].payload == {"status": "failed"}


def test_provider_timeout_is_audited_and_propagated_unchanged() -> None:
    """The Report Agent should understand only provider-neutral failures."""

    timeout_error = LLMTimeoutError("provider timed out")
    provider = FakeReportProvider([timeout_error])
    audit_logger = AuditLogger()
    agent = ReportAgent(provider, audit_logger)

    with pytest.raises(LLMTimeoutError) as captured:
        run_agent(agent, "report-timeout")

    assert captured.value is timeout_error
    assert audit_logger.get_events()[-2].payload == {
        "exception_type": "LLMTimeoutError",
        "message": "Report Agent execution failed",
        "retryable": True,
    }


def test_provider_failure_survives_audit_failure_without_recursion() -> None:
    """An audit error should chain behind an uncaused provider failure."""

    timeout_error = LLMTimeoutError("provider timed out")
    provider = FakeReportProvider([timeout_error])
    audit_logger, storage, backend_error = failing_audit_logger(AuditEventType.ERROR)
    agent = ReportAgent(provider, audit_logger)

    with pytest.raises(LLMTimeoutError) as captured:
        run_agent(agent, "report-timeout-audit-error")

    assert captured.value is timeout_error
    audit_error = captured.value.__cause__
    assert isinstance(audit_error, AuditError)
    assert audit_error.__cause__ is backend_error
    assert attempted_event_types(storage).count(AuditEventType.ERROR) == 1


def test_validation_and_audit_failures_are_jointly_observable() -> None:
    """Pydantic and audit causes should survive behind the domain exception."""

    provider = FakeReportProvider([generation_result("not-json")])
    audit_logger, storage, backend_error = failing_audit_logger(AuditEventType.ERROR)
    agent = ReportAgent(provider, audit_logger)

    with pytest.raises(ReportAgentValidationError) as captured:
        run_agent(agent, "report-validation-audit-error")

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

    provider = FakeReportProvider(
        [generation_result("not-json"), generation_result("still-not-json")]
    )
    audit_logger, storage, backend_error = failing_audit_logger(AuditEventType.FINISH)
    agent = ReportAgent(provider, audit_logger)

    with pytest.raises(ReportAgentValidationError) as captured:
        run_agent(agent, "report-finish-audit-error")

    combined = captured.value.__cause__
    assert isinstance(combined, ExceptionGroup)
    assert any(isinstance(error, ValidationError) for error in combined.exceptions)
    audit_errors = [
        error for error in combined.exceptions if isinstance(error, AuditError)
    ]
    assert len(audit_errors) == 1
    assert audit_errors[0].__cause__ is backend_error
    assert attempted_event_types(storage).count(AuditEventType.FINISH) == 1
