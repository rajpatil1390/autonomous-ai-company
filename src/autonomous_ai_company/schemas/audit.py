"""Define provider-independent contracts for deeply immutable audit events.

Audit data is validated and recursively frozen before storage so the same
trustworthy event contract can move from Phase A memory storage to Phase E
PostgreSQL persistence without allowing post-creation history changes.
"""

import json
import math
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_serializer,
    field_validator,
)


def _reject_mutation(*args: object, **kwargs: object) -> None:
    """Reject every normal dictionary mutation operation."""

    raise TypeError("audit JSON mappings are immutable")


class FrozenDict(dict[str, object]):
    """Provide a JSON-compatible dictionary that rejects mutation."""

    __setitem__ = _reject_mutation  # type: ignore[assignment]
    __delitem__ = _reject_mutation  # type: ignore[assignment]
    clear = _reject_mutation  # type: ignore[assignment]
    pop = _reject_mutation  # type: ignore[assignment]
    popitem = _reject_mutation  # type: ignore[assignment]
    setdefault = _reject_mutation  # type: ignore[assignment]
    update = _reject_mutation  # type: ignore[assignment]
    __ior__ = _reject_mutation  # type: ignore[assignment]


class AuditEventType(StrEnum):
    """Name the lifecycle events that every audited component may emit."""

    START = "start"
    TOOL_CALL = "tool_call"
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    ERROR = "error"
    FINISH = "finish"


def _freeze_json(value: object) -> object:
    """Validate and recursively freeze one extended JSON-compatible value."""

    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("audit JSON mapping keys must be strings")
            frozen[key] = _freeze_json(item)
        return FrozenDict(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_json(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("audit JSON values must contain only finite numbers")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("audit values must be JSON-compatible")


def _thaw_json(value: object) -> JsonValue:
    """Convert immutable containers into deterministic standard JSON values."""

    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    if isinstance(value, frozenset):
        items = [_thaw_json(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    return value  # type: ignore[return-value]


class AuditEvent(BaseModel):
    """Represent one validated, deeply immutable audit trail entry.

    A stable event envelope separates observability from business logic and
    gives future storage backends the same fields, types, and guarantees.
    Recursive freezing prevents callers, shared references, and storage
    snapshots from changing already-recorded evidence.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        arbitrary_types_allowed=True,
    )

    run_id: str = Field(
        min_length=1,
        description="Identifier connecting events from one workflow run.",
    )
    timestamp: datetime = Field(
        description="Timezone-aware UTC instant when the event was recorded.",
    )
    event_type: AuditEventType = Field(
        description="Controlled lifecycle category for this event.",
    )
    component: str = Field(
        min_length=1,
        description="Provider-independent component that emitted the event.",
    )
    payload: Mapping[str, object] = Field(
        description="Deeply immutable JSON-compatible event facts.",
    )
    metadata: Mapping[str, object] | None = Field(
        default=None,
        description="Optional deeply immutable correlation attributes.",
    )

    @field_validator("timestamp")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        """Reject naive or non-UTC timestamps to preserve global ordering."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        if value.utcoffset() != timedelta(0):
            raise ValueError("timestamp must use UTC")
        return value.astimezone(timezone.utc)

    @field_validator("payload", "metadata")
    @classmethod
    def freeze_json_fields(
        cls,
        value: Mapping[str, object] | None,
    ) -> Mapping[str, object] | None:
        """Validate, copy, and recursively freeze payloads and metadata."""

        if value is None:
            return None
        return _freeze_json(value)  # type: ignore[return-value]

    @field_serializer("payload", "metadata")
    def serialize_json_fields(
        self,
        value: Mapping[str, object] | None,
    ) -> JsonValue:
        """Serialize immutable containers as ordinary JSON objects and arrays."""

        if value is None:
            return None
        return _thaw_json(value)
