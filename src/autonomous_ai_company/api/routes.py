"""Map validated HTTP requests to injected asynchronous graph execution."""

from typing import Annotated, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from langgraph.graph.state import CompiledStateGraph

from autonomous_ai_company.api.dependencies import build_company_graph
from autonomous_ai_company.api.models import (
    HealthResponse,
    VersionResponse,
    WorkflowRequest,
)
from autonomous_ai_company.api.streaming import stream_workflow_events
from autonomous_ai_company.auth.dependencies import get_current_user
from autonomous_ai_company.auth.models import AuthenticatedUser
from autonomous_ai_company.graph.company_state import CompanyState
from autonomous_ai_company.schemas.agent_outputs import CEOAgentOutput


GraphDependency = Annotated[CompiledStateGraph, Depends(build_company_graph)]
CurrentUserDependency = Annotated[AuthenticatedUser, Depends(get_current_user)]


def create_router() -> APIRouter:
    """Create isolated routes whose dependencies FastAPI can override in tests."""

    router = APIRouter()

    @router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        """Report process liveness without touching application dependencies."""

        return HealthResponse(status="ok")

    @router.get("/version", response_model=VersionResponse)
    async def version() -> VersionResponse:
        """Return the public API identity and compatibility version."""

        return VersionResponse(
            application="Autonomous AI Company",
            version="1.0.0",
        )

    @router.post("/workflow/run", response_model=CEOAgentOutput)
    async def run_workflow(
        request: WorkflowRequest,
        current_user: CurrentUserDependency,
        graph: GraphDependency,
    ) -> CEOAgentOutput:
        """Invoke the graph and validate its final domain response."""

        del current_user
        state: CompanyState = {
            "dataset": request.dataset,
            "audit_events": [],
            "generation_results": [],
            "execution_status": "pending",
            "errors": [],
            "metadata": {
                "run_id": str(uuid4()),
                "previous_dataset": request.previous_dataset,
                "data_scientist_series": request.data_scientist_series,
                "business_context": request.business_context,
                "executive_question": request.executive_question,
            },
        }
        result = cast(CompanyState, await graph.ainvoke(state))
        return CEOAgentOutput.model_validate(result.get("ceo_result"))

    @router.post("/workflow/stream", response_class=StreamingResponse)
    async def stream_workflow(
        request: WorkflowRequest,
        http_request: Request,
        current_user: CurrentUserDependency,
        graph: GraphDependency,
    ) -> StreamingResponse:
        """Stream real lifecycle events from one request-scoped graph run."""

        del current_user
        run_id = str(uuid4())
        state: CompanyState = {
            "dataset": request.dataset,
            "audit_events": [],
            "generation_results": [],
            "execution_status": "pending",
            "errors": [],
            "metadata": {
                "run_id": run_id,
                "previous_dataset": request.previous_dataset,
                "data_scientist_series": request.data_scientist_series,
                "business_context": request.business_context,
                "executive_question": request.executive_question,
            },
        }
        return StreamingResponse(
            stream_workflow_events(
                request=http_request,
                graph=graph,
                state=state,
                run_id=run_id,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return router
