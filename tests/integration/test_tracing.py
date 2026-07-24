"""Integration tests for optional provider-neutral OpenTelemetry tracing."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import Mock, patch

import httpx
import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from pydantic import SecretStr, ValidationError

from autonomous_ai_company.agents.ceo_agent import CEOAgent
from autonomous_ai_company.agents.data_scientist_agent import DataScientistAgent
from autonomous_ai_company.agents.finance_agent import FinanceAgent
from autonomous_ai_company.agents.marketing_agent import MarketingAgent
from autonomous_ai_company.agents.report_agent import ReportAgent
from autonomous_ai_company.api.app import create_app
from autonomous_ai_company.api.dependencies import build_company_graph
from autonomous_ai_company.audit.audit_logger import AuditLogger
from autonomous_ai_company.auth.dependencies import get_current_user
from autonomous_ai_company.auth.models import AuthenticatedUser
from autonomous_ai_company.bootstrap import (
    _build_runtime_dependencies,
    _build_tracer,
    build_company_graph as compose_graph,
    build_finance_agent,
)
from autonomous_ai_company.config import Settings
from autonomous_ai_company.observability.trace_models import (
    NullTracer,
    SpanHandle,
    Tracer,
)
from autonomous_ai_company.observability.tracing import (
    OpenTelemetryTracer,
    TracedAuditLogger,
    TracedTrackingClient,
    TracingMiddleware,
    bind_tracer,
    create_tracer,
    get_current_tracer,
    reset_tracer,
)
from autonomous_ai_company.observability.tracking_models import (
    AgentTracking,
    NullTrackingClient,
    TrackingClient,
    WorkflowTracking,
)


PROMPT_HASH = f"sha256:{'b' * 64}"


def settings(**overrides: object) -> Settings:
    """Build isolated runtime configuration without reading local files."""

    values: dict[str, object] = {
        "ANTHROPIC_API_KEY": SecretStr("test-api-key"),
        "MODEL_NAME": "test-model",
        "TEMPERATURE": 0.0,
        "MAX_TOKENS": 256,
        "LOG_LEVEL": "INFO",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def workflow_payload() -> dict[str, object]:
    """Return a complete workflow request for API tracing tests."""

    return {
        "dataset": [{"revenue": 100, "cost": 60}],
        "previous_dataset": [{"revenue": 80, "cost": 50}],
        "data_scientist_series": [10, 20, 30],
        "business_context": "Controlled growth.",
        "executive_question": "What comes next?",
    }


def ceo_response() -> dict[str, object]:
    """Return a valid terminal response for the API adapter."""

    return {
        "executive_summary": "Proceed carefully.",
        "business_health": "stable",
        "strategic_priorities": ["Protect margin."],
        "key_risks": ["Demand volatility."],
        "final_recommendation": "Use staged investment.",
        "confidence_score": 0.9,
    }


def test_trace_handle_and_null_tracer_are_strict_complete_contracts() -> None:
    """Disabled tracing should retain typed handles and zero side effects."""

    tracer = NullTracer()
    span = tracer.start_span("agent.finance", {"run_id": "run-1"})

    assert isinstance(tracer, Tracer)
    assert span.model_dump_json() == (
        '{"handle_id":"null:agent.finance","name":"agent.finance"}'
    )
    tracer.set_attribute(span, "success", True)
    tracer.record_exception(span, RuntimeError("ignored"))
    tracer.end_span(span)
    with pytest.raises(ValidationError):
        span.name = "changed"
    with pytest.raises(ValidationError):
        SpanHandle(handle_id="", name="invalid")


def test_open_telemetry_records_safe_hierarchy_attributes_and_exceptions() -> None:
    """The adapter should export correlated spans without sensitive values."""

    exporter = InMemorySpanExporter()
    tracer = OpenTelemetryTracer("trace-test", span_exporter=exporter)
    root = tracer.start_span(
        "http.request",
        {
            "http.method": "POST",
            "raw_prompt": "ignore this",
        },
    )
    workflow = tracer.start_span("workflow.execute")
    agent = tracer.start_span(
        "agent.finance",
        {
            "workflow_id": "workflow-1",
            "run_id": "workflow-1",
            "agent_name": "finance_agent",
            "prompt_hash": PROMPT_HASH,
            "password": "never-store",
        },
    )
    tracer.set_attribute(agent, "provider", "fake")
    tracer.set_attribute(agent, "model", "deterministic")
    tracer.set_attribute(agent, "run_id", "workflow-1")
    tracer.set_attribute(agent, "prompt_hash", "raw prompt")
    tracer.set_attribute(agent, "api_key", "never-store")
    tracer.record_exception(agent, RuntimeError("password=secret"))
    tracer.end_span(agent)
    tracer.set_attribute(workflow, "success", False)
    tracer.end_span(workflow)
    tracer.set_attribute(root, "http.status_code", 500)
    tracer.end_span(root)
    tracer.shutdown()

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert (
        spans["workflow.execute"].parent.span_id
        == spans["http.request"].context.span_id
    )
    assert (
        spans["agent.finance"].parent.span_id
        == spans["workflow.execute"].context.span_id
    )
    assert spans["http.request"].attributes["run_id"] == "workflow-1"
    assert spans["workflow.execute"].attributes["workflow_id"] == "workflow-1"
    assert spans["agent.finance"].attributes["prompt_hash"] == PROMPT_HASH
    assert spans["agent.finance"].attributes["provider"] == "fake"
    assert spans["agent.finance"].attributes["model"] == "deterministic"
    assert spans["agent.finance"].attributes["duration_ms"] >= 0
    assert "raw_prompt" not in spans["http.request"].attributes
    assert "password" not in spans["agent.finance"].attributes
    assert "api_key" not in spans["agent.finance"].attributes
    exception_event = spans["agent.finance"].events[0]
    assert exception_event.name == "exception"
    assert exception_event.attributes == {"exception.type": "RuntimeError"}
    assert "secret" not in str(exception_event.attributes)
    assert spans["agent.finance"].status.status_code.name == "ERROR"

    with pytest.raises(ValueError, match="not active"):
        tracer.set_attribute(agent, "success", True)
    with pytest.raises(ValueError, match="not active"):
        tracer.record_exception(agent, RuntimeError())
    with pytest.raises(ValueError, match="not active"):
        tracer.end_span(agent)
    tracer._propagate_identity("missing-handle", "run_id", "run-2")


def test_exporter_selection_and_configuration_are_explicit() -> None:
    """Console and OTLP selection should stay inside infrastructure."""

    console = OpenTelemetryTracer("console-test", exporter="console")
    span = console.start_span("console.span")
    console.end_span(span)
    console.shutdown()

    with patch(
        "autonomous_ai_company.observability.tracing.OTLPSpanExporter",
        return_value=InMemorySpanExporter(),
    ) as exporter_factory:
        otlp = OpenTelemetryTracer(
            "otlp-test",
            exporter="otlp",
            otlp_endpoint="http://collector.invalid/v1/traces",
        )
        otlp.shutdown()
    exporter_factory.assert_called_once_with(
        endpoint="http://collector.invalid/v1/traces"
    )

    with pytest.raises(ValueError, match="endpoint"):
        OpenTelemetryTracer("missing-endpoint", exporter="otlp")
    with pytest.raises(ValueError, match="Unsupported"):
        OpenTelemetryTracer("invalid-exporter", exporter="unknown")


def test_create_tracer_disabled_enabled_and_context_binding() -> None:
    """Configuration and request context should select one reusable tracer."""

    disabled = create_tracer(settings())
    assert isinstance(disabled, NullTracer)
    assert get_current_tracer() is None

    exporter = InMemorySpanExporter()
    enabled = create_tracer(
        settings(OTEL_ENABLED=True),
        span_exporter=exporter,
    )
    assert isinstance(enabled, OpenTelemetryTracer)
    token = bind_tracer(enabled)
    assert get_current_tracer() is enabled
    assert _build_tracer(settings(OTEL_ENABLED=True)) is enabled
    reset_tracer(token)
    assert get_current_tracer() is None
    enabled.shutdown()

    with patch(
        "autonomous_ai_company.bootstrap.create_tracer",
        return_value=Mock(spec=Tracer),
    ) as factory:
        created = _build_tracer(settings(OTEL_ENABLED=True))
    assert created is factory.return_value
    factory.assert_called_once()
    assert isinstance(_build_tracer(settings()), NullTracer)


def test_otlp_configuration_requires_an_endpoint_only_when_used() -> None:
    """Disabled or console tracing must not require collector configuration."""

    assert settings(OTEL_EXPORTER="otlp").otel_enabled is False
    assert (
        settings(OTEL_ENABLED=True, OTEL_EXPORTER="console").otel_otlp_endpoint is None
    )
    with pytest.raises(ValidationError, match="OTEL_OTLP_ENDPOINT"):
        settings(OTEL_ENABLED=True, OTEL_EXPORTER="otlp")


def test_audit_and_tracking_wrappers_create_safe_child_spans() -> None:
    """Existing infrastructure APIs should propagate context through wrappers."""

    exporter = InMemorySpanExporter()
    tracer = OpenTelemetryTracer("wrapper-test", span_exporter=exporter)
    agent = tracer.start_span("agent.finance")
    audit = TracedAuditLogger(AuditLogger(), tracer)
    audit.log_start("run-1", "finance_agent", payload={"dataset_size": 1})
    assert audit.get_events()[0].run_id == "run-1"
    assert audit._storage is audit._delegate._storage

    tracking = TracedTrackingClient(NullTrackingClient(), tracer)
    workflow_handle = tracking.start_run(
        WorkflowTracking(run_id="run-1", started_at=datetime.now(UTC))
    )
    agent_handle = tracking.start_run(
        AgentTracking(
            workflow_run_id="run-1",
            agent_name="finance_agent",
            started_at=datetime.now(UTC),
        )
    )
    tracking.log_metrics(agent_handle, {"latency_ms": 2})
    tracking.log_params(
        agent_handle,
        {
            "provider": "fake",
            "model_name": "model",
            "prompt_hash_attempt_1": PROMPT_HASH,
            "raw_prompt": "do not trace",
        },
    )
    tracking.log_params(agent_handle, {"provider": 1, "model_name": False})
    tracking.log_tags(agent_handle, {"status": "FINISHED"})
    tracking.log_artifact(agent_handle, "ceo_report.json", "generated text")
    tracking.end_run(agent_handle)
    tracking.end_run(workflow_handle, "KILLED")
    tracer.end_span(agent)
    tracer.shutdown()

    spans = exporter.get_finished_spans()
    names = [span.name for span in spans]
    assert "audit.log_start" in names
    assert "audit.get_events" in names
    assert names.count("mlflow.start_run") == 2
    assert "mlflow.log_metrics" in names
    assert "mlflow.log_params" in names
    assert "mlflow.log_tags" in names
    assert "mlflow.log_artifact" in names
    assert names.count("mlflow.end_run") == 2
    parameter_spans = [span for span in spans if span.name == "mlflow.log_params"]
    assert parameter_spans[0].attributes["prompt_hash"] == PROMPT_HASH
    serialized = " ".join(str(span.attributes) for span in spans)
    assert "raw_prompt" not in serialized
    assert "generated text" not in serialized


def test_wrappers_record_and_propagate_delegate_exceptions() -> None:
    """Tracing must observe infrastructure failures without swallowing them."""

    exporter = InMemorySpanExporter()
    tracer = OpenTelemetryTracer("failure-test", span_exporter=exporter)
    audit_delegate = Mock(spec=AuditLogger)
    audit_delegate.log_error.side_effect = RuntimeError("password=hidden")
    audit = TracedAuditLogger(audit_delegate, tracer)
    with pytest.raises(RuntimeError, match="password"):
        audit.log_error("run-1", "finance_agent")

    tracking_delegate = Mock(spec=TrackingClient)
    tracking_delegate.log_tags.side_effect = RuntimeError("jwt=hidden")
    tracking = TracedTrackingClient(tracking_delegate, tracer)
    with pytest.raises(RuntimeError, match="jwt"):
        tracking.log_tags("handle", {"status": "FAILED"})
    tracer.shutdown()

    failed = exporter.get_finished_spans()
    assert {span.name for span in failed} == {"audit.log_error", "mlflow.log_tags"}
    for span in failed:
        assert span.status.status_code.name == "ERROR"
        assert span.events[0].attributes == {"exception.type": "RuntimeError"}
        assert "hidden" not in str(span.events[0].attributes)


class TracingGraph:
    """Create deterministic agent-like spans inside the existing graph boundary."""

    async def ainvoke(self, state: dict[str, object]) -> dict[str, object]:
        """Exercise parallel and sequential trace context propagation."""

        tracer = get_current_tracer()
        assert tracer is not None
        metadata = state["metadata"]
        assert isinstance(metadata, dict)
        run_id = metadata["run_id"]
        assert isinstance(run_id, str)

        async def specialist(agent_name: str) -> None:
            span = tracer.start_span(
                f"agent.{agent_name}",
                {
                    "workflow_id": run_id,
                    "run_id": run_id,
                    "agent_name": agent_name,
                    "provider": "fake",
                    "model": "deterministic",
                    "prompt_hash": PROMPT_HASH,
                    "retry_count": 0,
                },
            )
            await asyncio.sleep(0)
            audit = TracedAuditLogger(AuditLogger(), tracer)
            audit.log_start(run_id, agent_name)
            tracking = TracedTrackingClient(NullTrackingClient(), tracer)
            tracking.log_params(
                "handle",
                {
                    "provider": "fake",
                    "model_name": "deterministic",
                    "prompt_hash_attempt_1": PROMPT_HASH,
                    "raw_prompt": "never trace",
                },
            )
            tracer.set_attribute(span, "success", True)
            tracer.end_span(span)

        await asyncio.gather(
            specialist("finance_agent"),
            specialist("marketing_agent"),
            specialist("data_scientist_agent"),
        )
        await specialist("report_agent")
        await specialist("ceo_agent")
        return {"ceo_result": ceo_response()}


def test_http_workflow_hierarchy_and_concurrent_requests() -> None:
    """Concurrent API workflows should create isolated traces with shared shape."""

    exporter = InMemorySpanExporter()
    created_tracers: list[OpenTelemetryTracer] = []

    def tracer_factory(*args: object, **kwargs: object) -> OpenTelemetryTracer:
        del args, kwargs
        tracer = OpenTelemetryTracer("api-test", span_exporter=exporter)
        created_tracers.append(tracer)
        return tracer

    configured = settings(OTEL_ENABLED=True)
    with (
        patch(
            "autonomous_ai_company.api.app.get_settings",
            return_value=configured,
        ),
        patch(
            "autonomous_ai_company.api.app.create_tracer",
            side_effect=tracer_factory,
        ),
    ):
        app = create_app()
        app.dependency_overrides[build_company_graph] = lambda: TracingGraph()
        app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            username="admin"
        )

        async def execute() -> list[httpx.Response]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                return await asyncio.gather(
                    client.post("/workflow/run", json=workflow_payload()),
                    client.post("/workflow/run", json=workflow_payload()),
                )

        responses = asyncio.run(execute())

    for tracer in created_tracers:
        tracer.shutdown()
    assert [response.status_code for response in responses] == [200, 200]
    spans = exporter.get_finished_spans()
    roots = [span for span in spans if span.name == "http.request"]
    workflows = [span for span in spans if span.name == "workflow.execute"]
    assert len(roots) == len(workflows) == 2
    assert len({span.context.trace_id for span in roots}) == 2
    for workflow in workflows:
        root = next(
            span for span in roots if span.context.trace_id == workflow.context.trace_id
        )
        assert workflow.parent.span_id == root.context.span_id
        trace_spans = [
            span for span in spans if span.context.trace_id == root.context.trace_id
        ]
        agents = [span for span in trace_spans if span.name.startswith("agent.")]
        assert len(agents) == 5
        assert all(span.parent.span_id == workflow.context.span_id for span in agents)
        assert all(span.attributes["success"] is True for span in agents)
        assert all(span.attributes["prompt_hash"] == PROMPT_HASH for span in agents)
        assert root.attributes["run_id"] == workflow.attributes["run_id"]
        audit_spans = [span for span in trace_spans if span.name.startswith("audit.")]
        mlflow_spans = [span for span in trace_spans if span.name.startswith("mlflow.")]
        agent_ids = {span.context.span_id for span in agents}
        assert all(span.parent.span_id in agent_ids for span in audit_spans)
        assert all(span.parent.span_id in agent_ids for span in mlflow_spans)
    serialized = " ".join(str(span.attributes) for span in spans)
    assert "raw_prompt" not in serialized
    assert "generated_text" not in serialized
    assert "password" not in serialized
    assert "api_key" not in serialized
    assert "jwt" not in serialized


class FailingTracer(NullTracer):
    """Fail only during finalization to exercise agent protection."""

    def end_span(self, span: SpanHandle) -> None:
        """Simulate an unavailable trace exporter."""

        raise RuntimeError("tracing unavailable")


@pytest.mark.parametrize(
    "agent_name",
    ["finance", "marketing", "data_scientist", "report", "ceo"],
)
def test_agents_preserve_primary_errors_when_tracing_finalization_fails(
    agent_name: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Tracing failures must never replace deterministic application failures."""

    provider = Mock()
    audit = AuditLogger()
    tracer = FailingTracer()
    if agent_name == "finance":
        operation = FinanceAgent(provider, audit, tracer=tracer).run(
            "trace-failure", (), (), "context"
        )
    elif agent_name == "marketing":
        operation = MarketingAgent(provider, audit, tracer=tracer).run(
            "trace-failure", (), (), "context"
        )
    elif agent_name == "data_scientist":
        operation = DataScientistAgent(provider, audit, tracer=tracer).run(
            "trace-failure", (), "context"
        )
    elif agent_name == "report":
        operation = ReportAgent(provider, audit, tracer=tracer).run(
            "trace-failure",
            object(),
            None,
            None,  # type: ignore[arg-type]
        )
    else:
        operation = CEOAgent(provider, audit, tracer=tracer).run(
            "trace-failure",
            object(),
            None,
            None,
            None,  # type: ignore[arg-type]
        )

    with pytest.raises(Exception) as captured:
        asyncio.run(operation)

    assert type(captured.value) is not RuntimeError
    assert "tracing finalization failed: RuntimeError" in caplog.text


def test_tracing_middleware_bypasses_non_http_and_records_failures() -> None:
    """ASGI lifespan traffic is untouched and unhandled HTTP errors are traced."""

    calls: list[str] = []

    async def app(scope: object, receive: object, send: object) -> None:
        del receive, send
        assert isinstance(scope, dict)
        calls.append(scope["type"])
        if scope["type"] == "http":
            raise RuntimeError("password=hidden")

    exporter = InMemorySpanExporter()
    tracer = OpenTelemetryTracer("middleware-test", span_exporter=exporter)
    middleware = TracingMiddleware(app, lambda: tracer)  # type: ignore[arg-type]

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: object) -> None:
        del message

    asyncio.run(middleware({"type": "lifespan"}, receive, send))  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="password"):
        asyncio.run(
            middleware(
                {"type": "http", "path": "/workflow/run", "method": "POST"},
                receive,
                send,
            )
        )  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="password"):
        asyncio.run(
            middleware(
                {"type": "http", "path": "/health", "method": "GET"},
                receive,
                send,
            )
        )  # type: ignore[arg-type]
    tracer.shutdown()

    assert calls == ["lifespan", "http", "http"]
    finished = exporter.get_finished_spans()
    spans = {span.name: span for span in finished}
    assert all(
        span.status.status_code.name == "ERROR"
        for span in finished
        if span.name == "http.request"
    )
    assert spans["workflow.execute"].status.status_code.name == "ERROR"
    assert spans["http.request"].attributes["success"] is False
    assert "hidden" not in str(spans["http.request"].events[0].attributes)


def test_bootstrap_injects_one_shared_request_scoped_tracer() -> None:
    """All graph agents should receive one tracer selected by composition."""

    configured = settings(OTEL_ENABLED=True)
    tracer = Mock(spec=Tracer)
    with (
        patch(
            "autonomous_ai_company.bootstrap.get_settings",
            return_value=configured,
        ),
        patch(
            "autonomous_ai_company.bootstrap.create_tracer",
            return_value=tracer,
        ),
        patch(
            "autonomous_ai_company.llm.claude_client.AsyncAnthropic",
            return_value=Mock(),
        ),
    ):
        graph = compose_graph()

    nodes = [
        graph.nodes[name].bound.afunc
        for name in ("finance", "marketing", "data_scientist", "report", "ceo")
    ]
    assert {id(node._agent._tracer) for node in nodes} == {id(tracer)}
    assert all(
        isinstance(node._agent._audit_logger, TracedAuditLogger) for node in nodes
    )
    assert all(
        not isinstance(node._agent._tracking_client, TracedTrackingClient)
        for node in nodes
    )


def test_bootstrap_wraps_mlflow_and_builds_an_enabled_standalone_agent() -> None:
    """Enabled observability adapters should share the composed tracer."""

    configured = settings(
        OTEL_ENABLED=True,
        MLFLOW_ENABLED=True,
        MLFLOW_TRACKING_URI="file:///unused",
    )
    tracer = Mock(spec=Tracer)
    tracking = Mock(spec=TrackingClient)
    with (
        patch(
            "autonomous_ai_company.bootstrap.get_settings",
            return_value=configured,
        ),
        patch(
            "autonomous_ai_company.bootstrap._build_tracer",
            return_value=tracer,
        ),
        patch(
            "autonomous_ai_company.bootstrap._build_tracking_client",
            return_value=tracking,
        ),
        patch(
            "autonomous_ai_company.llm.claude_client.AsyncAnthropic",
            return_value=Mock(),
        ),
    ):
        runtime = _build_runtime_dependencies()
    assert isinstance(runtime[3], TracedTrackingClient)
    assert runtime[3]._delegate is tracking
    assert runtime[3]._tracer is tracer

    audit = Mock()
    router = Mock()
    expected = Mock()
    with (
        patch(
            "autonomous_ai_company.bootstrap._build_runtime_dependencies",
            return_value=(configured, audit, router, tracking, tracer),
        ),
        patch(
            "autonomous_ai_company.bootstrap.FinanceAgent",
            return_value=expected,
        ) as agent_factory,
    ):
        result = build_finance_agent()
    assert result is expected
    agent_factory.assert_called_once_with(
        llm_provider=router,
        audit_logger=audit,
        tracking_client=tracking,
        tracer=tracer,
    )
