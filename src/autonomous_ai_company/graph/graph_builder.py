"""Compile the company graph from explicitly injected agent dependencies."""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph

from autonomous_ai_company.agents.ceo_agent import CEOAgent
from autonomous_ai_company.agents.data_scientist_agent import DataScientistAgent
from autonomous_ai_company.agents.finance_agent import FinanceAgent
from autonomous_ai_company.agents.marketing_agent import MarketingAgent
from autonomous_ai_company.agents.report_agent import ReportAgent
from autonomous_ai_company.config import Settings
from autonomous_ai_company.exceptions import ConfigurationError
from autonomous_ai_company.graph.company_graph import (
    register_sequential_company_graph,
)
from autonomous_ai_company.graph.company_state import CompanyState
from autonomous_ai_company.graph.nodes import (
    CEONode,
    DataScientistNode,
    FinanceNode,
    MarketingNode,
    ReportNode,
)


def build_company_graph(
    *,
    finance_agent: FinanceAgent,
    marketing_agent: MarketingAgent,
    data_scientist_agent: DataScientistAgent,
    report_agent: ReportAgent,
    ceo_agent: CEOAgent,
    settings: Settings | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Build the fixed graph with an optional injected checkpoint backend.

    Settings decide whether checkpointing is active, while the caller owns the
    checkpointer implementation and lifecycle. This keeps storage construction
    outside orchestration and preserves a no-checkpoint default.

    Raises:
        ConfigurationError: If checkpointing is enabled without a checkpointer.
    """

    checkpointing_enabled = (
        settings.checkpointing_enabled if settings is not None else False
    )
    if checkpointing_enabled and checkpointer is None:
        raise ConfigurationError(
            "Checkpointing requires an injected LangGraph checkpointer"
        )

    workflow = StateGraph(CompanyState)
    register_sequential_company_graph(
        workflow,
        finance_node=FinanceNode(finance_agent),
        marketing_node=MarketingNode(marketing_agent),
        data_scientist_node=DataScientistNode(data_scientist_agent),
        report_node=ReportNode(report_agent),
        ceo_node=CEONode(ceo_agent),
    )
    return workflow.compile(
        checkpointer=checkpointer if checkpointing_enabled else None
    )
