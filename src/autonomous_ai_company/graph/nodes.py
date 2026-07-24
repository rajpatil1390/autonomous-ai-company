"""Provide thin async adapters between ``CompanyState`` and injected agents.

Nodes read shared workflow data, call one preconstructed agent, and return one
owned partial update. They never mutate incoming state or construct providers,
audit storage, settings, or any other dependency.
"""

from collections.abc import Mapping
from typing import cast

from autonomous_ai_company.agents.ceo_agent import CEOAgent
from autonomous_ai_company.agents.data_scientist_agent import DataScientistAgent
from autonomous_ai_company.agents.finance_agent import FinanceAgent
from autonomous_ai_company.agents.marketing_agent import MarketingAgent
from autonomous_ai_company.agents.report_agent import ReportAgent
from autonomous_ai_company.graph.company_state import (
    CompanyState,
    JSONDocument,
)
from autonomous_ai_company.schemas.agent_outputs import (
    DataScientistAgentOutput,
    FinanceAgentOutput,
    MarketingAgentOutput,
    ReportAgentOutput,
)


def _metadata(state: CompanyState) -> JSONDocument:
    """Return the workflow metadata document required by analytical nodes."""

    return state["metadata"]


class FinanceNode:
    """Adapt shared state into one injected Finance Agent call."""

    def __init__(self, agent: FinanceAgent) -> None:
        """Retain the externally constructed Finance Agent."""

        self._agent = agent

    async def __call__(self, state: CompanyState) -> CompanyState:
        """Return only the serialized Finance Agent result."""

        metadata = _metadata(state)
        output = await self._agent.run(
            run_id=cast(str, metadata["run_id"]),
            current_period=state["dataset"],
            previous_period=cast(
                list[dict[str, object]],
                metadata["previous_dataset"],
            ),
            business_context=cast(str, metadata["business_context"]),
            user_question=cast(str | None, metadata.get("finance_question")),
        )
        return {"finance_result": output.model_dump(mode="json")}


class MarketingNode:
    """Adapt shared state into one injected Marketing Agent call."""

    def __init__(self, agent: MarketingAgent) -> None:
        """Retain the externally constructed Marketing Agent."""

        self._agent = agent

    async def __call__(self, state: CompanyState) -> CompanyState:
        """Return only the serialized Marketing Agent result."""

        metadata = _metadata(state)
        output = await self._agent.run(
            run_id=cast(str, metadata["run_id"]),
            current_period=state["dataset"],
            previous_period=cast(
                list[dict[str, object]],
                metadata["previous_dataset"],
            ),
            business_context=cast(str, metadata["business_context"]),
            user_question=cast(
                str | None,
                metadata.get("marketing_question"),
            ),
        )
        return {"marketing_result": output.model_dump(mode="json")}


class DataScientistNode:
    """Adapt shared state into one injected Data Scientist Agent call."""

    def __init__(self, agent: DataScientistAgent) -> None:
        """Retain the externally constructed Data Scientist Agent."""

        self._agent = agent

    async def __call__(self, state: CompanyState) -> CompanyState:
        """Return only the serialized Data Scientist Agent result."""

        metadata = _metadata(state)
        output = await self._agent.run(
            run_id=cast(str, metadata["run_id"]),
            dataset=cast(
                list[int | float],
                metadata["data_scientist_series"],
            ),
            business_context=cast(str, metadata["business_context"]),
            user_question=cast(
                str | None,
                metadata.get("data_scientist_question"),
            ),
            feature_importances=cast(
                Mapping[str, int | float] | None,
                metadata.get("feature_importances"),
            ),
            model_metrics=cast(
                Mapping[str, int | float] | None,
                metadata.get("model_metrics"),
            ),
        )
        return {"data_scientist_result": output.model_dump(mode="json")}


class ReportNode:
    """Adapt accumulated specialist results into one Report Agent call."""

    def __init__(self, agent: ReportAgent) -> None:
        """Retain the externally constructed Report Agent."""

        self._agent = agent

    async def __call__(self, state: CompanyState) -> CompanyState:
        """Return only the serialized Report Agent result."""

        metadata = _metadata(state)
        output = await self._agent.run(
            run_id=cast(str, metadata["run_id"]),
            finance_result=FinanceAgentOutput.model_validate(state["finance_result"]),
            marketing_result=MarketingAgentOutput.model_validate(
                state["marketing_result"]
            ),
            data_scientist_result=DataScientistAgentOutput.model_validate(
                state["data_scientist_result"]
            ),
            user_instructions=cast(
                str | None,
                metadata.get("report_instructions"),
            ),
        )
        return {"report_result": output.model_dump(mode="json")}


class CEONode:
    """Adapt all accumulated conclusions into one CEO Agent call."""

    def __init__(self, agent: CEOAgent) -> None:
        """Retain the externally constructed CEO Agent."""

        self._agent = agent

    async def __call__(self, state: CompanyState) -> CompanyState:
        """Return only the serialized CEO Agent result."""

        metadata = _metadata(state)
        finance_result = state.get("finance_result")
        marketing_result = state.get("marketing_result")
        data_scientist_result = state.get("data_scientist_result")
        report_result = state.get("report_result")
        output = await self._agent.run(
            run_id=cast(str, metadata["run_id"]),
            finance_result=(
                FinanceAgentOutput.model_validate(finance_result)
                if finance_result is not None
                else None
            ),
            marketing_result=(
                MarketingAgentOutput.model_validate(marketing_result)
                if marketing_result is not None
                else None
            ),
            data_scientist_result=(
                DataScientistAgentOutput.model_validate(data_scientist_result)
                if data_scientist_result is not None
                else None
            ),
            report_result=(
                ReportAgentOutput.model_validate(report_result)
                if report_result is not None
                else None
            ),
            executive_question=cast(
                str | None,
                metadata.get("executive_question"),
            ),
        )
        return {"ceo_result": output.model_dump(mode="json")}
