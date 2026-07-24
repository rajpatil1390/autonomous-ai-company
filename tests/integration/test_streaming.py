"""Integration tests for request-scoped workflow SSE streaming."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from autonomous_ai_company.api.app import create_app
from autonomous_ai_company.api.dependencies import build_company_graph
from autonomous_ai_company.api.event_models import (
    WorkflowEvent,
    WorkflowEventType,
)
from autonomous_ai_company.api.streaming import (
    _node_event,
    serialize_sse,
    stream_workflow_events,
)
from autonomous_ai_company.auth.dependencies import get_current_user
from autonomous_ai_company.auth.models import AuthenticatedUser
from autonomous_ai_company.graph.company_state import CompanyState


def workflow_payload() -> dict[str, object]:
    """Return all explicit inputs required by WorkflowRequest."""

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
        "business_context": "Plan controlled growth.",
        "executive_question": "What should be approved?",
    }


def native_event(
    event: str,
    name: str,
    *,
    node: str | None = None,
) -> dict[str, object]:
    """Build one LangGraph-shaped lifecycle notification."""

    metadata: dict[str, object] = {}
    if node is not None:
        metadata["langgraph_node"] = node
    return {"event": event, "name": name, "metadata": metadata, "data": {}}


class FakeEventGraph:
    """Expose deterministic native events without agents or network access."""

    def __init__(
        self,
        events: list[dict[str, object]] | None = None,
        error: Exception | None = None,
        delay: float = 0.0,
    ) -> None:
        self.events = events or []
        self.error = error
        self.delay = delay
        self.states: list[CompanyState] = []
        self.versions: list[str] = []

    async def astream_events(
        self,
        state: CompanyState,
        *,
        version: str,
    ) -> AsyncIterator[dict[str, object]]:
        """Yield configured native events and optionally fail."""

        self.states.append(state)
        self.versions.append(version)
        if self.delay:
            await asyncio.sleep(self.delay)
        for event in self.events:
            await asyncio.sleep(0)
            yield event
        if self.error is not None:
            raise self.error


class DisconnectRequest:
    """Return a deterministic client connection sequence."""

    def __init__(self, states: list[bool]) -> None:
        self._states = iter(states)

    async def is_disconnected(self) -> bool:
        """Return the next state, then remain connected."""

        return next(self._states, False)


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse the small SSE subset emitted by the application."""

    parsed: list[tuple[str, dict[str, Any]]] = []
    for block in body.strip().split("\n\n"):
        event_line, data_line = block.splitlines()
        parsed.append(
            (
                event_line.removeprefix("event: "),
                json.loads(data_line.removeprefix("data: ")),
            )
        )
    return parsed


def app_for(graph: FakeEventGraph) -> FastAPI:
    """Create an authenticated test app with one injected event graph."""

    app = create_app()
    app.dependency_overrides[build_company_graph] = lambda: graph
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        username="admin"
    )
    return app


async def streaming_request(
    app: FastAPI,
    payload: dict[str, object],
) -> httpx.Response:
    """Call the SSE endpoint directly through an in-process ASGI transport."""

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.post("/workflow/stream", json=payload)


def test_event_model_is_strict_utc_immutable_and_json_serializable() -> None:
    """The wire DTO must reject ambiguity and serialize predictably."""

    event = WorkflowEvent(
        run_id="run-1",
        timestamp=datetime.now(timezone.utc),
        event_type=WorkflowEventType.HEARTBEAT,
        payload={"status": "active"},
    )

    restored = WorkflowEvent.model_validate_json(event.model_dump_json())

    assert restored == event
    assert serialize_sse(event).startswith("event: heartbeat\ndata: {")
    with pytest.raises(ValidationError):
        event.run_id = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="run_id must not be empty"):
        WorkflowEvent(
            run_id=" ",
            timestamp=datetime.now(timezone.utc),
            event_type=WorkflowEventType.HEARTBEAT,
            payload={},
        )
    for invalid_timestamp in (
        datetime.now(),
        datetime.now(timezone(timedelta(hours=1))),
    ):
        with pytest.raises(ValidationError, match="timezone-aware UTC"):
            WorkflowEvent(
                run_id="run-1",
                timestamp=invalid_timestamp,
                event_type=WorkflowEventType.HEARTBEAT,
                payload={},
            )
    with pytest.raises(ValidationError):
        WorkflowEvent.model_validate(
            {
                **event.model_dump(),
                "unsupported": True,
            }
        )


def test_stream_endpoint_emits_real_ordered_events_and_preserves_inputs() -> None:
    """The route should map native node events without changing workflow data."""

    graph = FakeEventGraph(
        [
            native_event("on_chain_start", "LangGraph"),
            native_event("on_chain_start", "finance", node="finance"),
            native_event("on_chain_stream", "finance", node="finance"),
            native_event("on_chain_start", "nested", node="finance"),
            native_event("on_chain_end", "finance", node="finance"),
            native_event("on_chain_start", "ceo", node="ceo"),
            native_event("on_chain_end", "ceo", node="ceo"),
            native_event("on_chain_end", "LangGraph"),
        ]
    )
    payload = workflow_payload()

    response = asyncio.run(streaming_request(app_for(graph), payload))
    events = parse_sse(response.text)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert [name for name, _ in events] == [
        "workflow_started",
        "node_started",
        "node_completed",
        "node_started",
        "node_completed",
        "workflow_completed",
    ]
    assert [event[1]["payload"] for event in events] == [
        {"status": "started"},
        {"node": "finance"},
        {"node": "finance"},
        {"node": "ceo"},
        {"node": "ceo"},
        {"status": "completed"},
    ]
    run_ids = {event[1]["run_id"] for event in events}
    assert len(run_ids) == 1
    UUID(run_ids.pop())
    assert all(
        datetime.fromisoformat(event[1]["timestamp"]).utcoffset() == timedelta(0)
        for event in events
    )
    assert graph.versions == ["v2"]
    state = graph.states[0]
    assert state["dataset"] == payload["dataset"]
    assert state["execution_status"] == "pending"
    assert state["audit_events"] == []
    assert state["generation_results"] == []
    assert state["errors"] == []
    metadata = state["metadata"]
    assert metadata["previous_dataset"] == payload["previous_dataset"]
    assert metadata["data_scientist_series"] == payload["data_scientist_series"]
    assert metadata["business_context"] == payload["business_context"]
    assert metadata["executive_question"] == payload["executive_question"]


def test_stream_reports_real_failure_without_leaking_exception_message() -> None:
    """A graph exception should terminate the protocol with a failure event."""

    graph = FakeEventGraph(error=RuntimeError("private failure detail"))

    response = asyncio.run(streaming_request(app_for(graph), workflow_payload()))
    events = parse_sse(response.text)

    assert [name for name, _ in events] == [
        "workflow_started",
        "workflow_failed",
    ]
    assert events[-1][1]["payload"] == {
        "status": "failed",
        "exception_type": "RuntimeError",
    }
    assert "private failure detail" not in response.text


def test_heartbeat_is_emitted_while_waiting_without_blocking() -> None:
    """A slow real event source should cause timed heartbeat notifications."""

    graph = FakeEventGraph(
        [native_event("on_chain_end", "finance", node="finance")],
        delay=0.025,
    )

    async def collect() -> list[tuple[str, dict[str, Any]]]:
        chunks = [
            chunk
            async for chunk in stream_workflow_events(
                request=DisconnectRequest([False]),  # type: ignore[arg-type]
                graph=graph,
                state={},
                run_id="heartbeat-run",
                heartbeat_interval=0.005,
                disconnect_poll_interval=0.001,
            )
        ]
        return parse_sse("".join(chunks))

    events = asyncio.run(collect())
    names = [name for name, _ in events]

    assert names[0] == "workflow_started"
    assert "heartbeat" in names
    assert names.index("heartbeat") < names.index("node_completed")
    assert names[-1] == "workflow_completed"


def test_disconnect_cancels_the_pending_graph_iteration() -> None:
    """Explicit disconnect detection must stop request-owned graph work."""

    started = asyncio.Event()
    cancelled = asyncio.Event()

    class BlockingGraph:
        async def astream_events(
            self,
            state: CompanyState,
            *,
            version: str,
        ) -> AsyncIterator[dict[str, object]]:
            del state, version
            started.set()
            try:
                await asyncio.Event().wait()
                yield {}
            finally:
                cancelled.set()

    async def consume() -> list[str]:
        chunks = []
        async for chunk in stream_workflow_events(
            request=DisconnectRequest([False, True]),  # type: ignore[arg-type]
            graph=BlockingGraph(),
            state={},
            run_id="disconnect-run",
            heartbeat_interval=1,
            disconnect_poll_interval=0.001,
        ):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(consume())

    assert started.is_set()
    assert cancelled.is_set()
    assert [name for name, _ in parse_sse("".join(chunks))] == ["workflow_started"]


def test_consumer_cancellation_propagates_and_cancels_graph() -> None:
    """ASGI cancellation must not be converted into workflow failure."""

    graph_cancelled = asyncio.Event()

    class BlockingGraph:
        async def astream_events(
            self,
            state: CompanyState,
            *,
            version: str,
        ) -> AsyncIterator[dict[str, object]]:
            del state, version
            try:
                await asyncio.Event().wait()
                yield {}
            finally:
                graph_cancelled.set()

    async def cancel_consumer() -> None:
        stream = stream_workflow_events(
            request=DisconnectRequest([False]),  # type: ignore[arg-type]
            graph=BlockingGraph(),
            state={},
            run_id="cancelled-run",
            heartbeat_interval=1,
            disconnect_poll_interval=1,
        )
        assert "workflow_started" in await anext(stream)
        consumer = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer

    asyncio.run(cancel_consumer())

    assert graph_cancelled.is_set()


@pytest.mark.parametrize(
    ("heartbeat_interval", "poll_interval"),
    [(0.0, 1.0), (1.0, 0.0)],
)
def test_stream_rejects_non_positive_timing_configuration(
    heartbeat_interval: float,
    poll_interval: float,
) -> None:
    """Internal timing configuration must never create a busy loop."""

    async def consume() -> None:
        stream = stream_workflow_events(
            request=DisconnectRequest([False]),  # type: ignore[arg-type]
            graph=FakeEventGraph(),
            state={},
            run_id="invalid-timing",
            heartbeat_interval=heartbeat_interval,
            disconnect_poll_interval=poll_interval,
        )
        await anext(stream)

    with pytest.raises(ValueError, match="must be positive"):
        asyncio.run(consume())


def test_node_mapping_rejects_non_node_and_unsupported_native_events() -> None:
    """Only exact native node start/end events may cross the API boundary."""

    assert _node_event("run", {}) is None
    assert _node_event("run", {"metadata": {"langgraph_node": 1}, "name": 1}) is None
    assert (
        _node_event(
            "run",
            {
                "metadata": {"langgraph_node": "finance"},
                "name": "nested",
            },
        )
        is None
    )
    assert (
        _node_event(
            "run",
            {
                "event": "on_chain_stream",
                "metadata": {"langgraph_node": "finance"},
                "name": "finance",
            },
        )
        is None
    )


def test_event_source_without_optional_close_hook_completes_normally() -> None:
    """The adapter should support the minimum AsyncIterator protocol."""

    class EmptyIterator:
        def __aiter__(self) -> "EmptyIterator":
            return self

        async def __anext__(self) -> dict[str, object]:
            raise StopAsyncIteration

    class MinimumGraph:
        def astream_events(
            self,
            state: CompanyState,
            *,
            version: str,
        ) -> EmptyIterator:
            del state, version
            return EmptyIterator()

    async def collect() -> str:
        return "".join(
            [
                chunk
                async for chunk in stream_workflow_events(
                    request=DisconnectRequest([False]),  # type: ignore[arg-type]
                    graph=MinimumGraph(),
                    state={},
                    run_id="minimum-run",
                )
            ]
        )

    assert [name for name, _ in parse_sse(asyncio.run(collect()))] == [
        "workflow_started",
        "workflow_completed",
    ]
