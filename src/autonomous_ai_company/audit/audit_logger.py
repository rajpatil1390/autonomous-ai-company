"""Record allowlisted audit events behind a replaceable storage interface.

Phase A keeps events in memory, while the logger's public API depends only on
an abstract storage capability that a PostgreSQL adapter can implement later.
"""

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from threading import RLock
from typing import Protocol

from autonomous_ai_company.exceptions import AuditError
from autonomous_ai_company.schemas.audit import AuditEvent, AuditEventType


_EVENT_PAYLOAD_ALLOWLIST: Mapping[AuditEventType, tuple[str, ...]] = {
    AuditEventType.START: ("dataset_size",),
    AuditEventType.TOOL_CALL: ("tool_name", "duration_ms", "success"),
    AuditEventType.LLM_REQUEST: (
        "provider",
        "model_name",
        "prompt_hash",
        "prompt_length",
        "attempt",
    ),
    AuditEventType.LLM_RESPONSE: (
        "provider",
        "model_name",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "stop_reason",
        "request_id",
    ),
    AuditEventType.ERROR: ("exception_type", "message", "retryable"),
    AuditEventType.FINISH: ("duration_ms", "status"),
}


class AuditStorage(Protocol):
    """Define the persistence capability required by ``AuditLogger``.

    PostgreSQL can replace in-memory storage by implementing these two methods;
    event producers remain unaware of database sessions or table structures.
    """

    def append(self, event: AuditEvent) -> None:
        """Persist one already validated audit event."""

        ...

    def snapshot(self) -> tuple[AuditEvent, ...]:
        """Return an ordered, immutable view of persisted events."""

        ...


class InMemoryAuditStorage:
    """Store ordered events safely for Phase A tests and local execution."""

    def __init__(self) -> None:
        """Initialize isolated event state and its synchronization lock."""

        self._events: list[AuditEvent] = []
        self._lock = RLock()

    def append(self, event: AuditEvent) -> None:
        """Append atomically so concurrent writers cannot corrupt ordering."""

        with self._lock:
            self._events.append(event)

    def snapshot(self) -> tuple[AuditEvent, ...]:
        """Copy events under lock so callers cannot mutate internal storage."""

        with self._lock:
            return tuple(self._events)


def _utc_now() -> datetime:
    """Provide an injectable UTC clock without binding callers to wall time."""

    return datetime.now(timezone.utc)


def _filter_allowed_fields(
    values: Mapping[str, object],
    allowed_fields: tuple[str, ...],
) -> dict[str, object]:
    """Copy only explicitly approved fields in canonical policy order.

    Unknown fields are rejected from the persisted representation rather than
    raising an error, so callers cannot expand the audit data surface merely by
    adding a new key. Container validation remains strict at the API boundary.
    """

    if not isinstance(values, Mapping):
        raise TypeError("audit payload and metadata must be mappings")

    for key in values:
        if not isinstance(key, str):
            raise TypeError("audit payload and metadata keys must be strings")
    return {field: values[field] for field in allowed_fields if field in values}


class AuditLogger:
    """Allowlist, validate, and store ordered lifecycle events.

    Centralizing these concerns prevents individual business components from
    expanding the audit data surface or coupling themselves to storage calls.
    """

    def __init__(
        self,
        storage: AuditStorage | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize the logger with replaceable storage and clock dependencies."""

        self._storage = storage if storage is not None else InMemoryAuditStorage()
        self._clock = clock if clock is not None else _utc_now
        self._lock = RLock()

    def _log(
        self,
        event_type: AuditEventType,
        run_id: str,
        component: str,
        payload: Mapping[str, object] | None,
        metadata: Mapping[str, object] | None,
    ) -> AuditEvent:
        """Apply the allowlist and perform exactly one atomic append attempt.

        Storage failures are translated and returned to the caller; the logger
        never attempts to audit its own failure because that would recurse into
        the same unavailable backend.
        """

        with self._lock:
            try:
                allowed_fields = _EVENT_PAYLOAD_ALLOWLIST[event_type]
                event = AuditEvent(
                    run_id=run_id,
                    timestamp=self._clock(),
                    event_type=event_type,
                    component=component,
                    payload=(
                        _filter_allowed_fields(payload, allowed_fields)
                        if payload is not None
                        else {}
                    ),
                    metadata=(
                        _filter_allowed_fields(metadata, allowed_fields)
                        if metadata is not None
                        else None
                    ),
                )
                self._storage.append(event)
                return event
            except Exception as error:
                raise AuditError(
                    f"Failed to record {event_type.value} audit event"
                ) from error

    def log_start(
        self,
        run_id: str,
        component: str,
        payload: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> AuditEvent:
        """Record that a component began work for a workflow run."""

        return self._log(AuditEventType.START, run_id, component, payload, metadata)

    def log_tool_call(
        self,
        run_id: str,
        component: str,
        payload: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> AuditEvent:
        """Record approved facts about a deterministic tool invocation."""

        return self._log(AuditEventType.TOOL_CALL, run_id, component, payload, metadata)

    def log_llm_request(
        self,
        run_id: str,
        component: str,
        payload: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> AuditEvent:
        """Record approved LLM request telemetry without prompt content."""

        return self._log(
            AuditEventType.LLM_REQUEST, run_id, component, payload, metadata
        )

    def log_llm_response(
        self,
        run_id: str,
        component: str,
        payload: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> AuditEvent:
        """Record approved response telemetry without generated text."""

        return self._log(
            AuditEventType.LLM_RESPONSE, run_id, component, payload, metadata
        )

    def log_error(
        self,
        run_id: str,
        component: str,
        payload: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> AuditEvent:
        """Record approved error facts without swallowing the original error."""

        return self._log(AuditEventType.ERROR, run_id, component, payload, metadata)

    def log_finish(
        self,
        run_id: str,
        component: str,
        payload: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> AuditEvent:
        """Record that a component completed work for a workflow run."""

        return self._log(AuditEventType.FINISH, run_id, component, payload, metadata)

    def get_events(self) -> tuple[AuditEvent, ...]:
        """Return an immutable ordered snapshot from the configured storage."""

        with self._lock:
            try:
                return self._storage.snapshot()
            except Exception as error:
                raise AuditError("Failed to read audit events") from error
