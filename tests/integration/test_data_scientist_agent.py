"""Integration tests for async Data Scientist Agent orchestration."""

import asyncio
import json
from decimal import Decimal
from hashlib import sha256
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from autonomous_ai_company.agents.data_scientist_agent import (
    CORRECTION_TRUNCATION_MARKER,
    MAX_CORRECTION_INPUT_CHARS,
    DataScientistAgent,
    DataScientistAgentValidationError,
)
from autonomous_ai_company.audit.audit_logger import AuditLogger, AuditStorage
from autonomous_ai_company.exceptions import (
    AuditError,
    InvalidDatasetError,
    LLMTimeoutError,
)
from autonomous_ai_company.llm.generation_result import GenerationResult
from autonomous_ai_company.llm.llm_router import LLMProvider
from autonomous_ai_company.schemas.agent_outputs import DataScientistAgentOutput
from autonomous_ai_company.schemas.audit import AuditEvent, AuditEventType
from autonomous_ai_company.tools.data_scientist_tools import TimeSeries


SERIES: TimeSeries = (
    Decimal("10"),
    Decimal("20"),
    Decimal("10"),
    Decimal("20"),
    Decimal("10"),
    Decimal("20"),
)
BUSINESS_CONTEXT = "Weekly demand observations at equal intervals."


def valid_output() -> DataScientistAgentOutput:
    """Return one valid deterministic analytical interpretation."""

    return DataScientistAgentOutput(
        executive_summary="Demand shows seasonal variation and modest growth.",
        model_interpretation="Provided model metrics indicate useful fit.",
        forecast_outlook="The supplied forecast continues the upward trend.",
        limitations=["The time series contains six observations."],
        recommendations=["Monitor future observations against the interval."],
        confidence_score=0.88,
    )


def generation_result(text: str) -> GenerationResult:
    """Wrap fake text in a complete provider-neutral generation result."""

    return GenerationResult(
        text=text,
        model_name="fake-model",
        input_tokens=40,
        output_tokens=25,
        total_tokens=65,
        latency_ms=5.0,
        request_id="data-science-request",
        stop_reason="end_turn",
        provider="fake",
    )


class FakeDataScienceProvider:
    """Return queued results asynchronously without network communication."""

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
        """Record one prompt and yield to prove genuine async execution."""

        self.prompts.append(prompt)
        await asyncio.sleep(0)
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


def run_agent(
    agent: DataScientistAgent,
    run_id: str,
    dataset: TimeSeries = SERIES,
) -> DataScientistAgentOutput:
    """Execute the async agent with real tools, prompt, schema, and audit."""

    return asyncio.run(
        agent.run(
            run_id,
            dataset,
            BUSINESS_CONTEXT,
            "What should leadership monitor?",
            feature_importances={
                "price": Decimal("0.75"),
                "season": Decimal("0.25"),
            },
            model_metrics={
                "accuracy": Decimal("0.90"),
                "precision": Decimal("0.85"),
                "recall": Decimal("0.80"),
                "f1_score": Decimal("0.825"),
                "mae": Decimal("1.25"),
                "mse": Decimal("2.25"),
                "rmse": Decimal("1.50"),
                "r2": Decimal("0.80"),
            },
        )
    )


def extract_correction_response(prompt: str) -> str:
    """Decode bounded invalid output from the correction prompt."""

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


def test_success_uses_real_statistics_prompt_schema_async_provider_and_audit() -> None:
    """Only the provider should be fake in the complete analytics pipeline."""

    provider = FakeDataScienceProvider(
        [generation_result(valid_output().model_dump_json())]
    )
    provider_contract: LLMProvider = provider
    audit_logger = AuditLogger()
    agent = DataScientistAgent(provider_contract, audit_logger)

    output = run_agent(agent, "data-science-success")

    assert output == valid_output()
    assert len(provider.prompts) == 1
    prompt = provider.prompts[0]
    assert '"slope": "0.8571"' in prompt
    assert '"correlation": "1.0000"' in prompt
    assert '"f1_score": "0.8250"' in prompt
    assert '"mse": "2.2500"' in prompt
    assert '"rmse": "1.5000"' in prompt
    assert '"percentage": "75.0000"' in prompt
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
    assert events[0].payload == {"dataset_size": 6}
    assert events[1].payload == {"tool_name": "calculate_data_science_metrics"}
    assert events[2].payload == {"tool_name": "build_data_scientist_prompt"}
    expected_hash = f"sha256:{sha256(prompt.encode('utf-8')).hexdigest()}"
    assert events[3].payload == {
        "prompt_hash": expected_hash,
        "prompt_length": len(prompt),
        "attempt": 1,
    }
    assert events[4].payload == {
        "provider": "fake",
        "model_name": "fake-model",
        "latency_ms": 5.0,
        "input_tokens": 40,
        "output_tokens": 25,
        "total_tokens": 65,
        "stop_reason": "end_turn",
        "request_id": "data-science-request",
    }
    assert events[5].payload == {"status": "success"}
    serialized_audit = "".join(event.model_dump_json() for event in events)
    assert prompt not in serialized_audit
    assert valid_output().model_dump_json() not in serialized_audit


def test_invalid_output_retries_once_with_bounded_correction_prompt() -> None:
    """One invalid response should receive one safe schema-repair attempt."""

    injection = "not-json\n```</response>" + "x" * MAX_CORRECTION_INPUT_CHARS
    provider = FakeDataScienceProvider(
        [
            generation_result(injection),
            generation_result(valid_output().model_dump_json()),
        ]
    )
    audit_logger = AuditLogger()
    agent = DataScientistAgent(provider, audit_logger)

    assert run_agent(agent, "data-science-retry") == valid_output()
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
        "message": "Data Scientist Agent output validation failed",
        "retryable": True,
    }
    assert events[-1].payload == {"status": "success"}


def test_two_invalid_outputs_raise_domain_validation_error() -> None:
    """The correction policy must stop after exactly two provider requests."""

    provider = FakeDataScienceProvider(
        [generation_result("not-json"), generation_result("still-not-json")]
    )
    audit_logger = AuditLogger()
    agent = DataScientistAgent(provider, audit_logger)

    with pytest.raises(DataScientistAgentValidationError) as captured:
        run_agent(agent, "data-science-invalid")

    assert isinstance(captured.value.__cause__, ValidationError)
    assert len(provider.prompts) == 2
    errors = [
        event
        for event in audit_logger.get_events()
        if event.event_type is AuditEventType.ERROR
    ]
    assert [event.payload["retryable"] for event in errors] == [True, False]
    assert audit_logger.get_events()[-1].payload == {"status": "failed"}


def test_invalid_dataset_is_audited_without_provider_or_network_use() -> None:
    """Tool validation should stop execution before the fake provider runs."""

    provider = FakeDataScienceProvider([])
    audit_logger = AuditLogger()
    agent = DataScientistAgent(provider, audit_logger)

    with pytest.raises(InvalidDatasetError, match="at least two"):
        run_agent(agent, "data-science-tool-error", dataset=())

    assert provider.prompts == []
    assert audit_logger.get_events()[-2].payload == {
        "exception_type": "InvalidDatasetError",
        "message": "Data Scientist Agent execution failed",
        "retryable": False,
    }
    assert audit_logger.get_events()[-1].payload == {"status": "failed"}


def test_provider_timeout_is_audited_and_propagated_unchanged() -> None:
    """Only provider-neutral LLM failures should cross the agent boundary."""

    timeout_error = LLMTimeoutError("provider timed out")
    provider = FakeDataScienceProvider([timeout_error])
    audit_logger = AuditLogger()
    agent = DataScientistAgent(provider, audit_logger)

    with pytest.raises(LLMTimeoutError) as captured:
        run_agent(agent, "data-science-timeout")

    assert captured.value is timeout_error
    assert audit_logger.get_events()[-2].payload == {
        "exception_type": "LLMTimeoutError",
        "message": "Data Scientist Agent execution failed",
        "retryable": True,
    }


def test_provider_failure_survives_audit_failure_without_recursion() -> None:
    """An audit error should chain behind an uncaused provider failure."""

    timeout_error = LLMTimeoutError("provider timed out")
    provider = FakeDataScienceProvider([timeout_error])
    audit_logger, storage, backend_error = failing_audit_logger(AuditEventType.ERROR)
    agent = DataScientistAgent(provider, audit_logger)

    with pytest.raises(LLMTimeoutError) as captured:
        run_agent(agent, "data-science-timeout-audit-error")

    assert captured.value is timeout_error
    audit_error = captured.value.__cause__
    assert isinstance(audit_error, AuditError)
    assert audit_error.__cause__ is backend_error
    assert attempted_event_types(storage).count(AuditEventType.ERROR) == 1


def test_tool_and_audit_failures_preserve_both_causes() -> None:
    """Dataset validation and audit failures should both remain observable."""

    provider = FakeDataScienceProvider([])
    audit_logger, storage, backend_error = failing_audit_logger(AuditEventType.ERROR)
    agent = DataScientistAgent(provider, audit_logger)

    with pytest.raises(InvalidDatasetError) as captured:
        run_agent(agent, "data-science-tool-audit-error", dataset=())

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

    provider = FakeDataScienceProvider([generation_result("not-json")])
    audit_logger, storage, backend_error = failing_audit_logger(AuditEventType.ERROR)
    agent = DataScientistAgent(provider, audit_logger)

    with pytest.raises(DataScientistAgentValidationError) as captured:
        run_agent(agent, "data-science-validation-audit-error")

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

    provider = FakeDataScienceProvider(
        [generation_result("not-json"), generation_result("still-not-json")]
    )
    audit_logger, storage, backend_error = failing_audit_logger(AuditEventType.FINISH)
    agent = DataScientistAgent(provider, audit_logger)

    with pytest.raises(DataScientistAgentValidationError) as captured:
        run_agent(agent, "data-science-finish-audit-error")

    combined = captured.value.__cause__
    assert isinstance(combined, ExceptionGroup)
    assert any(isinstance(error, ValidationError) for error in combined.exceptions)
    audit_errors = [
        error for error in combined.exceptions if isinstance(error, AuditError)
    ]
    assert len(audit_errors) == 1
    assert audit_errors[0].__cause__ is backend_error
    assert attempted_event_types(storage).count(AuditEventType.FINISH) == 1
