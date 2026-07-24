"""Assemble concrete application dependencies in one composition root.

Keeping construction here lets business modules depend on injected contracts
without knowing configuration loading, provider adapters, or storage choices.
Future agents can reuse this module's shared runtime dependencies while leaving
their orchestration and domain logic unchanged.
"""

from autonomous_ai_company.agents.finance_agent import FinanceAgent
from autonomous_ai_company.agents.ceo_agent import CEOAgent
from autonomous_ai_company.agents.data_scientist_agent import DataScientistAgent
from autonomous_ai_company.agents.marketing_agent import MarketingAgent
from autonomous_ai_company.agents.report_agent import ReportAgent
from autonomous_ai_company.audit.audit_logger import (
    AuditLogger,
    AuditStorage,
    InMemoryAuditStorage,
)
from autonomous_ai_company.audit.postgres_storage import PostgresAuditStorage
from autonomous_ai_company.config import Settings, get_settings
from autonomous_ai_company.graph.graph_builder import (
    build_company_graph as compile_company_graph,
)
from autonomous_ai_company.llm.llm_router import LLMRouter
from autonomous_ai_company.llm.provider_factory import build_provider_factories
from autonomous_ai_company.observability.mlflow_tracker import MLflowTrackingClient
from autonomous_ai_company.observability.metrics import (
    MetricsAuditLogger,
    create_metrics_collector,
    get_current_metrics_collector,
)
from autonomous_ai_company.observability.metrics_models import (
    MetricsCollector,
    NullMetricsCollector,
)
from autonomous_ai_company.observability.trace_models import NullTracer, Tracer
from autonomous_ai_company.observability.tracing import (
    TracedAuditLogger,
    TracedTrackingClient,
    create_tracer,
    get_current_tracer,
)
from autonomous_ai_company.observability.tracking_models import (
    NullTrackingClient,
    TrackingClient,
)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph


def _build_audit_storage(settings: Settings) -> AuditStorage:
    """Select the configured audit adapter at the composition boundary."""

    if getattr(settings, "postgres_enabled", False) is not True:
        return InMemoryAuditStorage()
    assert settings.postgres_host is not None
    assert settings.postgres_port is not None
    assert settings.postgres_database is not None
    assert settings.postgres_user is not None
    assert settings.postgres_password is not None
    return PostgresAuditStorage(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_database,
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
    )


def _build_tracking_client(settings: Settings) -> TrackingClient:
    """Select one request-scoped tracking adapter at the composition root."""

    if getattr(settings, "mlflow_enabled", False) is not True:
        return NullTrackingClient()
    assert settings.mlflow_tracking_uri is not None
    return MLflowTrackingClient(
        tracking_uri=settings.mlflow_tracking_uri,
        experiment_name=settings.mlflow_experiment_name,
        artifact_location=settings.mlflow_artifact_location,
    )


def _build_tracer(settings: Settings) -> Tracer:
    """Reuse the request tracer or create one for non-HTTP composition."""

    current = get_current_tracer()
    if current is not None:
        return current
    if getattr(settings, "otel_enabled", False) is not True:
        return NullTracer()
    return create_tracer(settings)


def _build_metrics_collector(settings: Settings) -> MetricsCollector:
    """Reuse request metrics or create an isolated non-HTTP collector."""

    current = get_current_metrics_collector()
    if current is not None:
        return current
    if getattr(settings, "metrics_enabled", False) is not True:
        return NullMetricsCollector()
    return create_metrics_collector(settings)


def _build_runtime_dependencies() -> tuple[
    Settings,
    AuditLogger | TracedAuditLogger,
    LLMRouter,
    TrackingClient,
    Tracer,
    MetricsCollector,
]:
    """Construct shared audit, provider, tracking, tracing, and metrics."""

    settings = get_settings()
    tracer = _build_tracer(settings)
    metrics_collector = _build_metrics_collector(settings)
    audit_storage = _build_audit_storage(settings)
    base_audit_logger = AuditLogger(storage=audit_storage)
    audit_logger: AuditLogger | TracedAuditLogger = base_audit_logger
    if getattr(settings, "otel_enabled", False) is True:
        audit_logger = TracedAuditLogger(base_audit_logger, tracer)
    if getattr(settings, "metrics_enabled", False) is True:
        audit_logger = MetricsAuditLogger(audit_logger, metrics_collector)
    llm_router = LLMRouter(
        provider_name=settings.llm_provider,
        provider_factories=build_provider_factories(settings),
    )
    tracking_client = _build_tracking_client(settings)
    if (
        getattr(settings, "otel_enabled", False) is True
        and getattr(settings, "mlflow_enabled", False) is True
    ):
        tracking_client = TracedTrackingClient(tracking_client, tracer)
    return (
        settings,
        audit_logger,
        llm_router,
        tracking_client,
        tracer,
        metrics_collector,
    )


def build_finance_agent() -> FinanceAgent:
    """Return one fully configured Finance Agent dependency graph.

    Every runtime component is constructed locally and injected through its
    constructor. Nothing is retained at module scope, so application entry
    points and tests control object lifetimes explicitly.
    """

    runtime_dependencies = _build_runtime_dependencies()
    settings, audit_logger, llm_router, tracking_client = runtime_dependencies[:4]
    tracer = (
        runtime_dependencies[4]
        if len(runtime_dependencies) >= 5
        else _build_tracer(settings)
    )
    metrics_collector = (
        runtime_dependencies[5]
        if len(runtime_dependencies) >= 6
        else _build_metrics_collector(settings)
    )
    if getattr(settings, "metrics_enabled", False) is True:
        return FinanceAgent(
            llm_provider=llm_router,
            audit_logger=audit_logger,
            tracking_client=tracking_client,
            tracer=tracer,
            metrics_collector=metrics_collector,
        )
    if getattr(settings, "otel_enabled", False) is True:
        return FinanceAgent(
            llm_provider=llm_router,
            audit_logger=audit_logger,
            tracking_client=tracking_client,
            tracer=tracer,
        )
    if getattr(settings, "mlflow_enabled", False) is True:
        return FinanceAgent(
            llm_provider=llm_router,
            audit_logger=audit_logger,
            tracking_client=tracking_client,
        )
    return FinanceAgent(llm_provider=llm_router, audit_logger=audit_logger)


def build_company_graph() -> CompiledStateGraph:
    """Return a complete company graph from one shared dependency runtime.

    The composition root owns all concrete construction. API adapters receive
    only the compiled graph and therefore never need to know about providers,
    audit storage, agent constructors, or checkpoint implementations.
    """

    settings, audit_logger, llm_router, tracking_client, tracer, metrics_collector = (
        _build_runtime_dependencies()
    )
    checkpointer = InMemorySaver() if settings.checkpointing_enabled else None
    return compile_company_graph(
        finance_agent=FinanceAgent(
            llm_router,
            audit_logger,
            tracking_client,
            tracer,
            metrics_collector,
        ),
        marketing_agent=MarketingAgent(
            llm_router,
            audit_logger,
            tracking_client,
            tracer,
            metrics_collector,
        ),
        data_scientist_agent=DataScientistAgent(
            llm_router,
            audit_logger,
            tracking_client,
            tracer,
            metrics_collector,
        ),
        report_agent=ReportAgent(
            llm_router,
            audit_logger,
            tracking_client,
            tracer,
            metrics_collector,
        ),
        ceo_agent=CEOAgent(
            llm_router,
            audit_logger,
            tracking_client,
            tracer,
            metrics_collector,
        ),
        settings=settings,
        checkpointer=checkpointer,
    )
