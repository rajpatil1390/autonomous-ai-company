"""Create the FastAPI application and its transport-level error mappings."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from autonomous_ai_company.api.auth_routes import create_auth_router
from autonomous_ai_company.api.routes import create_router
from autonomous_ai_company.config import get_settings
from autonomous_ai_company.exceptions import (
    ConfigurationError,
    InvalidDatasetError,
    LLMError,
    UndefinedMetricError,
)
from autonomous_ai_company.observability.trace_models import NullTracer, Tracer
from autonomous_ai_company.observability.tracing import TracingMiddleware, create_tracer
from autonomous_ai_company.observability.metrics import (
    MetricsMiddleware,
    PrometheusMetricsCollector,
    create_metrics_collector,
    create_metrics_router,
)


def _request_tracer_factory() -> Tracer:
    """Create one tracer per request from centralized runtime configuration."""

    try:
        settings = get_settings()
    except ConfigurationError:
        return NullTracer()
    return create_tracer(settings)


async def _invalid_request_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    """Translate deterministic input failures into HTTP 400 responses."""

    del request
    return JSONResponse(status_code=400, content={"detail": str(error)})


async def _provider_error_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    """Hide provider details behind a stable service-unavailable response."""

    del request, error
    return JSONResponse(
        status_code=503,
        content={"detail": "LLM provider unavailable"},
    )


async def _unexpected_error_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    """Prevent unexpected internal exception details from crossing HTTP."""

    del request, error
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


def create_app() -> FastAPI:
    """Build a fresh FastAPI adapter with no module-level application state."""

    app = FastAPI(
        title="Autonomous AI Company",
        version="1.0.0",
    )
    app.add_middleware(
        TracingMiddleware,
        tracer_factory=_request_tracer_factory,
    )
    try:
        settings = get_settings()
    except ConfigurationError:
        settings = None
    metrics_collector = (
        create_metrics_collector(settings) if settings is not None else None
    )
    if isinstance(metrics_collector, PrometheusMetricsCollector):
        app.state.metrics_registry = metrics_collector.registry
        app.add_middleware(
            MetricsMiddleware,
            collector_factory=metrics_collector.fork,
        )
        app.include_router(create_metrics_router(metrics_collector.registry))
    app.include_router(create_auth_router())
    app.include_router(create_router())
    app.add_exception_handler(InvalidDatasetError, _invalid_request_handler)
    app.add_exception_handler(UndefinedMetricError, _invalid_request_handler)
    app.add_exception_handler(LLMError, _provider_error_handler)
    app.add_exception_handler(Exception, _unexpected_error_handler)
    return app
