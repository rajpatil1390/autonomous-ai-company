"""Define the company workflow topology and conditional specialist routing.

This module owns node names and edges only. It does not construct agents,
providers, storage, settings, checkpointers, or compiled graph instances.
"""

from langgraph.graph import END, START, StateGraph

from autonomous_ai_company.graph.company_state import CompanyState
from autonomous_ai_company.graph.nodes import (
    CEONode,
    DataScientistNode,
    FinanceNode,
    MarketingNode,
    ReportNode,
)
from autonomous_ai_company.graph.routing import (
    ERROR_SUMMARY_ROUTE,
    REPORT_ROUTE,
    route_after_specialists,
)


FINANCE_NODE = "finance"
MARKETING_NODE = "marketing"
DATA_SCIENTIST_NODE = "data_scientist"
REPORT_NODE = "report"
SPECIALIST_ROUTER_NODE = "specialist_router"
ERROR_SUMMARY_NODE = "error_summary"
CEO_NODE = "ceo"

_SPECIALIST_RESULT_FIELDS = (
    "finance_result",
    "marketing_result",
    "data_scientist_result",
)


def _specialist_router_node(state: CompanyState) -> CompanyState:
    """Synchronize specialist branches without changing shared state."""

    del state
    return {}


def _error_summary_node(state: CompanyState) -> CompanyState:
    """Append a deterministic record of unavailable specialist sections."""

    unavailable_sections = [
        field.removesuffix("_result")
        for field in _SPECIALIST_RESULT_FIELDS
        if state.get(field) is None
    ]
    summary = {
        "component": ERROR_SUMMARY_NODE,
        "error_type": "UnavailableSpecialistOutputs",
        "unavailable_sections": unavailable_sections,
    }
    return {"errors": [*state.get("errors", []), summary]}


def register_sequential_company_graph(
    workflow: StateGraph,
    *,
    finance_node: FinanceNode,
    marketing_node: MarketingNode,
    data_scientist_node: DataScientistNode,
    report_node: ReportNode,
    ceo_node: CEONode,
) -> None:
    """Fan out specialists, route their joined state, then finish through CEO."""

    workflow.add_node(FINANCE_NODE, finance_node)
    workflow.add_node(MARKETING_NODE, marketing_node)
    workflow.add_node(DATA_SCIENTIST_NODE, data_scientist_node)
    workflow.add_node(SPECIALIST_ROUTER_NODE, _specialist_router_node)
    workflow.add_node(REPORT_NODE, report_node)
    workflow.add_node(ERROR_SUMMARY_NODE, _error_summary_node)
    workflow.add_node(CEO_NODE, ceo_node)

    workflow.add_edge(START, FINANCE_NODE)
    workflow.add_edge(START, MARKETING_NODE)
    workflow.add_edge(START, DATA_SCIENTIST_NODE)
    workflow.add_edge(
        [FINANCE_NODE, MARKETING_NODE, DATA_SCIENTIST_NODE],
        SPECIALIST_ROUTER_NODE,
    )
    workflow.add_conditional_edges(
        SPECIALIST_ROUTER_NODE,
        route_after_specialists,
        {
            REPORT_ROUTE: REPORT_NODE,
            ERROR_SUMMARY_ROUTE: ERROR_SUMMARY_NODE,
        },
    )
    workflow.add_edge(REPORT_NODE, CEO_NODE)
    workflow.add_edge(ERROR_SUMMARY_NODE, CEO_NODE)
    workflow.add_edge(CEO_NODE, END)
