"""Integration tests for optional provider-neutral Prometheus metrics."""

import asyncio
from unittest.mock import Mock, patch

import httpx
import pytest
from prometheus_client import CollectorRegistry, generate_latest
from pydantic import SecretStr, ValidationError

from autonomous_ai_company.api.app import create_app
from autonomous_ai_company.api.dependencies import build_company_graph
from autonomous_ai_company.audit.audit_logger import AuditLogger
from autonomous_ai_company.auth.dependencies import get_current_user
from autonomous_ai_company.auth.models import AuthenticatedUser
from autonomous_ai_company.bootstrap import (
    _build_metrics_collector,
    _build_runtime_dependencies,
    build_company_graph as compose_graph,
    build_finance_agent,
)
from autonomous_ai_company.config import Settings, get_settings
from autonomous_ai_company.exceptions import LLMUnavailableError
from autonomous_ai_company.observability.metrics import (
    MetricsAuditLogger,
    MetricsMiddleware,
    PrometheusMetricsCollector,
    bind_metrics_collector,
    create_metrics_collector,
    get_current_metrics_collector,
    reset_metrics_collector,
)
from autonomous_ai_company.observability.metrics_models import (
    MetricsCollector,
    NullMetricsCollector,
    record_agent_metrics,
    record_failed_generation_metrics,
    record_generation_metrics,
)
from autonomous_ai_company.observability.trace_models import NullTracer
from autonomous_ai_company.observability.tracking_models import NullTrackingClient


def settings(**overrides: object) -> Settings:
    """Build isolated application configuration for metrics tests."""

    values: dict[str, object] = {
        "ANTHROPIC_API_KEY": SecretStr("test-api-key"),
        "MODEL_NAME": "test-model",
        "TEMPERATURE": 0.0,
        "MAX_TOKENS": 256,
        "LOG_LEVEL": "INFO",
        "JWT_SECRET_KEY": SecretStr("x" * 32),
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def exposition(registry: CollectorRegistry) -> str:
    """Return one isolated registry's text representation."""

    return generate_latest(registry).decode("utf-8")


def workflow_payload() -> dict[str, object]:
    """Return a complete API workflow request."""

    return {
        "dataset": [{"revenue": 100, "cost": 60}],
        "previous_dataset": [{"revenue": 80, "cost": 50}],
        "data_scientist_series": [10, 20, 30],
        "business_context": "Controlled growth.",
        "executive_question": "What comes next?",
    }


def ceo_response() -> dict[str, object]:
    """Return one valid terminal graph response."""

    return {
        "executive_summary": "Proceed carefully.",
        "business_health": "stable",
        "strategic_priorities": ["Protect margin."],
        "key_risks": ["Demand volatility."],
        "final_recommendation": "Use staged investment.",
        "confidence_score": 0.9,
    }


class FakeGraph:
    """Provide deterministic async graph behavior without network access."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def ainvoke(self, state: dict[str, object]) -> dict[str, object]:
        await asyncio.sleep(0)
        if self.error is not None:
            raise self.error
        return {**state, "ceo_result": ceo_response()}


class BlockingGraph(FakeGraph):
    """Hold concurrent requests so the active-workflow gauge can be inspected."""

    def __init__(self, expected: int) -> None:
        super().__init__()
        self.expected = expected
        self.started = 0
        self.all_started = asyncio.Event()
        self.release = asyncio.Event()

    async def ainvoke(self, state: dict[str, object]) -> dict[str, object]:
        self.started += 1
        if self.started == self.expected:
            self.all_started.set()
        await self.release.wait()
        return {**state, "ceo_result": ceo_response()}


class RaisingMetricsCollector:
    """Exercise failure isolation for optional metrics calls."""

    def increment_counter(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("metrics backend unavailable")

    def observe_histogram(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("metrics backend unavailable")

    def set_gauge(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("metrics backend unavailable")


def test_collector_records_counters_histograms_gauges_and_safe_labels() -> None:
    """All metric primitives should use one isolated explicit registry."""

    registry = CollectorRegistry()
    collector = PrometheusMetricsCollector(
        registry,
        namespace="test",
        subsystem="company",
    )
    fork = collector.fork()

    collector.increment_counter(
        "llm_requests_total",
        labels={
            "agent": "finance",
            "provider": "fake",
            "model": "fixed",
            "status": "success",
        },
    )
    fork.increment_counter(
        "llm_requests_total",
        2,
        {
            "agent": "finance",
            "provider": "fake",
            "model": "fixed",
            "status": "success",
        },
    )
    collector.observe_histogram(
        "llm_latency_seconds",
        0.25,
        {
            "agent": "finance",
            "provider": "fake",
            "model": "fixed",
            "status": "success",
        },
    )
    collector.set_gauge("workflow_active", -1, {"workflow": "company"})

    output = exposition(registry)
    assert 'test_company_llm_requests_total{agent="finance"' in output
    assert 'model="fixed",provider="fake",status="success"} 3.0' in output
    assert "test_company_llm_latency_seconds_sum" in output
    assert 'test_company_workflow_active{workflow="company"} -1.0' in output
    assert collector.registry is registry
    assert fork.registry is registry
    assert isinstance(collector, MetricsCollector)


@pytest.mark.parametrize(
    ("operation", "error", "match"),
    [
        (lambda c: c.increment_counter("unknown"), ValueError, "Unsupported metric"),
        (
            lambda c: c.increment_counter(
                "http_requests_total", labels={"request_id": "secret"}
            ),
            ValueError,
            "Unsupported metric labels",
        ),
        (
            lambda c: c.increment_counter(
                "http_requests_total", labels={"agent": "finance"}
            ),
            ValueError,
            "not valid",
        ),
        (
            lambda c: c.increment_counter(
                "http_requests_total", labels={"status": 200}
            ),
            TypeError,
            "strings",
        ),
        (
            lambda c: c.increment_counter("http_requests_total", True),
            TypeError,
            "values",
        ),
        (
            lambda c: c.increment_counter("http_requests_total", "1"),
            TypeError,
            "values",
        ),
        (
            lambda c: c.increment_counter("http_requests_total", float("inf")),
            ValueError,
            "finite",
        ),
        (
            lambda c: c.increment_counter("http_requests_total", -1),
            ValueError,
            "non-negative",
        ),
        (lambda c: c.observe_histogram("unknown", 1), ValueError, "Unsupported metric"),
        (lambda c: c.set_gauge("unknown", 1), ValueError, "Unsupported metric"),
    ],
)
def test_collector_rejects_unsafe_or_invalid_observations(
    operation: object,
    error: type[Exception],
    match: str,
) -> None:
    """Unknown metrics, unsafe labels, and invalid values must fail closed."""

    collector = PrometheusMetricsCollector(CollectorRegistry())
    with pytest.raises(error, match=match):
        operation(collector)  # type: ignore[operator]


def test_metric_helpers_cover_success_failure_retry_and_failure_isolation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Agent helpers should emit telemetry without changing application outcomes."""

    registry = CollectorRegistry()
    collector = PrometheusMetricsCollector(registry, namespace="helpers")
    record_generation_metrics(
        collector,
        agent="finance",
        provider="fake",
        model="fixed",
        latency_ms=125,
        total_tokens=12,
    )
    record_generation_metrics(
        collector,
        agent="finance",
        provider="fake",
        model="fixed",
        latency_ms=None,
        total_tokens=None,
    )
    record_failed_generation_metrics(collector, agent="finance")
    record_agent_metrics(
        collector,
        agent="finance",
        duration_seconds=0.5,
        retry_count=1,
        success=True,
    )
    record_agent_metrics(
        collector,
        agent="marketing",
        duration_seconds=0.25,
        retry_count=0,
        success=False,
    )
    raising = RaisingMetricsCollector()
    record_generation_metrics(
        raising,
        agent="finance",
        provider="fake",
        model="fixed",
        latency_ms=1,
        total_tokens=1,
    )
    record_failed_generation_metrics(raising, agent="finance")
    record_agent_metrics(
        raising,
        agent="finance",
        duration_seconds=1,
        retry_count=0,
        success=False,
    )

    output = exposition(registry)
    assert "helpers_llm_tokens_total" in output
    assert "helpers_agent_retry_total" in output
    assert "helpers_agent_failures_total" in output
    assert caplog.text.count("metrics failed") == 3


def test_null_collector_and_configuration_are_explicit() -> None:
    """Disabled metrics should retain the protocol and register nothing."""

    disabled = create_metrics_collector(settings())
    assert isinstance(disabled, NullMetricsCollector)
    assert isinstance(disabled, MetricsCollector)
    disabled.increment_counter("anything", labels={"request_id": "ignored"})
    disabled.observe_histogram("anything", -1)
    disabled.set_gauge("anything", -1)

    registry = CollectorRegistry()
    enabled = create_metrics_collector(
        settings(
            METRICS_ENABLED=True,
            METRICS_NAMESPACE="configured",
            METRICS_SUBSYSTEM="runtime",
        ),
        registry=registry,
    )
    assert isinstance(enabled, PrometheusMetricsCollector)
    assert enabled.registry is registry
    assert settings().metrics_enabled is False
    assert settings().metrics_namespace == "autonomous_ai_company"
    assert settings().metrics_subsystem == ""
    with pytest.raises(ValidationError):
        settings(METRICS_NAMESPACE="invalid namespace")
    with pytest.raises(ValidationError):
        settings(METRICS_SUBSYSTEM="invalid subsystem")


def test_context_binding_and_bootstrap_reuse_one_request_collector() -> None:
    """Composition should reuse the facade bound to the active request."""

    configured = settings(METRICS_ENABLED=True)
    collector = PrometheusMetricsCollector(CollectorRegistry())
    assert get_current_metrics_collector() is None
    token = bind_metrics_collector(collector)
    assert get_current_metrics_collector() is collector
    assert _build_metrics_collector(configured) is collector
    reset_metrics_collector(token)
    assert get_current_metrics_collector() is None
    assert isinstance(_build_metrics_collector(settings()), NullMetricsCollector)
    isolated = _build_metrics_collector(configured)
    assert isinstance(isolated, PrometheusMetricsCollector)
    assert isolated is not collector


def test_audit_wrapper_counts_events_failures_and_hides_payloads(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Audit instrumentation should observe only outcomes and stable components."""

    registry = CollectorRegistry()
    collector = PrometheusMetricsCollector(registry, namespace="audit_test")
    logger = MetricsAuditLogger(AuditLogger(), collector)
    logger.log_start("run-1", "finance_agent", payload={"raw_prompt": "secret"})
    assert logger.get_events()[0].run_id == "run-1"
    assert logger._storage is logger._delegate._storage

    failing_delegate = Mock(spec=AuditLogger)
    primary_error = RuntimeError("audit unavailable")
    failing_delegate.log_error.side_effect = primary_error
    failing = MetricsAuditLogger(failing_delegate, collector)
    with pytest.raises(RuntimeError) as captured:
        failing.log_error(run_id="run-1", component="finance_agent")
    assert captured.value is primary_error

    metrics_failing = MetricsAuditLogger(AuditLogger(), RaisingMetricsCollector())
    metrics_failing.log_start("run-2", "marketing_agent")

    output = exposition(registry)
    assert "audit_test_audit_events_total" in output
    assert "audit_test_audit_failures_total" in output
    assert "raw_prompt" not in output
    assert "secret" not in output
    assert "Audit metrics failed" in caplog.text


def test_bootstrap_injects_one_shared_collector_into_every_agent() -> None:
    """The composition root should construct and share one request collector."""

    configured = settings(METRICS_ENABLED=True)
    collector = PrometheusMetricsCollector(CollectorRegistry())
    audit = AuditLogger()
    router = Mock()
    tracking = NullTrackingClient()
    tracer = NullTracer()
    compiled = object()

    with (
        patch(
            "autonomous_ai_company.bootstrap._build_runtime_dependencies",
            return_value=(configured, audit, router, tracking, tracer, collector),
        ),
        patch(
            "autonomous_ai_company.bootstrap.compile_company_graph",
            return_value=compiled,
        ) as compiler,
    ):
        assert compose_graph() is compiled

    arguments = compiler.call_args.kwargs
    for name in (
        "finance_agent",
        "marketing_agent",
        "data_scientist_agent",
        "report_agent",
        "ceo_agent",
    ):
        assert arguments[name]._metrics_collector is collector

    with patch(
        "autonomous_ai_company.bootstrap._build_runtime_dependencies",
        return_value=(configured, audit, router, tracking, tracer, collector),
    ):
        assert build_finance_agent()._metrics_collector is collector


def test_runtime_dependencies_wrap_audit_with_request_metrics() -> None:
    """Enabled composition should create one collector and metric audit decorator."""

    configured = settings(METRICS_ENABLED=True)
    sdk_client = Mock()
    with (
        patch("autonomous_ai_company.bootstrap.get_settings", return_value=configured),
        patch(
            "autonomous_ai_company.bootstrap.get_current_metrics_collector",
            return_value=None,
        ),
        patch(
            "autonomous_ai_company.llm.claude_client.AsyncAnthropic",
            return_value=sdk_client,
        ),
    ):
        dependencies = _build_runtime_dependencies()

    assert len(dependencies) == 6
    assert isinstance(dependencies[1], MetricsAuditLogger)
    assert isinstance(dependencies[5], PrometheusMetricsCollector)


def test_metrics_endpoint_registration_http_workflow_auth_and_isolation() -> None:
    """Enabled API metrics should be public, cumulative, and registry-isolated."""

    configured = settings(
        METRICS_ENABLED=True,
        METRICS_NAMESPACE="api_test",
        METRICS_SUBSYSTEM="service",
    )
    with patch(
        "autonomous_ai_company.api.app.get_settings",
        return_value=configured,
    ):
        app = create_app()
    app.dependency_overrides[get_settings] = lambda: configured
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        username="admin"
    )
    graph = BlockingGraph(expected=4)
    app.dependency_overrides[build_company_graph] = lambda: graph

    async def exercise() -> tuple[str, str]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            health, version = await asyncio.gather(
                client.get("/health"),
                client.get("/version"),
            )
            workflow_tasks = [
                asyncio.create_task(
                    client.post("/workflow/run", json=workflow_payload())
                )
                for _ in range(4)
            ]
            await graph.all_started.wait()
            active_metrics = await client.get("/metrics")
            graph.release.set()
            workflows = await asyncio.gather(*workflow_tasks)
            failed_login = await client.post(
                "/auth/login",
                json={"username": "admin", "password": "wrong"},
            )
            successful_login = await client.post(
                "/auth/login",
                json={"username": "admin", "password": "admin123"},
            )
            metrics = await client.get("/metrics")
        assert health.status_code == 200
        assert version.status_code == 200
        assert all(response.status_code == 200 for response in workflows)
        assert failed_login.status_code == 401
        assert successful_login.status_code == 200
        assert metrics.status_code == 200
        assert metrics.headers["content-type"].startswith("text/plain")
        return active_metrics.text, metrics.text

    active_output, output = asyncio.run(exercise())
    assert 'api_test_service_workflow_active{workflow="company"} 4.0' in active_output
    assert "api_test_service_http_requests_total" in output
    assert "api_test_service_http_request_duration_seconds" in output
    assert (
        'api_test_service_workflow_runs_total{status="success",workflow="company"} 4.0'
        in output
    )
    assert "api_test_service_workflow_duration_seconds" in output
    assert "api_test_service_workflow_success_total" in output
    assert "api_test_service_auth_login_total" in output
    assert "api_test_service_auth_failures_total" in output
    assert 'api_test_service_workflow_active{workflow="company"} 0.0' in output
    assert app.state.metrics_registry is not None
    for forbidden in (
        "raw_prompt",
        "generated_text",
        "jwt",
        "api_key",
        "user_id",
        "request_id",
        "workflow_id",
    ):
        assert forbidden not in output.lower()

    other_registry = CollectorRegistry()
    other = PrometheusMetricsCollector(other_registry, namespace="other")
    other.increment_counter("http_requests_total", labels={"status": "200"})
    assert "api_test" not in exposition(other_registry)
    assert "other_http_requests_total" not in output


def test_disabled_endpoint_and_failed_workflow_metrics() -> None:
    """Disabled applications omit the endpoint; enabled failures are counted."""

    with patch(
        "autonomous_ai_company.api.app.get_settings",
        return_value=settings(),
    ):
        disabled_app = create_app()

    configured = settings(METRICS_ENABLED=True, METRICS_NAMESPACE="failed")
    with patch(
        "autonomous_ai_company.api.app.get_settings",
        return_value=configured,
    ):
        enabled_app = create_app()
    enabled_app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        username="admin"
    )
    enabled_app.dependency_overrides[build_company_graph] = lambda: FakeGraph(
        LLMUnavailableError("offline")
    )

    async def exercise() -> tuple[int, int, str]:
        disabled_transport = httpx.ASGITransport(app=disabled_app)
        enabled_transport = httpx.ASGITransport(app=enabled_app)
        async with (
            httpx.AsyncClient(
                transport=disabled_transport,
                base_url="http://disabled",
            ) as disabled,
            httpx.AsyncClient(
                transport=enabled_transport,
                base_url="http://enabled",
            ) as enabled,
        ):
            absent = await disabled.get("/metrics")
            failed = await enabled.post("/workflow/run", json=workflow_payload())
            metrics = await enabled.get("/metrics")
        return absent.status_code, failed.status_code, metrics.text

    absent_status, failed_status, output = asyncio.run(exercise())
    assert absent_status == 404
    assert failed_status == 503
    assert "failed_workflow_failures_total" in output
    assert (
        'failed_workflow_runs_total{status="failure",workflow="company"} 1.0' in output
    )


def test_metrics_middleware_passes_non_http_scopes_and_propagates_errors() -> None:
    """ASGI adaptation should leave non-HTTP traffic and exceptions unchanged."""

    calls: list[str] = []

    async def downstream(scope: object, receive: object, send: object) -> None:
        del receive, send
        calls.append(scope["type"])  # type: ignore[index]
        if scope["type"] == "http":  # type: ignore[index]
            raise RuntimeError("primary failure")

    collector = PrometheusMetricsCollector(CollectorRegistry())
    middleware = MetricsMiddleware(downstream, collector.fork)

    async def receive() -> dict[str, object]:
        return {}

    async def send(message: object) -> None:
        del message

    async def exercise() -> None:
        await middleware({"type": "lifespan"}, receive, send)  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="primary failure"):
            await middleware(
                {"type": "http", "path": "/workflow/run", "method": "POST"},  # type: ignore[arg-type]
                receive,
                send,
            )

    asyncio.run(exercise())
    assert calls == ["lifespan", "http"]
    assert get_current_metrics_collector() is None
    assert "workflow_failures_total" in exposition(collector.registry)
