"""Define deterministic routing policy for the company workflow.

Routing is kept separate from agents and graph construction so workflow policy
can evolve without coupling specialist reasoning to orchestration decisions.
"""

from typing import Literal

from autonomous_ai_company.graph.company_state import CompanyState


REPORT_ROUTE = "report"
ERROR_SUMMARY_ROUTE = "error_summary"
type SpecialistRoute = Literal["report", "error_summary"]


def route_after_specialists(state: CompanyState) -> SpecialistRoute:
    """Route complete specialist results to Report, otherwise to ErrorSummary."""

    required_results = (
        state.get("finance_result"),
        state.get("marketing_result"),
        state.get("data_scientist_result"),
    )
    if all(result is not None for result in required_results):
        return REPORT_ROUTE
    return ERROR_SUMMARY_ROUTE
