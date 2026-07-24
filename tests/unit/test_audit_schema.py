"""Unit tests for validated provider-independent audit events."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from autonomous_ai_company.schemas.audit import AuditEvent, AuditEventType


UTC_TIMESTAMP = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def valid_event_data() -> dict[str, object]:
    """Return isolated valid input for schema tests."""

    return {
        "run_id": "run-123",
        "timestamp": UTC_TIMESTAMP,
        "event_type": AuditEventType.START,
        "component": "finance_agent",
        "payload": {"attempt": 1, "nested": {"ready": True}},
        "metadata": {"correlation_id": "correlation-456"},
    }


def test_audit_event_accepts_valid_data_and_serializes_to_json() -> None:
    """A validated event should retain every field in JSON-compatible form."""

    event = AuditEvent.model_validate(valid_event_data())
    serialized = json.loads(event.model_dump_json())

    assert serialized == {
        "run_id": "run-123",
        "timestamp": "2026-01-02T03:04:05Z",
        "event_type": "start",
        "component": "finance_agent",
        "payload": {"attempt": 1, "nested": {"ready": True}},
        "metadata": {"correlation_id": "correlation-456"},
    }


@pytest.mark.parametrize("event_type", tuple(AuditEventType))
def test_schema_accepts_every_controlled_event_type(
    event_type: AuditEventType,
) -> None:
    """Every logger lifecycle method should have a valid schema category."""

    data = valid_event_data()
    data["event_type"] = event_type

    assert AuditEvent.model_validate(data).event_type is event_type


@pytest.mark.parametrize(
    "required_field",
    ("run_id", "timestamp", "event_type", "component", "payload"),
)
def test_audit_event_rejects_missing_required_fields(required_field: str) -> None:
    """Incomplete audit envelopes should never reach storage."""

    data = valid_event_data()
    data.pop(required_field)

    with pytest.raises(ValidationError):
        AuditEvent.model_validate(data)


@pytest.mark.parametrize("field_name", ("run_id", "component"))
def test_audit_event_rejects_blank_identifiers(field_name: str) -> None:
    """Run and component identifiers must carry meaningful text."""

    data = valid_event_data()
    data[field_name] = "   "

    with pytest.raises(ValidationError):
        AuditEvent.model_validate(data)


def test_audit_event_rejects_naive_timestamp() -> None:
    """Naive timestamps cannot support globally correct ordering."""

    data = valid_event_data()
    data["timestamp"] = datetime(2026, 1, 2, 3, 4, 5)

    with pytest.raises(ValidationError, match="timezone-aware"):
        AuditEvent.model_validate(data)


def test_audit_event_rejects_non_utc_timestamp() -> None:
    """Aware timestamps with non-zero offsets must not enter the audit trail."""

    data = valid_event_data()
    data["timestamp"] = datetime(
        2026,
        1,
        2,
        8,
        34,
        5,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )

    with pytest.raises(ValidationError, match="must use UTC"):
        AuditEvent.model_validate(data)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("event_type", "unknown"),
        ("payload", {"bad": object()}),
        ("metadata", {"bad": object()}),
    ),
)
def test_audit_event_rejects_invalid_field_data(
    field_name: str,
    invalid_value: object,
) -> None:
    """Enum and JSON fields should reject values outside their contracts."""

    data = valid_event_data()
    data[field_name] = invalid_value

    with pytest.raises(ValidationError):
        AuditEvent.model_validate(data)


@pytest.mark.parametrize("field_name", ("payload", "metadata"))
@pytest.mark.parametrize(
    "invalid_value",
    (
        float("nan"),
        {"nested": [float("inf")]},
    ),
)
def test_audit_event_rejects_non_finite_nested_numbers(
    field_name: str,
    invalid_value: object,
) -> None:
    """All nested numeric values must remain portable strict JSON."""

    data = valid_event_data()
    data[field_name] = {"value": invalid_value}

    with pytest.raises(ValidationError, match="finite numbers"):
        AuditEvent.model_validate(data)


def test_audit_event_allows_omitted_metadata() -> None:
    """Metadata is optional while the core event envelope remains required."""

    data = valid_event_data()
    data.pop("metadata")

    event = AuditEvent.model_validate(data)

    assert event.metadata is None
    assert json.loads(event.model_dump_json())["metadata"] is None


def test_audit_event_rejects_extra_fields_and_is_immutable() -> None:
    """Audit history must reject schema drift and post-validation mutation."""

    data = valid_event_data()
    data["unexpected"] = "value"

    with pytest.raises(ValidationError):
        AuditEvent.model_validate(data)

    event = AuditEvent.model_validate(valid_event_data())
    with pytest.raises(ValidationError):
        event.run_id = "changed"


def test_audit_event_deep_freezes_every_nested_container() -> None:
    """Mappings, lists, tuples, sets, and metadata must reject mutation."""

    event = AuditEvent(
        run_id="run-frozen",
        timestamp=UTC_TIMESTAMP,
        event_type=AuditEventType.TOOL_CALL,
        component="finance_tools",
        payload={
            "nested": {"status": "original"},
            "list": [1, 2],
            "tuple": ("a", "b"),
            "set": {"beta", "alpha"},
        },
        metadata={"tags": ["finance", "audit"]},
    )

    with pytest.raises(TypeError):
        event.payload["new"] = "value"  # type: ignore[index]
    with pytest.raises(TypeError):
        event.payload["nested"]["status"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        event.payload["list"][0] = 99  # type: ignore[index]
    with pytest.raises(TypeError):
        event.payload["tuple"][0] = "changed"  # type: ignore[index]
    with pytest.raises(AttributeError):
        event.payload["set"].add("gamma")  # type: ignore[union-attr]
    with pytest.raises(TypeError):
        event.metadata["tags"][0] = "changed"  # type: ignore[index]

    assert event.payload["list"] == (1, 2)
    assert event.payload["tuple"] == ("a", "b")
    assert event.payload["set"] == frozenset({"alpha", "beta"})


def test_audit_event_copies_shared_references_before_freezing() -> None:
    """Mutating caller-owned containers must not rewrite an existing event."""

    nested_payload = {"status": "original"}
    tags = ["finance"]
    event = AuditEvent(
        run_id="run-shared",
        timestamp=UTC_TIMESTAMP,
        event_type=AuditEventType.START,
        component="finance_agent",
        payload={"nested": nested_payload},
        metadata={"tags": tags},
    )

    nested_payload["status"] = "mutated"
    tags.append("changed")

    assert event.payload["nested"] == {"status": "original"}
    assert event.metadata == {"tags": ("finance",)}


def test_frozen_audit_event_serializes_as_standard_json() -> None:
    """Immutable runtime containers should thaw at the JSON boundary."""

    event = AuditEvent(
        run_id="run-json",
        timestamp=UTC_TIMESTAMP,
        event_type=AuditEventType.FINISH,
        component="finance_agent",
        payload={
            "list": [1, 2],
            "tuple": ("a", "b"),
            "set": {"beta", "alpha"},
        },
        metadata={"nested": {"ready": True}},
    )

    serialized = json.loads(event.model_dump_json())

    assert serialized["payload"] == {
        "list": [1, 2],
        "tuple": ["a", "b"],
        "set": ["alpha", "beta"],
    }
    assert serialized["metadata"] == {"nested": {"ready": True}}


def test_audit_event_rejects_nested_non_string_mapping_keys() -> None:
    """Deep validation should apply the JSON key contract recursively."""

    data = valid_event_data()
    data["payload"] = {"nested": {1: "invalid"}}

    with pytest.raises(ValidationError, match="keys must be strings"):
        AuditEvent.model_validate(data)
