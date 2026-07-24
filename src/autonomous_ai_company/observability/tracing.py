"""Implement optional OpenTelemetry tracing behind provider-neutral contracts.

This is the sole production module allowed to import OpenTelemetry. Explicit
opaque handles keep SDK spans inside the adapter, while OpenTelemetry context
propagation carries request ancestry through existing async LangGraph calls.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass
from re import fullmatch
from threading import RLock
from time import perf_counter
from typing import Any
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.trace import Status, StatusCode
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from autonomous_ai_company.audit.audit_logger import AuditLogger
from autonomous_ai_company.config import Settings
from autonomous_ai_company.observability.trace_models import (
    NullTracer,
    SpanHandle,
    TraceAttribute,
    Tracer,
)
from autonomous_ai_company.observability.tracking_models import (
    AgentTracking,
    RunStatus,
    TrackingClient,
    TrackingValue,
    WorkflowTracking,
)


_SAFE_ATTRIBUTES = {
    "workflow_id",
    "run_id",
    "agent_name",
    "provider",
    "model",
    "duration_ms",
    "retry_count",
    "success",
    "prompt_hash",
    "component",
    "event_type",
    "operation",
    "http.method",
    "http.route",
    "http.status_code",
    "exception.type",
}
_PROMPT_HASH_PATTERN = r"sha256:[0-9a-f]{64}"
_CURRENT_TRACER: ContextVar[Tracer | None] = ContextVar(
    "autonomous_ai_company_tracer",
    default=None,
)


@dataclass(slots=True)
class _ActiveSpan:
    """Retain SDK lifecycle state entirely inside the adapter."""

    span: Any
    activation: Any
    started_at: float
    parent_handle_id: str | None


class OpenTelemetryTracer:
    """Export safe spans while preserving concurrent async parentage."""

    def __init__(
        self,
        service_name: str,
        exporter: str = "console",
        otlp_endpoint: str | None = None,
        *,
        span_exporter: SpanExporter | None = None,
    ) -> None:
        """Create an isolated provider so request lifetimes never use globals."""

        provider = TracerProvider(
            resource=Resource.create({"service.name": service_name})
        )
        if span_exporter is not None:
            provider.add_span_processor(SimpleSpanProcessor(span_exporter))
        elif exporter == "otlp":
            if otlp_endpoint is None:
                raise ValueError("An OTLP endpoint is required")
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
            )
        elif exporter == "console":
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        else:
            raise ValueError(f"Unsupported OpenTelemetry exporter: {exporter}")
        self._provider = provider
        self._tracer = provider.get_tracer("autonomous_ai_company")
        self._lock = RLock()
        self._active: dict[str, _ActiveSpan] = {}
        self._otel_to_handle: dict[int, str] = {}

    def start_span(
        self,
        name: str,
        attributes: Mapping[str, TraceAttribute] | None = None,
    ) -> SpanHandle:
        """Start and activate one child span in the current async context."""

        safe_attributes = self._filter_attributes(attributes or {})
        current_span_id = trace.get_current_span().get_span_context().span_id
        parent_handle_id = self._otel_to_handle.get(current_span_id)
        sdk_span = self._tracer.start_span(name, attributes=safe_attributes)
        activation = trace.use_span(sdk_span, end_on_exit=False)
        activation.__enter__()
        handle = SpanHandle(handle_id=uuid4().hex, name=name)
        sdk_span_id = sdk_span.get_span_context().span_id
        with self._lock:
            self._active[handle.handle_id] = _ActiveSpan(
                span=sdk_span,
                activation=activation,
                started_at=perf_counter(),
                parent_handle_id=parent_handle_id,
            )
            self._otel_to_handle[sdk_span_id] = handle.handle_id
            for key in ("workflow_id", "run_id"):
                if key in safe_attributes:
                    self._propagate_identity(
                        parent_handle_id, key, safe_attributes[key]
                    )
        return handle

    def set_attribute(
        self,
        span: SpanHandle,
        key: str,
        value: TraceAttribute,
    ) -> None:
        """Set one allowlisted attribute and propagate workflow identity upward."""

        safe = self._filter_attributes({key: value})
        if key not in safe:
            return
        with self._lock:
            active = self._require_active(span)
            active.span.set_attribute(key, safe[key])
            if key in {"workflow_id", "run_id"}:
                self._propagate_identity(active.parent_handle_id, key, safe[key])

    def record_exception(self, span: SpanHandle, error: BaseException) -> None:
        """Record only exception type so messages cannot leak credentials."""

        with self._lock:
            active = self._require_active(span)
            exception_type = type(error).__name__
            active.span.add_event(
                "exception",
                attributes={"exception.type": exception_type},
            )
            active.span.set_status(Status(StatusCode.ERROR))
            active.span.set_attribute("exception.type", exception_type)

    def end_span(self, span: SpanHandle) -> None:
        """Attach duration, finish the SDK span, and restore its parent context."""

        with self._lock:
            active = self._require_active(span)
            duration_ms = (perf_counter() - active.started_at) * 1_000
            active.span.set_attribute("duration_ms", duration_ms)
            sdk_span_id = active.span.get_span_context().span_id
            del self._active[span.handle_id]
            self._otel_to_handle.pop(sdk_span_id, None)
        active.activation.__exit__(None, None, None)
        active.span.end()

    def shutdown(self) -> None:
        """Flush exporter resources deterministically at application shutdown."""

        self._provider.shutdown()

    def _require_active(self, span: SpanHandle) -> _ActiveSpan:
        """Reject stale or foreign handles instead of mutating another span."""

        try:
            return self._active[span.handle_id]
        except KeyError as error:
            raise ValueError(f"Span is not active: {span.name}") from error

    def _propagate_identity(
        self,
        handle_id: str | None,
        key: str,
        value: TraceAttribute,
    ) -> None:
        """Copy correlation IDs to already-open request and workflow ancestors."""

        while handle_id is not None:
            active = self._active.get(handle_id)
            if active is None:
                return
            active.span.set_attribute(key, value)
            handle_id = active.parent_handle_id

    @staticmethod
    def _filter_attributes(
        attributes: Mapping[str, TraceAttribute],
    ) -> dict[str, TraceAttribute]:
        """Apply an allowlist and validate the only prompt-derived value."""

        safe: dict[str, TraceAttribute] = {}
        for key, value in attributes.items():
            if key not in _SAFE_ATTRIBUTES:
                continue
            if key == "prompt_hash" and (
                not isinstance(value, str)
                or fullmatch(_PROMPT_HASH_PATTERN, value) is None
            ):
                continue
            safe[key] = value
        return safe


class TracedAuditLogger:
    """Add audit child spans without changing the AuditLogger implementation."""

    _TRACED_METHODS = {
        "log_start",
        "log_tool_call",
        "log_llm_request",
        "log_llm_response",
        "log_error",
        "log_finish",
        "get_events",
    }

    def __init__(self, delegate: AuditLogger, tracer: Tracer) -> None:
        """Store the existing logger and tracing contract as injected peers."""

        self._delegate = delegate
        self._tracer = tracer

    def __getattr__(self, name: str) -> Any:
        """Trace only the known AuditLogger API and delegate all other access."""

        attribute = getattr(self._delegate, name)
        if name not in self._TRACED_METHODS or not callable(attribute):
            return attribute

        def traced_call(*args: Any, **kwargs: Any) -> Any:
            run_id = args[0] if args and isinstance(args[0], str) else None
            component = (
                args[1] if len(args) > 1 and isinstance(args[1], str) else "audit"
            )
            attributes: dict[str, TraceAttribute] = {
                "component": component,
                "event_type": name.removeprefix("log_"),
            }
            if run_id is not None:
                attributes["run_id"] = run_id
                attributes["workflow_id"] = run_id
            span = self._tracer.start_span(
                f"audit.{name}",
                attributes,
            )
            try:
                result = attribute(*args, **kwargs)
                self._tracer.set_attribute(span, "success", True)
                return result
            except BaseException as error:
                self._tracer.set_attribute(span, "success", False)
                self._tracer.record_exception(span, error)
                raise
            finally:
                self._tracer.end_span(span)

        return traced_call


class TracedTrackingClient:
    """Add MLflow child spans while retaining the TrackingClient public API."""

    def __init__(self, delegate: TrackingClient, tracer: Tracer) -> None:
        """Store provider-neutral tracking and tracing dependencies."""

        self._delegate = delegate
        self._tracer = tracer

    def _call(
        self,
        operation: str,
        callback: Callable[[], Any],
        attributes: Mapping[str, TraceAttribute] | None = None,
    ) -> Any:
        """Trace one tracking operation without logging its arguments."""

        span = self._tracer.start_span(
            f"mlflow.{operation}",
            {"operation": operation, **(attributes or {})},
        )
        try:
            result = callback()
            self._tracer.set_attribute(span, "success", True)
            return result
        except BaseException as error:
            self._tracer.set_attribute(span, "success", False)
            self._tracer.record_exception(span, error)
            raise
        finally:
            self._tracer.end_span(span)

    def start_run(self, tracking: WorkflowTracking | AgentTracking) -> str:
        """Trace creation or lookup of one workflow or nested agent run."""

        if isinstance(tracking, WorkflowTracking):
            run_id = tracking.run_id
            agent_name = "workflow"
        else:
            run_id = tracking.workflow_run_id
            agent_name = tracking.agent_name
        return self._call(
            "start_run",
            lambda: self._delegate.start_run(tracking),
            {
                "run_id": run_id,
                "workflow_id": run_id,
                "agent_name": agent_name,
            },
        )

    def log_metrics(
        self,
        run_handle: str,
        metrics: Mapping[str, int | float],
    ) -> None:
        """Trace metrics transport without copying metric payloads into spans."""

        self._call(
            "log_metrics",
            lambda: self._delegate.log_metrics(run_handle, metrics),
        )

    def log_params(
        self,
        run_handle: str,
        params: Mapping[str, TrackingValue],
    ) -> None:
        """Trace safe MLflow parameters using prompt hashes only."""

        attributes: dict[str, TraceAttribute] = {}
        provider = params.get("provider")
        model = params.get("model_name")
        prompt_hash = next(
            (
                value
                for key, value in params.items()
                if key.startswith("prompt_hash_attempt_") and isinstance(value, str)
            ),
            None,
        )
        if isinstance(provider, str):
            attributes["provider"] = provider
        if isinstance(model, str):
            attributes["model"] = model
        if prompt_hash is not None:
            attributes["prompt_hash"] = prompt_hash
        self._call(
            "log_params",
            lambda: self._delegate.log_params(run_handle, params),
            attributes,
        )

    def log_tags(
        self,
        run_handle: str,
        tags: Mapping[str, TrackingValue],
    ) -> None:
        """Trace tag transport without copying arbitrary tag contents."""

        self._call(
            "log_tags",
            lambda: self._delegate.log_tags(run_handle, tags),
        )

    def log_artifact(
        self,
        run_handle: str,
        artifact_name: str,
        content: str,
    ) -> None:
        """Trace artifact transport without recording names or contents."""

        self._call(
            "log_artifact",
            lambda: self._delegate.log_artifact(
                run_handle,
                artifact_name,
                content,
            ),
        )

    def end_run(self, run_handle: str, status: RunStatus = "FINISHED") -> None:
        """Trace tracking lifecycle completion."""

        self._call(
            "end_run",
            lambda: self._delegate.end_run(run_handle, status),
            {"success": status == "FINISHED"},
        )


def create_tracer(
    settings: Settings,
    *,
    span_exporter: SpanExporter | None = None,
) -> Tracer:
    """Create the configured request-scoped tracing adapter."""

    if settings.otel_enabled is not True:
        return NullTracer()
    return OpenTelemetryTracer(
        service_name=settings.otel_service_name,
        exporter=settings.otel_exporter,
        otlp_endpoint=settings.otel_otlp_endpoint,
        span_exporter=span_exporter,
    )


def get_current_tracer() -> Tracer | None:
    """Return the tracer bound to the active request context, if any."""

    return _CURRENT_TRACER.get()


def bind_tracer(tracer: Tracer) -> Token[Tracer | None]:
    """Bind one tracer so request-scoped dependency construction can reuse it."""

    return _CURRENT_TRACER.set(tracer)


def reset_tracer(token: Token[Tracer | None]) -> None:
    """Restore the prior request context after response completion."""

    _CURRENT_TRACER.reset(token)


class TracingMiddleware:
    """Create HTTP and workflow root spans around complete ASGI responses."""

    def __init__(
        self,
        app: ASGIApp,
        tracer_factory: Callable[[], Tracer],
    ) -> None:
        """Store the downstream application and request-scoped factory."""

        self._app = app
        self._tracer_factory = tracer_factory

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Trace HTTP requests while leaving non-HTTP ASGI scopes untouched."""

        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        tracer = self._tracer_factory()
        token = bind_tracer(tracer)
        path = scope.get("path", "")
        request_span = tracer.start_span(
            "http.request",
            {
                "http.method": scope.get("method", ""),
                "http.route": path,
            },
        )
        workflow_span = (
            tracer.start_span("workflow.execute")
            if path in {"/workflow/run", "/workflow/stream"}
            else None
        )
        response_status = 500

        async def traced_send(message: Message) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message["status"]
            await send(message)

        try:
            await self._app(scope, receive, traced_send)
        except BaseException as error:
            if workflow_span is not None:
                tracer.record_exception(workflow_span, error)
            tracer.record_exception(request_span, error)
            raise
        finally:
            success = response_status < 500
            if workflow_span is not None:
                tracer.set_attribute(workflow_span, "success", success)
                tracer.end_span(workflow_span)
            tracer.set_attribute(request_span, "http.status_code", response_status)
            tracer.set_attribute(request_span, "success", success)
            tracer.end_span(request_span)
            reset_tracer(token)
