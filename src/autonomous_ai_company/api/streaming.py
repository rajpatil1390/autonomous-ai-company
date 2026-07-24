"""Adapt request-scoped LangGraph lifecycle events to SSE wire messages."""

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import suppress
from datetime import datetime, timezone
from typing import Protocol

from fastapi import Request

from autonomous_ai_company.api.event_models import (
    WorkflowEvent,
    WorkflowEventType,
)
from autonomous_ai_company.graph.company_state import CompanyState


HEARTBEAT_INTERVAL_SECONDS = 15.0
DISCONNECT_POLL_INTERVAL_SECONDS = 0.1


class WorkflowEventSource(Protocol):
    """Describe the native async event surface required from a compiled graph."""

    def astream_events(
        self,
        state: CompanyState,
        *,
        version: str,
    ) -> AsyncIterator[dict[str, object]]:
        """Return real graph lifecycle events for one request-scoped run."""


def _workflow_event(
    run_id: str,
    event_type: WorkflowEventType,
    payload: dict[str, object],
) -> WorkflowEvent:
    """Create one validated event with an authoritative UTC timestamp."""

    return WorkflowEvent.model_validate(
        {
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc),
            "event_type": event_type,
            "payload": payload,
        }
    )


def serialize_sse(event: WorkflowEvent) -> str:
    """Serialize one event using the standard SSE event and data fields."""

    return f"event: {event.event_type.value}\ndata: {event.model_dump_json()}\n\n"


def _node_event(
    run_id: str,
    native_event: Mapping[str, object],
) -> WorkflowEvent | None:
    """Map only genuine top-level LangGraph node lifecycle notifications."""

    metadata = native_event.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    node_name = metadata.get("langgraph_node")
    if not isinstance(node_name, str) or native_event.get("name") != node_name:
        return None

    event_name = native_event.get("event")
    if event_name == "on_chain_start":
        event_type = WorkflowEventType.NODE_STARTED
    elif event_name == "on_chain_end":
        event_type = WorkflowEventType.NODE_COMPLETED
    else:
        return None
    return _workflow_event(run_id, event_type, {"node": node_name})


async def stream_workflow_events(
    *,
    request: Request,
    graph: WorkflowEventSource,
    state: CompanyState,
    run_id: str,
    heartbeat_interval: float = HEARTBEAT_INTERVAL_SECONDS,
    disconnect_poll_interval: float = DISCONNECT_POLL_INTERVAL_SECONDS,
) -> AsyncIterator[str]:
    """Stream one graph run and cancel its pending work after disconnection.

    The graph remains request-scoped. Its native event iterator is the sole
    source of node lifecycle events; the adapter adds workflow boundary events
    only when execution actually starts, completes, or raises. A monotonic
    clock schedules heartbeats without blocking the event loop.
    """

    if heartbeat_interval <= 0 or disconnect_poll_interval <= 0:
        raise ValueError("stream timing intervals must be positive")

    yield serialize_sse(
        _workflow_event(
            run_id,
            WorkflowEventType.WORKFLOW_STARTED,
            {"status": "started"},
        )
    )

    native_events = graph.astream_events(state, version="v2").__aiter__()
    pending_event: asyncio.Task[dict[str, object]] | None = asyncio.create_task(
        anext(native_events)
    )
    loop = asyncio.get_running_loop()
    next_heartbeat = loop.time() + heartbeat_interval

    try:
        while True:
            if await request.is_disconnected():
                return

            remaining = max(0.0, next_heartbeat - loop.time())
            timeout = min(disconnect_poll_interval, remaining)
            done, _ = await asyncio.wait({pending_event}, timeout=timeout)

            if pending_event in done:
                try:
                    native_event = pending_event.result()
                except StopAsyncIteration:
                    pending_event = None
                    yield serialize_sse(
                        _workflow_event(
                            run_id,
                            WorkflowEventType.WORKFLOW_COMPLETED,
                            {"status": "completed"},
                        )
                    )
                    return

                pending_event = asyncio.create_task(anext(native_events))
                mapped_event = _node_event(run_id, native_event)
                if mapped_event is not None:
                    yield serialize_sse(mapped_event)

            if loop.time() >= next_heartbeat:
                yield serialize_sse(
                    _workflow_event(
                        run_id,
                        WorkflowEventType.HEARTBEAT,
                        {"status": "active"},
                    )
                )
                next_heartbeat = loop.time() + heartbeat_interval
    except asyncio.CancelledError:
        raise
    except Exception as error:
        yield serialize_sse(
            _workflow_event(
                run_id,
                WorkflowEventType.WORKFLOW_FAILED,
                {
                    "status": "failed",
                    "exception_type": type(error).__name__,
                },
            )
        )
    finally:
        if pending_event is not None and not pending_event.done():
            pending_event.cancel()
            with suppress(asyncio.CancelledError):
                await pending_event
        close = getattr(native_events, "aclose", None)
        if close is not None:
            with suppress(RuntimeError):
                await close()
