"""Define provider-neutral distributed tracing contracts and handles.

Agents use these types without knowing whether spans are exported to a console,
an OTLP collector, an in-memory test sink, or nowhere at all.
"""

from collections.abc import Mapping
from typing import Protocol, TypeAlias, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


TraceAttribute: TypeAlias = str | bool | int | float


class SpanHandle(BaseModel):
    """Carry an opaque span identity without exposing SDK span objects."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    handle_id: str = Field(min_length=1, description="Adapter-owned span handle.")
    name: str = Field(min_length=1, description="Stable operation name.")


@runtime_checkable
class Tracer(Protocol):
    """Define the tracing operations available to application orchestrators."""

    def start_span(
        self,
        name: str,
        attributes: Mapping[str, TraceAttribute] | None = None,
    ) -> SpanHandle:
        """Start a span beneath the current async trace context."""

    def set_attribute(
        self,
        span: SpanHandle,
        key: str,
        value: TraceAttribute,
    ) -> None:
        """Attach one safe, provider-neutral observation to a span."""

    def record_exception(self, span: SpanHandle, error: BaseException) -> None:
        """Record exception type without leaking its potentially sensitive text."""

    def end_span(self, span: SpanHandle) -> None:
        """Finish a span and restore its parent async context."""


class NullTracer:
    """Preserve the tracing contract with zero side effects when disabled."""

    def start_span(
        self,
        name: str,
        attributes: Mapping[str, TraceAttribute] | None = None,
    ) -> SpanHandle:
        """Return an opaque no-op handle."""

        del attributes
        return SpanHandle(handle_id=f"null:{name}", name=name)

    def set_attribute(
        self,
        span: SpanHandle,
        key: str,
        value: TraceAttribute,
    ) -> None:
        """Discard an attribute intentionally."""

    def record_exception(self, span: SpanHandle, error: BaseException) -> None:
        """Discard an exception intentionally."""

    def end_span(self, span: SpanHandle) -> None:
        """End the no-op lifecycle intentionally."""
