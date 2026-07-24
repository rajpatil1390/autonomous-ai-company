"""Provide request-scoped API dependencies through the composition root."""

from langgraph.graph.state import CompiledStateGraph

from autonomous_ai_company.bootstrap import (
    build_company_graph as bootstrap_company_graph,
)


def build_company_graph() -> CompiledStateGraph:
    """Return a newly composed graph without retaining hidden singleton state."""

    return bootstrap_company_graph()
