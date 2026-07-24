"""Integration tests for JWT authentication at the FastAPI boundary."""

import asyncio
from copy import deepcopy
from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI

from autonomous_ai_company.api.app import create_app
from autonomous_ai_company.api.dependencies import build_company_graph
from autonomous_ai_company.auth.dependencies import get_current_user
from autonomous_ai_company.auth.jwt_service import create_access_token
from autonomous_ai_company.auth.models import AuthenticatedUser
from autonomous_ai_company.config import Settings, get_settings


JWT_SECRET = "integration-signing-secret-with-more-than-thirty-two-bytes"


def auth_settings(
    *,
    secret: str = JWT_SECRET,
) -> Settings:
    """Return complete settings without production credentials."""

    return Settings(
        ANTHROPIC_API_KEY="test-api-key",
        MODEL_NAME="test-model",
        TEMPERATURE=0.0,
        MAX_TOKENS=100,
        LOG_LEVEL="INFO",
        JWT_SECRET_KEY=secret,
        JWT_ALGORITHM="HS256",
        ACCESS_TOKEN_EXPIRE_MINUTES=15,
        _env_file=None,
    )


def workflow_payload() -> dict[str, object]:
    """Return all caller-supplied workflow inputs."""

    return {
        "dataset": [{"revenue": 100, "cost": 60}],
        "previous_dataset": [{"revenue": 80, "cost": 50}],
        "data_scientist_series": [10, 20, 30],
        "business_context": "Controlled growth.",
        "executive_question": "What should be approved?",
    }


def ceo_response() -> dict[str, object]:
    """Return one valid terminal graph response."""

    return {
        "executive_summary": "Pursue controlled growth.",
        "business_health": "stable",
        "strategic_priorities": ["Invest with safeguards."],
        "key_risks": ["Costs may rise."],
        "final_recommendation": "Approve a staged investment.",
        "confidence_score": 0.9,
    }


class FakeGraph:
    """Capture workflow invocations without network or graph modifications."""

    def __init__(self) -> None:
        """Initialize isolated invocation state."""

        self.states: list[dict[str, object]] = []

    async def ainvoke(self, state: dict[str, object]) -> dict[str, object]:
        """Yield to the event loop and return a deterministic CEO result."""

        await asyncio.sleep(0)
        self.states.append(deepcopy(state))
        return {"ceo_result": ceo_response()}


def configured_app(graph: FakeGraph | None = None) -> FastAPI:
    """Create an app with isolated settings and optional fake graph."""

    app = create_app()
    app.dependency_overrides[get_settings] = auth_settings
    if graph is not None:
        app.dependency_overrides[build_company_graph] = lambda: graph
    return app


async def request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json: dict[str, object] | None = None,
    token: str | None = None,
) -> httpx.Response:
    """Send one request through HTTPX's asynchronous ASGI transport."""

    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.request(method, path, json=json, headers=headers)


def login(app: FastAPI) -> str:
    """Authenticate the configured demo user and return its bearer token."""

    response = asyncio.run(
        request(
            app,
            "POST",
            "/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    return str(response.json()["access_token"])


def test_health_and_version_remain_public() -> None:
    """Liveness and version discovery must not require authentication."""

    app = create_app()

    health = asyncio.run(request(app, "GET", "/health"))
    version = asyncio.run(request(app, "GET", "/version"))

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert version.status_code == 200


def test_login_and_valid_jwt_authorize_async_workflow() -> None:
    """Valid demo credentials should grant access to the unchanged workflow."""

    graph = FakeGraph()
    app = configured_app(graph)
    token = login(app)

    response = asyncio.run(
        request(
            app,
            "POST",
            "/workflow/run",
            json=workflow_payload(),
            token=token,
        )
    )

    assert response.status_code == 200
    assert response.json() == ceo_response()
    assert len(graph.states) == 1
    metadata = graph.states[0]["metadata"]
    assert isinstance(metadata, dict)
    assert "username" not in metadata
    assert "user" not in metadata


@pytest.mark.parametrize(
    "credentials",
    [
        {"username": "unknown", "password": "admin123"},
        {"username": "admin", "password": "wrong-password"},
    ],
)
def test_login_rejects_invalid_credentials(
    credentials: dict[str, object],
) -> None:
    """Unknown usernames and incorrect passwords should share one response."""

    response = asyncio.run(
        request(
            configured_app(),
            "POST",
            "/auth/login",
            json=credentials,
        )
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Incorrect username or password"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_login_request_validation_returns_422() -> None:
    """Malformed login bodies should fail before password verification."""

    response = asyncio.run(
        request(
            configured_app(),
            "POST",
            "/auth/login",
            json={"username": "admin", "unsupported": True},
        )
    )

    assert response.status_code == 422


def test_protected_workflow_rejects_missing_token_before_graph_creation() -> None:
    """The workflow graph must not run when bearer credentials are absent."""

    graph = FakeGraph()
    app = configured_app(graph)

    response = asyncio.run(
        request(
            app,
            "POST",
            "/workflow/run",
            json=workflow_payload(),
        )
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert graph.states == []


@pytest.mark.parametrize("token_kind", ["expired", "malformed", "signature"])
def test_protected_workflow_rejects_invalid_tokens(token_kind: str) -> None:
    """Expired, malformed, and foreign-signature JWTs must return HTTP 401."""

    settings = auth_settings()
    if token_kind == "expired":
        token = create_access_token(
            "admin",
            settings,
            expires_delta=timedelta(seconds=-1),
        )
    elif token_kind == "signature":
        token = create_access_token(
            "admin",
            auth_settings(
                secret="foreign-signing-secret-with-more-than-thirty-two-bytes"
            ),
        )
    else:
        token = "not-a-jwt"
    graph = FakeGraph()

    response = asyncio.run(
        request(
            configured_app(graph),
            "POST",
            "/workflow/run",
            json=workflow_payload(),
            token=token,
        )
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
    assert response.headers["www-authenticate"] == "Bearer"
    assert graph.states == []


def test_current_user_dependency_can_be_overridden_without_auth_bypass_code() -> None:
    """FastAPI overrides should isolate route tests from JWT infrastructure."""

    graph = FakeGraph()
    app = configured_app(graph)
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        username="test-user"
    )

    response = asyncio.run(
        request(
            app,
            "POST",
            "/workflow/run",
            json=workflow_payload(),
        )
    )

    assert response.status_code == 200
    assert len(graph.states) == 1
