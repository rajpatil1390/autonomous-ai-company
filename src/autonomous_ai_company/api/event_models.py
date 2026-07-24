"""Define the validated transport contract for workflow SSE events."""

from datetime import datetime, timedelta, timezone
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, JsonValue, field_validator


class WorkflowEventType(StrEnum):
    """Name the finite event vocabulary exposed by the streaming API."""

    WORKFLOW_STARTED = "workflow_started"
    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    HEARTBEAT = "heartbeat"


class WorkflowEvent(BaseModel):
    """Carry one immutable, JSON-safe progress event to an SSE client."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    run_id: str
    timestamp: datetime
    event_type: WorkflowEventType
    payload: dict[str, JsonValue]

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        """Reject empty identifiers because every event must be correlatable."""

        if not value.strip():
            raise ValueError("run_id must not be empty")
        return value

    @field_validator("timestamp")
    @classmethod
    def validate_utc_timestamp(cls, value: datetime) -> datetime:
        """Require aware UTC timestamps so clients can order events safely."""

        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("timestamp must be timezone-aware UTC")
        return value.astimezone(timezone.utc)
