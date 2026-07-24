"""Define immutable, provider-neutral experiment tracking contracts.

These DTOs prevent MLflow objects and unbounded application data from crossing
the infrastructure boundary. Their deliberately narrow fields also make raw
prompts, generated text, and credentials impossible to log accidentally.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


TrackingValue = str | int | float | bool
RunStatus = Literal["FINISHED", "FAILED", "KILLED"]


class _TrackingModel(BaseModel):
    """Apply one strict immutable contract to every tracking DTO."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class WorkflowTracking(_TrackingModel):
    """Identify one workflow parent without carrying workflow state or inputs."""

    run_id: str = Field(min_length=1, description="Application workflow identifier.")
    started_at: datetime = Field(description="UTC workflow observation start time.")
    workflow_name: str = Field(
        default="company_workflow",
        min_length=1,
        description="Stable grouping name used for MLflow run discovery.",
    )


class AgentTracking(_TrackingModel):
    """Describe one nested specialist run under its workflow parent."""

    workflow_run_id: str = Field(
        min_length=1,
        description="Application identifier used to locate the workflow parent.",
    )
    agent_name: str = Field(min_length=1, description="Provider-neutral agent name.")
    started_at: datetime = Field(description="UTC agent observation start time.")
    closes_workflow: bool = Field(
        default=False,
        description="Signal that ending this terminal child also ends its parent.",
    )


class GenerationTracking(_TrackingModel):
    """Capture safe generation telemetry without response or prompt contents."""

    provider: str = Field(min_length=1, description="Provider adapter identifier.")
    model_name: str = Field(min_length=1, description="Provider model identifier.")
    prompt_hash: str = Field(
        pattern=r"^sha256:[0-9a-f]{64}$",
        description="Non-reversible SHA-256 fingerprint of the bounded prompt.",
    )
    attempt: int = Field(ge=1, description="One-based generation attempt number.")
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    latency_ms: float | None = Field(default=None, ge=0)
    request_id: str | None = Field(default=None, min_length=1)
    stop_reason: str | None = Field(default=None, min_length=1)


class AuditTracking(_TrackingModel):
    """Summarize audit coverage without duplicating sensitive audit payloads."""

    event_count: int = Field(ge=0, description="Number of immutable audit events.")
    error_count: int = Field(ge=0, description="Number of recorded error events.")
    event_types: tuple[str, ...] = Field(
        default=(),
        description="Ordered event type names, excluding event payloads.",
    )


@runtime_checkable
class TrackingClient(Protocol):
    """Define the only experiment tracking interface visible to agents.

    Implementations own parent/child lifecycle and storage. Callers keep the
    opaque run handle and never receive backend-specific run objects.
    """

    def start_run(self, tracking: WorkflowTracking | AgentTracking) -> str:
        """Start or locate a workflow run, or create one nested agent run."""

    def log_metrics(
        self,
        run_handle: str,
        metrics: Mapping[str, int | float],
    ) -> None:
        """Record numeric telemetry against an opaque run handle."""

    def log_params(
        self,
        run_handle: str,
        params: Mapping[str, TrackingValue],
    ) -> None:
        """Record bounded descriptive values without sensitive contents."""

    def log_tags(
        self,
        run_handle: str,
        tags: Mapping[str, TrackingValue],
    ) -> None:
        """Attach safe searchable run classifications."""

    def log_artifact(
        self,
        run_handle: str,
        artifact_name: str,
        content: str,
    ) -> None:
        """Persist a named report through the infrastructure adapter."""

    def end_run(self, run_handle: str, status: RunStatus = "FINISHED") -> None:
        """Terminate a run and any parent lifecycle it explicitly closes."""


class NullTrackingClient:
    """Provide a zero-side-effect implementation when tracking is disabled."""

    def start_run(self, tracking: WorkflowTracking | AgentTracking) -> str:
        """Return a stable local handle without creating external state."""

        if isinstance(tracking, WorkflowTracking):
            return f"workflow:{tracking.run_id}"
        return f"agent:{tracking.workflow_run_id}:{tracking.agent_name}"

    def log_metrics(
        self,
        run_handle: str,
        metrics: Mapping[str, int | float],
    ) -> None:
        """Discard metrics intentionally."""

    def log_params(
        self,
        run_handle: str,
        params: Mapping[str, TrackingValue],
    ) -> None:
        """Discard parameters intentionally."""

    def log_tags(
        self,
        run_handle: str,
        tags: Mapping[str, TrackingValue],
    ) -> None:
        """Discard tags intentionally."""

    def log_artifact(
        self,
        run_handle: str,
        artifact_name: str,
        content: str,
    ) -> None:
        """Discard artifact content intentionally."""

    def end_run(self, run_handle: str, status: RunStatus = "FINISHED") -> None:
        """End the no-op lifecycle intentionally."""
