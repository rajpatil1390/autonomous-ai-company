"""Unit tests for allowlisted, thread-safe audit logging."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from autonomous_ai_company.audit.audit_logger import (
    AuditLogger,
    AuditStorage,
    InMemoryAuditStorage,
)
from autonomous_ai_company.exceptions import AuditError
from autonomous_ai_company.schemas.audit import AuditEvent, AuditEventType


UTC_START = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def incrementing_clock() -> Mock:
    """Return a deterministic clock with one timestamp for each event method."""

    timestamps = [UTC_START + timedelta(seconds=index) for index in range(6)]
    return Mock(side_effect=timestamps)


def test_logger_records_every_event_type_in_order_with_utc_timestamps() -> None:
    """Lifecycle methods should preserve invocation order and validated times."""

    clock = incrementing_clock()
    logger = AuditLogger(clock=clock)

    returned_events = (
        logger.log_start("run-1", "finance_agent"),
        logger.log_tool_call("run-1", "finance_tools"),
        logger.log_llm_request("run-1", "llm_router"),
        logger.log_llm_response("run-1", "llm_router"),
        logger.log_error("run-1", "finance_agent"),
        logger.log_finish("run-1", "finance_agent"),
    )
    stored_events = logger.get_events()

    assert stored_events == returned_events
    assert tuple(event.event_type for event in stored_events) == tuple(AuditEventType)
    assert tuple(event.timestamp for event in stored_events) == tuple(
        UTC_START + timedelta(seconds=index) for index in range(6)
    )
    assert all(event.timestamp.utcoffset() == timedelta(0) for event in stored_events)
    assert all(event.run_id == "run-1" for event in stored_events)
    assert all(event.payload == {} for event in stored_events)


def test_logger_applies_each_event_specific_allowlist() -> None:
    """Each lifecycle category should persist only its approved telemetry."""

    logger = AuditLogger(clock=lambda: UTC_START)

    events = (
        logger.log_start(
            "run-policy",
            "finance_agent",
            payload={"dataset_size": 25, "current_period_rows": 25},
        ),
        logger.log_tool_call(
            "run-policy",
            "finance_tools",
            payload={
                "tool_name": "calculate_kpis",
                "duration_ms": 4.5,
                "success": True,
                "arguments": {"secret": "value"},
            },
        ),
        logger.log_llm_request(
            "run-policy",
            "llm_router",
            payload={
                "provider": "anthropic",
                "model_name": "claude-test",
                "prompt_hash": "sha256:abc",
                "prompt_length": 512,
                "attempt": 1,
                "timeout": 30,
            },
        ),
        logger.log_llm_response(
            "run-policy",
            "llm_router",
            payload={
                "provider": "anthropic",
                "model_name": "claude-test",
                "latency_ms": 125.5,
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
                "stop_reason": "end_turn",
                "request_id": "request-1",
                "attempt": 1,
            },
        ),
        logger.log_error(
            "run-policy",
            "finance_agent",
            payload={
                "exception_type": "LLMTimeoutError",
                "message": "provider timed out",
                "retryable": True,
                "traceback": "sensitive stack",
            },
        ),
        logger.log_finish(
            "run-policy",
            "finance_agent",
            payload={
                "duration_ms": 250.0,
                "status": "success",
                "result": "sensitive result",
            },
        ),
    )

    assert tuple(event.payload for event in events) == (
        {"dataset_size": 25},
        {
            "tool_name": "calculate_kpis",
            "duration_ms": 4.5,
            "success": True,
        },
        {
            "provider": "anthropic",
            "model_name": "claude-test",
            "prompt_hash": "sha256:abc",
            "prompt_length": 512,
            "attempt": 1,
        },
        {
            "provider": "anthropic",
            "model_name": "claude-test",
            "latency_ms": 125.5,
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "stop_reason": "end_turn",
            "request_id": "request-1",
        },
        {
            "exception_type": "LLMTimeoutError",
            "message": "provider timed out",
            "retryable": True,
        },
        {"duration_ms": 250.0, "status": "success"},
    )


def test_unknown_fields_are_excluded_from_persisted_output() -> None:
    """Callers must not expand the audit schema with arbitrary fields."""

    logger = AuditLogger(clock=lambda: UTC_START)

    event = logger.log_start(
        "trusted-run-id",
        "finance_agent",
        payload={
            "run_id": "spoofed-run-id",
            "timestamp": "spoofed-time",
            "component": "spoofed-component",
            "dataset_size": 10,
            "unknown": "discard me",
        },
    )

    assert event.run_id == "trusted-run-id"
    assert event.timestamp == UTC_START
    assert event.component == "finance_agent"
    assert event.payload == {"dataset_size": 10}


def test_llm_request_never_stores_prompts_or_messages() -> None:
    """Raw prompt variants must be excluded even when explicitly supplied."""

    logger = AuditLogger(clock=lambda: UTC_START)
    prompt_content = "confidential customer prompt"

    event = logger.log_llm_request(
        "run-request",
        "llm_router",
        payload={
            "provider": "anthropic",
            "prompt_hash": "sha256:def",
            "prompt_length": len(prompt_content),
            "raw_prompt": prompt_content,
            "system_prompt": "confidential system prompt",
            "user_prompt": "confidential user prompt",
            "messages": [{"role": "user", "content": prompt_content}],
        },
    )
    serialized = event.model_dump_json()

    assert event.payload == {
        "provider": "anthropic",
        "prompt_hash": "sha256:def",
        "prompt_length": len(prompt_content),
    }
    assert "confidential" not in serialized
    assert "messages" not in serialized


def test_llm_response_excludes_text_and_keeps_allowed_telemetry() -> None:
    """Response observability must not persist provider-generated content."""

    logger = AuditLogger(clock=lambda: UTC_START)

    event = logger.log_llm_response(
        "run-response",
        "llm_router",
        payload={
            "provider": "anthropic",
            "model_name": "claude-test",
            "latency_ms": 99.25,
            "input_tokens": 80,
            "output_tokens": 20,
            "total_tokens": 100,
            "stop_reason": "end_turn",
            "request_id": "request-telemetry",
            "raw_response": {"sdk": "object"},
            "generated_text": "private generated answer",
        },
    )

    assert event.payload == {
        "provider": "anthropic",
        "model_name": "claude-test",
        "latency_ms": 99.25,
        "input_tokens": 80,
        "output_tokens": 20,
        "total_tokens": 100,
        "stop_reason": "end_turn",
        "request_id": "request-telemetry",
    }
    assert "private generated answer" not in event.model_dump_json()


def test_unsupported_metadata_is_ignored_by_the_same_allowlist() -> None:
    """Metadata must not provide a side channel around payload policy."""

    logger = AuditLogger(clock=lambda: UTC_START)

    event = logger.log_llm_request(
        "run-metadata",
        "llm_router",
        metadata={
            "provider": "anthropic",
            "model_name": "claude-test",
            "correlation_id": "unsupported",
            "raw_prompt": "must disappear",
        },
    )

    assert event.metadata == {
        "provider": "anthropic",
        "model_name": "claude-test",
    }
    assert "unsupported" not in event.model_dump_json()
    assert "must disappear" not in event.model_dump_json()


def test_allowlist_produces_deterministic_field_order() -> None:
    """Caller dictionary order must not alter serialized audit output."""

    first_logger = AuditLogger(clock=lambda: UTC_START)
    second_logger = AuditLogger(clock=lambda: UTC_START)
    first = first_logger.log_tool_call(
        "run-deterministic",
        "finance_tools",
        payload={"success": True, "tool_name": "calculate_kpis", "duration_ms": 2},
    )
    second = second_logger.log_tool_call(
        "run-deterministic",
        "finance_tools",
        payload={"duration_ms": 2, "tool_name": "calculate_kpis", "success": True},
    )

    assert first.model_dump_json() == second.model_dump_json()
    assert tuple(first.payload) == ("tool_name", "duration_ms", "success")


def test_logger_rejects_non_string_payload_keys() -> None:
    """Payload keys must remain valid JSON object field names."""

    logger = AuditLogger(clock=lambda: UTC_START)

    with pytest.raises(AuditError, match="Failed to record") as captured:
        logger.log_start(
            "run-4",
            "finance_agent",
            payload={1: "invalid"},  # type: ignore[dict-item]
        )

    assert isinstance(captured.value.__cause__, TypeError)


def test_logger_rejects_non_mapping_payload() -> None:
    """An explicitly supplied invalid container must not become an empty event."""

    logger = AuditLogger(clock=lambda: UTC_START)

    with pytest.raises(AuditError, match="Failed to record") as captured:
        logger.log_start(
            "run-4",
            "finance_agent",
            payload=[],  # type: ignore[arg-type]
        )

    assert isinstance(captured.value.__cause__, TypeError)


def test_logger_propagates_validation_errors_for_allowed_values() -> None:
    """Invalid approved values should fail loudly instead of being coerced."""

    logger = AuditLogger(clock=lambda: UTC_START)

    with pytest.raises(AuditError) as captured:
        logger.log_error(
            "run-5",
            "finance_agent",
            payload={"message": object(), "unsupported": object()},
        )

    assert isinstance(captured.value.__cause__, ValidationError)


def test_logger_uses_injected_storage_interface() -> None:
    """AuditLogger should depend on storage behavior rather than memory details."""

    storage = Mock(spec=AuditStorage)
    storage.snapshot.return_value = ()
    logger = AuditLogger(storage=storage, clock=lambda: UTC_START)

    event = logger.log_finish("run-6", "finance_agent")

    storage.append.assert_called_once_with(event)
    assert logger.get_events() == ()
    storage.snapshot.assert_called_once_with()


def test_logger_translates_storage_failures_with_chained_causes() -> None:
    """Storage drivers must not leak through the audit application boundary."""

    append_error = RuntimeError("append failed")
    snapshot_error = RuntimeError("snapshot failed")
    storage = Mock(spec=AuditStorage)
    storage.append.side_effect = append_error
    storage.snapshot.side_effect = snapshot_error
    logger = AuditLogger(storage=storage, clock=lambda: UTC_START)

    with pytest.raises(AuditError, match="Failed to record") as append_failure:
        logger.log_start("run-storage", "finance_agent")
    with pytest.raises(AuditError, match="Failed to read") as read_failure:
        logger.get_events()

    assert append_failure.value.__cause__ is append_error
    assert read_failure.value.__cause__ is snapshot_error
    storage.append.assert_called_once()
    storage.snapshot.assert_called_once()


def test_in_memory_storage_returns_immutable_snapshot() -> None:
    """Callers should receive a copy rather than mutable internal storage."""

    storage = InMemoryAuditStorage()
    event = AuditEvent(
        run_id="run-7",
        timestamp=UTC_START,
        event_type=AuditEventType.START,
        component="finance_agent",
        payload={},
    )

    storage.append(event)
    snapshot = storage.snapshot()

    assert snapshot == (event,)
    assert isinstance(snapshot, tuple)


def test_snapshot_exposes_no_mutable_nested_references() -> None:
    """Allowlisted nested values must retain deep immutability guarantees."""

    logger = AuditLogger(clock=lambda: UTC_START)
    original_payload = {
        "tool_name": {"name": "calculate_kpis"},
        "duration_ms": [1, 2],
        "success": {"verified", "complete"},
    }
    logger.log_tool_call(
        "run-snapshot",
        "finance_tools",
        payload=original_payload,
    )
    snapshot = logger.get_events()

    with pytest.raises(TypeError):
        snapshot[0] = snapshot[0]  # type: ignore[index]
    with pytest.raises(TypeError):
        snapshot[0].payload["tool_name"]["name"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        snapshot[0].payload["duration_ms"][0] = 99  # type: ignore[index]
    with pytest.raises(AttributeError):
        snapshot[0].payload["success"].add("changed")  # type: ignore[union-attr]

    original_payload["tool_name"]["name"] = "caller-mutated"  # type: ignore[index]
    original_payload["duration_ms"].append(3)  # type: ignore[union-attr]
    original_payload["success"].add("caller-mutated")  # type: ignore[union-attr]

    stored = logger.get_events()[0]
    assert stored.payload["tool_name"] == {"name": "calculate_kpis"}
    assert stored.payload["duration_ms"] == (1, 2)
    assert stored.payload["success"] == frozenset({"verified", "complete"})


def test_logger_is_thread_safe_without_losing_events() -> None:
    """Concurrent writers should produce complete validated event storage."""

    logger = AuditLogger()
    event_count = 200

    def record(index: int) -> AuditEvent:
        return logger.log_tool_call(
            "run-threaded",
            "finance_tools",
            payload={"tool_name": f"tool-{index}", "success": True},
        )

    with ThreadPoolExecutor(max_workers=16) as executor:
        returned_events = tuple(executor.map(record, range(event_count)))

    stored_events = logger.get_events()
    assert len(stored_events) == event_count
    assert len({event.payload["tool_name"] for event in stored_events}) == event_count
    assert {id(event) for event in stored_events} == {
        id(event) for event in returned_events
    }
    assert all(event.timestamp.utcoffset() == timedelta(0) for event in stored_events)
