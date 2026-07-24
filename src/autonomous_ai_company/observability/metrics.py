"""Implement optional Prometheus metrics behind a provider-neutral contract.

This is the sole production module that imports ``prometheus_client``. An
application owns its explicit ``CollectorRegistry`` and registered instruments;
request-scoped collector facades share those instruments without using the
library's default global registry.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextvars import ContextVar, Token
import logging
from math import isfinite
from threading import RLock
from time import perf_counter
from typing import Any

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest
from prometheus_client.metrics import Counter, Gauge, Histogram
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from autonomous_ai_company.audit.audit_logger import AuditLogger
from autonomous_ai_company.config import Settings
from autonomous_ai_company.observability.metrics_models import (
    MetricLabels,
    MetricsCollector,
    MetricValue,
    NullMetricsCollector,
)


_ALLOWED_LABELS = frozenset({"workflow", "agent", "provider", "model", "status"})
_COUNTER_LABELS: dict[str, tuple[str, ...]] = {
    "http_requests_total": ("status",),
    "workflow_runs_total": ("workflow", "status"),
    "workflow_failures_total": ("workflow",),
    "workflow_success_total": ("workflow",),
    "agent_runs_total": ("agent", "status"),
    "agent_retry_total": ("agent",),
    "agent_failures_total": ("agent",),
    "llm_requests_total": ("agent", "provider", "model", "status"),
    "llm_tokens_total": ("agent", "provider", "model", "status"),
    "audit_events_total": ("agent", "status"),
    "audit_failures_total": ("agent",),
    "auth_login_total": ("status",),
    "auth_failures_total": ("status",),
}
_HISTOGRAM_LABELS: dict[str, tuple[str, ...]] = {
    "http_request_duration_seconds": ("status",),
    "workflow_duration_seconds": ("workflow", "status"),
    "agent_duration_seconds": ("agent", "status"),
    "llm_latency_seconds": ("agent", "provider", "model", "status"),
}
_GAUGE_LABELS: dict[str, tuple[str, ...]] = {
    "workflow_active": ("workflow",),
}
_DESCRIPTIONS = {
    "http_requests_total": "Total HTTP responses by status.",
    "http_request_duration_seconds": "HTTP request duration in seconds.",
    "workflow_runs_total": "Total workflow executions by outcome.",
    "workflow_duration_seconds": "Workflow execution duration in seconds.",
    "workflow_failures_total": "Total failed workflow executions.",
    "workflow_success_total": "Total successful workflow executions.",
    "workflow_active": "Currently active workflow HTTP requests.",
    "agent_runs_total": "Total agent executions by outcome.",
    "agent_duration_seconds": "Agent execution duration in seconds.",
    "agent_retry_total": "Total agent schema-correction retries.",
    "agent_failures_total": "Total failed agent executions.",
    "llm_requests_total": "Total provider-neutral LLM requests.",
    "llm_latency_seconds": "Provider-reported LLM latency in seconds.",
    "llm_tokens_total": "Total provider-reported generation tokens.",
    "audit_events_total": "Total successfully persisted audit events.",
    "audit_failures_total": "Total failed audit persistence attempts.",
    "auth_login_total": "Total authentication login responses.",
    "auth_failures_total": "Total failed authentication login responses.",
}
_CURRENT_COLLECTOR: ContextVar[MetricsCollector | None] = ContextVar(
    "autonomous_ai_company_metrics_collector",
    default=None,
)
_LOGGER = logging.getLogger(__name__)


class _PrometheusInstruments:
    """Own one registry's instruments and synchronize their construction."""

    def __init__(
        self,
        registry: CollectorRegistry,
        namespace: str,
        subsystem: str,
    ) -> None:
        self.registry = registry
        self.namespace = namespace
        self.subsystem = subsystem
        self.lock = RLock()
        self.counters: dict[str, Counter] = {}
        self.histograms: dict[str, Histogram] = {}
        self.gauges: dict[str, Gauge] = {}


class PrometheusMetricsCollector:
    """Record allowlisted metrics in one explicitly supplied registry.

    ``fork`` creates a distinct request-scoped facade while retaining the same
    application-owned registry and instruments. The client library provides
    thread-safe metric updates, and the local lock protects lazy registration
    when concurrent requests first encounter an instrument.
    """

    def __init__(
        self,
        registry: CollectorRegistry,
        namespace: str = "autonomous_ai_company",
        subsystem: str = "",
        *,
        _instruments: _PrometheusInstruments | None = None,
    ) -> None:
        """Bind a collector to an explicit registry, never the global default."""

        self._instruments = _instruments or _PrometheusInstruments(
            registry,
            namespace,
            subsystem,
        )

    @property
    def registry(self) -> CollectorRegistry:
        """Expose the owned registry for Prometheus text serialization only."""

        return self._instruments.registry

    def fork(self) -> PrometheusMetricsCollector:
        """Return a fresh request facade sharing application instruments."""

        return PrometheusMetricsCollector(
            self.registry,
            _instruments=self._instruments,
        )

    def increment_counter(
        self,
        name: str,
        value: MetricValue = 1,
        labels: MetricLabels | None = None,
    ) -> None:
        """Increment one declared counter after validating value and labels."""

        amount = self._validated_value(value, non_negative=True)
        metric = self._metric(
            name, _COUNTER_LABELS, self._instruments.counters, Counter
        )
        metric.labels(**self._validated_labels(name, labels, _COUNTER_LABELS)).inc(
            amount
        )

    def observe_histogram(
        self,
        name: str,
        value: MetricValue,
        labels: MetricLabels | None = None,
    ) -> None:
        """Observe one declared histogram after validating value and labels."""

        observation = self._validated_value(value, non_negative=True)
        metric = self._metric(
            name,
            _HISTOGRAM_LABELS,
            self._instruments.histograms,
            Histogram,
        )
        metric.labels(
            **self._validated_labels(name, labels, _HISTOGRAM_LABELS)
        ).observe(observation)

    def set_gauge(
        self,
        name: str,
        value: MetricValue,
        labels: MetricLabels | None = None,
    ) -> None:
        """Set one declared gauge after validating value and labels."""

        gauge_value = self._validated_value(value, non_negative=False)
        metric = self._metric(name, _GAUGE_LABELS, self._instruments.gauges, Gauge)
        metric.labels(**self._validated_labels(name, labels, _GAUGE_LABELS)).set(
            gauge_value
        )

    def _metric(
        self,
        name: str,
        policy: Mapping[str, tuple[str, ...]],
        cache: dict[str, Any],
        metric_type: type[Any],
    ) -> Any:
        """Return one lazily registered metric from the requested type policy."""

        if name not in policy:
            raise ValueError(f"Unsupported metric: {name}")
        with self._instruments.lock:
            existing = cache.get(name)
            if existing is not None:
                return existing
            metric = metric_type(
                name,
                _DESCRIPTIONS[name],
                labelnames=policy[name],
                namespace=self._instruments.namespace,
                subsystem=self._instruments.subsystem,
                registry=self.registry,
            )
            cache[name] = metric
            return metric

    @staticmethod
    def _validated_labels(
        name: str,
        labels: MetricLabels | None,
        policy: Mapping[str, tuple[str, ...]],
    ) -> dict[str, str]:
        """Reject unknown label keys and fill omitted safe labels deterministically."""

        supplied = dict(labels or {})
        unsupported = set(supplied) - _ALLOWED_LABELS
        if unsupported:
            names = ", ".join(sorted(unsupported))
            raise ValueError(f"Unsupported metric labels: {names}")
        expected = policy[name]
        irrelevant = set(supplied) - set(expected)
        if irrelevant:
            names = ", ".join(sorted(irrelevant))
            raise ValueError(f"Labels are not valid for {name}: {names}")
        if any(not isinstance(value, str) for value in supplied.values()):
            raise TypeError("Metric label values must be strings")
        return {label: supplied.get(label, "") for label in expected}

    @staticmethod
    def _validated_value(value: MetricValue, *, non_negative: bool) -> float:
        """Accept finite numeric observations and enforce metric semantics."""

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("Metric values must be integers or floats")
        converted = float(value)
        if not isfinite(converted):
            raise ValueError("Metric values must be finite")
        if non_negative and converted < 0:
            raise ValueError("Metric values must be non-negative")
        return converted


class MetricsAuditLogger:
    """Count audit writes without changing the AuditLogger public API."""

    _LOG_METHODS = {
        "log_start",
        "log_tool_call",
        "log_llm_request",
        "log_llm_response",
        "log_error",
        "log_finish",
    }

    def __init__(
        self, delegate: AuditLogger | Any, collector: MetricsCollector
    ) -> None:
        """Store the existing logger and provider-neutral metrics boundary."""

        self._delegate = delegate
        self._collector = collector

    def __getattr__(self, name: str) -> Any:
        """Instrument known writes and delegate reads or attributes unchanged."""

        attribute = getattr(self._delegate, name)
        if name not in self._LOG_METHODS or not callable(attribute):
            return attribute

        def measured_call(*args: Any, **kwargs: Any) -> Any:
            positional_component = args[1] if len(args) > 1 else None
            keyword_component = kwargs.get("component")
            component = next(
                (
                    value
                    for value in (positional_component, keyword_component)
                    if isinstance(value, str)
                ),
                "audit",
            )
            try:
                result = attribute(*args, **kwargs)
            except BaseException:
                self._safe_increment("audit_failures_total", {"agent": component})
                raise
            self._safe_increment(
                "audit_events_total",
                {"agent": component, "status": "success"},
            )
            return result

        return measured_call

    def _safe_increment(self, name: str, labels: MetricLabels) -> None:
        """Prevent optional metrics failures from altering audit behavior."""

        try:
            self._collector.increment_counter(name, labels=labels)
        except Exception as error:
            _LOGGER.error("Audit metrics failed: %s", type(error).__name__)


def create_metrics_collector(
    settings: Settings,
    *,
    registry: CollectorRegistry | None = None,
) -> MetricsCollector:
    """Create an enabled isolated collector or the disabled no-op adapter."""

    if settings.metrics_enabled is not True:
        return NullMetricsCollector()
    return PrometheusMetricsCollector(
        registry=registry or CollectorRegistry(),
        namespace=settings.metrics_namespace,
        subsystem=settings.metrics_subsystem,
    )


def get_current_metrics_collector() -> MetricsCollector | None:
    """Return the collector bound to the active request context, if any."""

    return _CURRENT_COLLECTOR.get()


def bind_metrics_collector(
    collector: MetricsCollector,
) -> Token[MetricsCollector | None]:
    """Bind one request-scoped collector for bootstrap dependency reuse."""

    return _CURRENT_COLLECTOR.set(collector)


def reset_metrics_collector(token: Token[MetricsCollector | None]) -> None:
    """Restore the prior async metrics context after response completion."""

    _CURRENT_COLLECTOR.reset(token)


def create_metrics_router(registry: CollectorRegistry) -> APIRouter:
    """Expose one application's registry in Prometheus text format."""

    router = APIRouter()

    @router.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(
            content=generate_latest(registry),
            media_type=CONTENT_TYPE_LATEST,
        )

    return router


class MetricsMiddleware:
    """Measure HTTP, workflow, and authentication outcomes at the API edge."""

    def __init__(
        self,
        app: ASGIApp,
        collector_factory: Callable[[], MetricsCollector],
    ) -> None:
        """Store the downstream application and request collector factory."""

        self._app = app
        self._collector_factory = collector_factory
        self._workflow_lock = RLock()
        self._active_workflows = 0

    def _adjust_active_workflows(
        self,
        collector: MetricsCollector,
        adjustment: int,
    ) -> None:
        """Update the shared active gauge atomically across concurrent requests."""

        with self._workflow_lock:
            self._active_workflows += adjustment
            collector.set_gauge(
                "workflow_active",
                self._active_workflows,
                {"workflow": "company"},
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Measure HTTP scopes while passing other ASGI traffic through untouched."""

        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        collector = self._collector_factory()
        token = bind_metrics_collector(collector)
        started_at = perf_counter()
        path = scope.get("path", "")
        is_workflow = path in {"/workflow/run", "/workflow/stream"}
        response_status = 500
        request_failed = False
        if is_workflow:
            self._adjust_active_workflows(collector, 1)

        async def measured_send(message: Message) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message["status"]
            await send(message)

        try:
            await self._app(scope, receive, measured_send)
        except BaseException:
            request_failed = True
            raise
        finally:
            status = str(response_status)
            duration = perf_counter() - started_at
            collector.increment_counter(
                "http_requests_total",
                labels={"status": status},
            )
            collector.observe_histogram(
                "http_request_duration_seconds",
                duration,
                {"status": status},
            )
            if is_workflow:
                outcome = (
                    "success"
                    if not request_failed and response_status < 500
                    else "failure"
                )
                workflow_labels = {"workflow": "company", "status": outcome}
                collector.increment_counter(
                    "workflow_runs_total",
                    labels=workflow_labels,
                )
                collector.observe_histogram(
                    "workflow_duration_seconds",
                    duration,
                    workflow_labels,
                )
                terminal_metric = (
                    "workflow_success_total"
                    if outcome == "success"
                    else "workflow_failures_total"
                )
                collector.increment_counter(
                    terminal_metric,
                    labels={"workflow": "company"},
                )
                self._adjust_active_workflows(collector, -1)
            if path == "/auth/login":
                auth_status = "success" if response_status < 400 else "failure"
                collector.increment_counter(
                    "auth_login_total",
                    labels={"status": auth_status},
                )
                if auth_status == "failure":
                    collector.increment_counter(
                        "auth_failures_total",
                        labels={"status": str(response_status)},
                    )
            reset_metrics_collector(token)
