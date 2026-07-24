"""Integration tests for the thin FastAPI application adapter."""

import asyncio
from copy import deepcopy
from unittest.mock import Mock, patch
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver

from autonomous_ai_company.api.app import _request_tracer_factory, create_app
from autonomous_ai_company.api.dependencies import build_company_graph
from autonomous_ai_company.auth.dependencies import get_current_user
from autonomous_ai_company.auth.models import AuthenticatedUser
from autonomous_ai_company.bootstrap import (
    build_company_graph as build_bootstrap_company_graph,
)
from autonomous_ai_company.config import Settings
from autonomous_ai_company.exceptions import (
    ConfigurationError,
    InvalidDatasetError,
    LLMUnavailableError,
    UndefinedMetricError,
)
from autonomous_ai_company.observability.trace_models import NullTracer


def workflow_payload() -> dict[str, object]:
    """Return a complete request without derived analytical inputs."""

    return {
        "dataset": [
            {
                "revenue": 100,
                "cost": 60,
                "customer_id": "c1",
                "segment": "Enterprise",
            }
        ],
        "previous_dataset": [
            {
                "revenue": 80,
                "cost": 50,
                "customer_id": "c1",
                "segment": "Enterprise",
            }
        ],
        "data_scientist_series": [10, 20, 30],
        "business_context": "Subscription company planning controlled growth.",
        "executive_question": "Which priority should be approved?",
    }


def ceo_response() -> dict[str, object]:
    """Return one valid serialized CEOAgentOutput document."""

    return {
        "executive_summary": "Pursue controlled growth.",
        "business_health": "stable",
        "strategic_priorities": ["Invest with safeguards."],
        "key_risks": ["Costs may rise."],
        "final_recommendation": "Approve a staged investment.",
        "confidence_score": 0.9,
    }


class FakeGraph:
    """Capture asynchronous state invocation without network activity."""

    def __init__(
        self,
        *,
        result: dict[str, object] | None = None,
        error: Exception | None = None,
    ) -> None:
        """Configure one deterministic result or failure."""

        self.result = {"ceo_result": ceo_response()} if result is None else result
        self.error = error
        self.states: list[dict[str, object]] = []

    async def ainvoke(self, state: dict[str, object]) -> dict[str, object]:
        """Yield once to prove async execution, then return configured output."""

        await asyncio.sleep(0)
        self.states.append(deepcopy(state))
        if self.error is not None:
            raise self.error
        return self.result


def app_for(graph: FakeGraph) -> FastAPI:
    """Create an isolated application with one overridden graph dependency."""

    app = create_app()
    app.dependency_overrides[build_company_graph] = lambda: graph
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        username="admin"
    )
    return app


async def api_request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json: dict[str, object] | None = None,
) -> httpx.Response:
    """Send one request directly through HTTPX's asynchronous ASGI transport."""

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.request(method, path, json=json)


def configured_settings(*, checkpointing_enabled: bool = False) -> Settings:
    """Return complete runtime settings without reading local environment."""

    return Settings(
        ANTHROPIC_API_KEY="test-api-key",
        MODEL_NAME="test-model",
        TEMPERATURE=0.0,
        MAX_TOKENS=100,
        LOG_LEVEL="INFO",
        CHECKPOINTING_ENABLED=checkpointing_enabled,
        _env_file=None,
    )


def test_application_starts_and_exposes_health_and_version() -> None:
    """A fresh app should expose stable liveness and identity contracts."""

    app = create_app()

    health = asyncio.run(api_request(app, "GET", "/health"))
    version = asyncio.run(api_request(app, "GET", "/version"))
    schema = asyncio.run(api_request(app, "GET", "/openapi.json"))

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert version.status_code == 200
    assert version.json() == {
        "application": "Autonomous AI Company",
        "version": "1.0.0",
    }
    assert schema.status_code == 200
    assert "/workflow/run" in schema.json()["paths"]
    assert schema.json()["components"]["securitySchemes"] == {
        "HTTPBearer": {
            "type": "http",
            "scheme": "bearer",
        }
    }


def test_application_uses_safe_adapters_when_configuration_is_invalid() -> None:
    """Public startup should retain health routes without optional adapters."""

    with patch(
        "autonomous_ai_company.api.app.get_settings",
        side_effect=ConfigurationError("invalid local configuration"),
    ):
        app = create_app()
        tracer = _request_tracer_factory()

    assert isinstance(tracer, NullTracer)
    assert not hasattr(app.state, "metrics_registry")


def test_workflow_invokes_injected_graph_and_returns_validated_ceo_output() -> None:
    """The endpoint should map supplied values unchanged into shared state."""

    graph = FakeGraph()
    payload = workflow_payload()

    response = asyncio.run(
        api_request(app_for(graph), "POST", "/workflow/run", json=payload)
    )

    assert response.status_code == 200
    assert response.json() == ceo_response()
    assert len(graph.states) == 1
    state = graph.states[0]
    assert state["dataset"] == payload["dataset"]
    assert state["audit_events"] == []
    assert state["generation_results"] == []
    assert state["execution_status"] == "pending"
    assert state["errors"] == []
    metadata = state["metadata"]
    assert isinstance(metadata, dict)
    UUID(str(metadata["run_id"]))
    assert metadata["previous_dataset"] == payload["previous_dataset"]
    assert metadata["data_scientist_series"] == payload["data_scientist_series"]
    assert metadata["business_context"] == payload["business_context"]
    assert metadata["executive_question"] == payload["executive_question"]


def test_optional_request_values_use_transport_defaults_only() -> None:
    """Omitted narrative inputs should not fabricate analytical values."""

    graph = FakeGraph()
    payload = workflow_payload()
    del payload["business_context"]
    del payload["executive_question"]

    response = asyncio.run(
        api_request(app_for(graph), "POST", "/workflow/run", json=payload)
    )

    assert response.status_code == 200
    metadata = graph.states[0]["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["business_context"] == ""
    assert metadata["executive_question"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {
            "dataset": [],
            "data_scientist_series": [1, 2],
        },
        {
            **workflow_payload(),
            "data_scientist_series": [1, "not-a-number"],
        },
        {
            **workflow_payload(),
            "unsupported": True,
        },
    ],
)
def test_request_schema_failures_return_422(payload: dict[str, object]) -> None:
    """Missing, incorrectly typed, and unknown fields must be rejected."""

    graph = FakeGraph()

    response = asyncio.run(
        api_request(app_for(graph), "POST", "/workflow/run", json=payload)
    )

    assert response.status_code == 422
    assert graph.states == []


@pytest.mark.parametrize(
    "error",
    [
        InvalidDatasetError("Dataset is invalid"),
        UndefinedMetricError("Metric is undefined"),
    ],
)
def test_domain_input_failures_return_400(error: Exception) -> None:
    """Deterministic input failures should retain a useful client message."""

    response = asyncio.run(
        api_request(
            app_for(FakeGraph(error=error)),
            "POST",
            "/workflow/run",
            json=workflow_payload(),
        )
    )

    assert response.status_code == 400
    assert response.json() == {"detail": str(error)}


def test_provider_failure_returns_503_without_leaking_details() -> None:
    """Provider-neutral availability failures should map to HTTP 503."""

    graph = FakeGraph(error=LLMUnavailableError("private provider detail"))

    response = asyncio.run(
        api_request(
            app_for(graph),
            "POST",
            "/workflow/run",
            json=workflow_payload(),
        )
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "LLM provider unavailable"}


@pytest.mark.parametrize(
    "graph",
    [
        FakeGraph(error=RuntimeError("private internal detail")),
        FakeGraph(result={}),
    ],
)
def test_unexpected_or_invalid_graph_results_return_safe_500(
    graph: FakeGraph,
) -> None:
    """Unexpected failures and invalid terminal state must not leak details."""

    response = asyncio.run(
        api_request(
            app_for(graph),
            "POST",
            "/workflow/run",
            json=workflow_payload(),
        )
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}


def test_api_graph_dependency_delegates_only_to_bootstrap() -> None:
    """The API dependency must not construct agents or providers itself."""

    expected = Mock()
    with patch(
        "autonomous_ai_company.api.dependencies.bootstrap_company_graph",
        return_value=expected,
    ) as composition_root:
        result = build_company_graph()

    assert result is expected
    composition_root.assert_called_once_with()


@pytest.mark.parametrize("checkpointing_enabled", [False, True])
def test_bootstrap_composes_complete_graph_with_shared_dependencies(
    checkpointing_enabled: bool,
) -> None:
    """Bootstrap should own complete graph and optional saver construction."""

    settings = configured_settings(checkpointing_enabled=checkpointing_enabled)
    sdk_client = Mock()
    with (
        patch(
            "autonomous_ai_company.bootstrap.get_settings",
            return_value=settings,
        ),
        patch(
            "autonomous_ai_company.llm.claude_client.AsyncAnthropic",
            return_value=sdk_client,
        ),
    ):
        graph = build_bootstrap_company_graph()

    agent_nodes = [
        graph.nodes[name].bound.afunc
        for name in ("finance", "marketing", "data_scientist", "report", "ceo")
    ]
    providers = {id(node._agent._llm_provider) for node in agent_nodes}
    audit_loggers = {id(node._agent._audit_logger) for node in agent_nodes}
    assert len(providers) == 1
    assert len(audit_loggers) == 1
    if checkpointing_enabled:
        assert isinstance(graph.checkpointer, InMemorySaver)
    else:
        assert graph.checkpointer is None
    assert graph.store is None
