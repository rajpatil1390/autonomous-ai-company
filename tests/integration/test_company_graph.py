"""Integration tests for the conditional parallel company workflow."""

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph

from autonomous_ai_company.agents.ceo_agent import CEOAgent
from autonomous_ai_company.agents.data_scientist_agent import DataScientistAgent
from autonomous_ai_company.agents.finance_agent import FinanceAgent
from autonomous_ai_company.agents.marketing_agent import MarketingAgent
from autonomous_ai_company.agents.report_agent import ReportAgent
from autonomous_ai_company.audit.audit_logger import AuditLogger
from autonomous_ai_company.config import Settings
from autonomous_ai_company.exceptions import ConfigurationError
from autonomous_ai_company.graph.company_graph import (
    CEO_NODE,
    DATA_SCIENTIST_NODE,
    ERROR_SUMMARY_NODE,
    FINANCE_NODE,
    MARKETING_NODE,
    REPORT_NODE,
    SPECIALIST_ROUTER_NODE,
    register_sequential_company_graph,
)
from autonomous_ai_company.graph.company_state import CompanyState
from autonomous_ai_company.graph.graph_builder import build_company_graph
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
from autonomous_ai_company.llm.generation_result import GenerationResult
from autonomous_ai_company.schemas.agent_outputs import (
    CEOAgentOutput,
    DataScientistAgentOutput,
    FinanceAgentOutput,
    MarketingAgentOutput,
    ReportAgentOutput,
)


def finance_output() -> FinanceAgentOutput:
    """Return the deterministic Finance result used throughout graph tests."""

    return FinanceAgentOutput(
        executive_summary="Financial performance is stable.",
        key_findings=["Revenue supports controlled investment."],
        recommendations=["Maintain cost controls."],
        risk_level="low",
        confidence_score=0.9,
    )


def marketing_output() -> MarketingAgentOutput:
    """Return the deterministic Marketing result used throughout graph tests."""

    return MarketingAgentOutput(
        executive_summary="Retention creates a growth opportunity.",
        key_findings=["Enterprise is the leading segment."],
        opportunities=["Develop retention campaigns."],
        recommendations=["Prioritize retained customers."],
        confidence_score=0.85,
    )


def data_scientist_output() -> DataScientistAgentOutput:
    """Return the deterministic analytics result used by downstream nodes."""

    return DataScientistAgentOutput(
        executive_summary="Demand has a recurring pattern.",
        model_interpretation="Provided metrics indicate useful fit.",
        forecast_outlook="The supplied forecast trends upward.",
        limitations=["The observation window is limited."],
        recommendations=["Monitor forecast error."],
        confidence_score=0.8,
    )


def report_output() -> ReportAgentOutput:
    """Return the deterministic cross-specialist report."""

    return ReportAgentOutput(
        title="Company Performance Report",
        executive_summary="Performance is stable with focused opportunity.",
        sections={
            "finance": "Financial performance remains stable.",
            "marketing": "Retention offers focused growth.",
            "analytics": "Demand evidence has a recurring pattern.",
        },
        key_recommendations=["Use controlled investment."],
        unavailable_sections=[],
    )


def ceo_output() -> CEOAgentOutput:
    """Return the deterministic terminal executive decision."""

    return CEOAgentOutput(
        executive_summary="Pursue controlled growth with financial safeguards.",
        business_health="stable",
        strategic_priorities=["Run a bounded retention investment."],
        key_risks=["Expansion could weaken cost discipline."],
        final_recommendation="Approve staged growth with explicit controls.",
        confidence_score=0.86,
    )


def initial_state() -> CompanyState:
    """Return one JSON-safe state accepted by every sequential specialist."""

    return {
        "dataset": [
            {
                "revenue": 100,
                "cost": 60,
                "customer_id": "c1",
                "segment": "Enterprise",
            },
            {
                "revenue": 50,
                "cost": 30,
                "customer_id": "c1",
                "segment": "Enterprise",
            },
            {
                "revenue": 75,
                "cost": 50,
                "customer_id": "c2",
                "segment": "SMB",
            },
            {
                "revenue": 25,
                "cost": 20,
                "customer_id": "c3",
                "segment": "SMB",
            },
        ],
        "audit_events": [],
        "generation_results": [],
        "execution_status": "pending",
        "errors": [],
        "metadata": {
            "run_id": "company-graph-run",
            "business_context": "Subscription company planning controlled growth.",
            "previous_dataset": [
                {
                    "revenue": 80,
                    "cost": 50,
                    "customer_id": "c1",
                    "segment": "Enterprise",
                },
                {
                    "revenue": 60,
                    "cost": 40,
                    "customer_id": "c4",
                    "segment": "SMB",
                },
            ],
            "data_scientist_series": [10, 20, 10, 20, 10, 20],
            "feature_importances": {"price": 0.75, "season": 0.25},
            "model_metrics": {"accuracy": 0.9, "rmse": 1.5},
            "finance_question": "What financial risk matters most?",
            "marketing_question": "Where should marketing invest?",
            "data_scientist_question": "What should leadership monitor?",
            "report_instructions": "Prioritize actionable findings.",
            "executive_question": "Which priority should be approved?",
        },
    }


def checkpoint_settings(enabled: bool) -> Settings:
    """Return validated settings with an explicit checkpoint policy."""

    return Settings.model_validate(
        {
            "ANTHROPIC_API_KEY": "test-api-key",
            "MODEL_NAME": "test-model",
            "TEMPERATURE": 0.0,
            "MAX_TOKENS": 100,
            "LOG_LEVEL": "INFO",
            "CHECKPOINTING_ENABLED": enabled,
        }
    )


def generation_result(text: str, role: str) -> GenerationResult:
    """Wrap one queued output in provider-neutral telemetry."""

    return GenerationResult(
        text=text,
        model_name="fake-model",
        input_tokens=10,
        output_tokens=10,
        total_tokens=20,
        latency_ms=1.0,
        request_id=f"graph-request-{role}",
        stop_reason="end_turn",
        provider="fake",
    )


class ParallelFakeProvider:
    """Synchronize specialist requests and return role-specific fake outputs."""

    def __init__(self, delays: dict[str, float] | None = None) -> None:
        """Prepare output mapping, concurrency barrier, and event telemetry."""

        self._outputs = {
            "finance": finance_output().model_dump_json(),
            "marketing": marketing_output().model_dump_json(),
            "data_scientist": data_scientist_output().model_dump_json(),
            "report": report_output().model_dump_json(),
            "ceo": ceo_output().model_dump_json(),
        }
        self._delays = delays or {
            "finance": 0.03,
            "marketing": 0.01,
            "data_scientist": 0.02,
        }
        self._specialist_roles = {
            "finance",
            "marketing",
            "data_scientist",
        }
        self._started_specialists: set[str] = set()
        self._completed_specialists: set[str] = set()
        self._all_specialists_started = asyncio.Event()
        self.prompts: dict[str, str] = {}
        self.events: list[str] = []
        self.active_specialists = 0
        self.maximum_active_specialists = 0

    @staticmethod
    def _role(prompt: str) -> str:
        """Identify the requested schema without relying on call ordering."""

        if "``FinanceAgentOutput``" in prompt:
            return "finance"
        if "``MarketingAgentOutput``" in prompt:
            return "marketing"
        if "``DataScientistAgentOutput``" in prompt:
            return "data_scientist"
        if "``ReportAgentOutput``" in prompt:
            return "report"
        return "ceo"

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> GenerationResult:
        """Prove specialist overlap and enforce downstream wait assertions."""

        role = self._role(prompt)
        self.prompts[role] = prompt
        self.events.append(f"{role}:start")
        if role in self._specialist_roles:
            self._started_specialists.add(role)
            self.active_specialists += 1
            self.maximum_active_specialists = max(
                self.maximum_active_specialists,
                self.active_specialists,
            )
            if self._started_specialists == self._specialist_roles:
                self._all_specialists_started.set()
            await asyncio.wait_for(
                self._all_specialists_started.wait(),
                timeout=1,
            )
            await asyncio.sleep(self._delays[role])
            self.active_specialists -= 1
            self._completed_specialists.add(role)
        elif role == "report":
            assert self._completed_specialists == self._specialist_roles
        else:
            assert "report:end" in self.events
        self.events.append(f"{role}:end")
        return generation_result(self._outputs[role], role)


def real_agents(
    provider: ParallelFakeProvider,
) -> tuple[FinanceAgent, MarketingAgent, DataScientistAgent, ReportAgent, CEOAgent]:
    """Construct all real agents around one injected fake provider and logger."""

    audit_logger = AuditLogger()
    return (
        FinanceAgent(provider, audit_logger),
        MarketingAgent(provider, audit_logger),
        DataScientistAgent(provider, audit_logger),
        ReportAgent(provider, audit_logger),
        CEOAgent(provider, audit_logger),
    )


def test_graph_compiles_with_parallel_fan_out_and_conditional_join() -> None:
    """The graph must join specialists before either conditional destination."""

    agents = tuple(AsyncMock() for _ in range(5))
    graph = build_company_graph(
        finance_agent=agents[0],  # type: ignore[arg-type]
        marketing_agent=agents[1],  # type: ignore[arg-type]
        data_scientist_agent=agents[2],  # type: ignore[arg-type]
        report_agent=agents[3],  # type: ignore[arg-type]
        ceo_agent=agents[4],  # type: ignore[arg-type]
    )
    representation = graph.get_graph()
    edges = {(edge.source, edge.target) for edge in representation.edges}

    assert set(representation.nodes) == {
        "__start__",
        FINANCE_NODE,
        MARKETING_NODE,
        DATA_SCIENTIST_NODE,
        SPECIALIST_ROUTER_NODE,
        REPORT_NODE,
        ERROR_SUMMARY_NODE,
        CEO_NODE,
        "__end__",
    }
    assert edges == {
        ("__start__", FINANCE_NODE),
        ("__start__", MARKETING_NODE),
        ("__start__", DATA_SCIENTIST_NODE),
        (FINANCE_NODE, SPECIALIST_ROUTER_NODE),
        (MARKETING_NODE, SPECIALIST_ROUTER_NODE),
        (DATA_SCIENTIST_NODE, SPECIALIST_ROUTER_NODE),
        (SPECIALIST_ROUTER_NODE, REPORT_NODE),
        (SPECIALIST_ROUTER_NODE, ERROR_SUMMARY_NODE),
        (REPORT_NODE, CEO_NODE),
        (ERROR_SUMMARY_NODE, CEO_NODE),
        (CEO_NODE, "__end__"),
    }
    conditional_edges = {
        (edge.source, edge.target) for edge in representation.edges if edge.conditional
    }
    assert conditional_edges == {
        (SPECIALIST_ROUTER_NODE, REPORT_NODE),
        (SPECIALIST_ROUTER_NODE, ERROR_SUMMARY_NODE),
    }
    assert graph.checkpointer is None
    assert graph.store is None


def test_async_graph_runs_specialists_in_parallel_then_report_and_ceo() -> None:
    """A barrier proves overlap while downstream assertions prove both waits."""

    provider = ParallelFakeProvider()
    finance, marketing, data_scientist, report, ceo = real_agents(provider)
    graph = build_company_graph(
        finance_agent=finance,
        marketing_agent=marketing,
        data_scientist_agent=data_scientist,
        report_agent=report,
        ceo_agent=ceo,
    )
    state = initial_state()
    original = deepcopy(state)

    result = asyncio.run(graph.ainvoke(state))

    assert state == original
    assert result["finance_result"] == finance_output().model_dump(mode="json")
    assert result["marketing_result"] == marketing_output().model_dump(mode="json")
    assert result["data_scientist_result"] == data_scientist_output().model_dump(
        mode="json"
    )
    assert result["report_result"] == report_output().model_dump(mode="json")
    assert result["ceo_result"] == ceo_output().model_dump(mode="json")
    assert result["dataset"] == original["dataset"]
    assert set(provider.prompts) == {
        "finance",
        "marketing",
        "data_scientist",
        "report",
        "ceo",
    }
    assert provider.maximum_active_specialists == 3
    specialist_ends = [
        provider.events.index(f"{role}:end")
        for role in ("finance", "marketing", "data_scientist")
    ]
    assert max(specialist_ends) < provider.events.index("report:start")
    assert provider.events.index("report:end") < provider.events.index("ceo:start")
    assert "Financial performance is stable." in provider.prompts["report"]
    assert "Company Performance Report" in provider.prompts["ceo"]


def test_missing_specialist_routes_to_error_summary_then_partial_ceo() -> None:
    """A missing result must skip Report and reach CEO without fabrication."""

    finance_node = AsyncMock(return_value={})
    marketing_node = AsyncMock(
        return_value={"marketing_result": marketing_output().model_dump(mode="json")}
    )
    data_scientist_node = AsyncMock(
        return_value={
            "data_scientist_result": data_scientist_output().model_dump(mode="json")
        }
    )
    report_node = AsyncMock(
        return_value={"report_result": report_output().model_dump(mode="json")}
    )
    ceo_agent = AsyncMock()
    ceo_agent.run.return_value = ceo_output()
    workflow = StateGraph(CompanyState)
    register_sequential_company_graph(
        workflow,
        finance_node=finance_node,  # type: ignore[arg-type]
        marketing_node=marketing_node,  # type: ignore[arg-type]
        data_scientist_node=data_scientist_node,  # type: ignore[arg-type]
        report_node=report_node,  # type: ignore[arg-type]
        ceo_node=CEONode(ceo_agent),  # type: ignore[arg-type]
    )
    graph = workflow.compile()

    result = asyncio.run(graph.ainvoke(initial_state()))

    report_node.assert_not_awaited()
    ceo_call = ceo_agent.run.await_args.kwargs
    assert ceo_call["finance_result"] is None
    assert ceo_call["marketing_result"] == marketing_output()
    assert ceo_call["data_scientist_result"] == data_scientist_output()
    assert ceo_call["report_result"] is None
    assert result["errors"] == [
        {
            "component": ERROR_SUMMARY_NODE,
            "error_type": "UnavailableSpecialistOutputs",
            "unavailable_sections": ["finance"],
        }
    ]
    assert "finance_result" not in result
    assert "report_result" not in result
    assert result["ceo_result"] == ceo_output().model_dump(mode="json")


def test_routing_policy_is_deterministic_for_complete_and_missing_results() -> None:
    """Only specialist availability may influence the explicit route."""

    complete: CompanyState = {
        "finance_result": {},
        "marketing_result": {},
        "data_scientist_result": {},
    }
    missing: CompanyState = {
        "finance_result": {},
        "marketing_result": None,
        "data_scientist_result": {},
    }

    assert route_after_specialists(complete) == REPORT_ROUTE
    assert route_after_specialists(complete) == REPORT_ROUTE
    assert route_after_specialists(missing) == ERROR_SUMMARY_ROUTE
    assert route_after_specialists(missing) == ERROR_SUMMARY_ROUTE


def test_parallel_completion_order_does_not_change_the_merged_result() -> None:
    """Distinct branch timing must yield one deterministic conflict-free merge."""

    completion_orders: list[tuple[str, ...]] = []
    final_results: list[dict[str, object]] = []
    for delays in (
        {"finance": 0.03, "marketing": 0.01, "data_scientist": 0.02},
        {"finance": 0.01, "marketing": 0.03, "data_scientist": 0.02},
    ):
        provider = ParallelFakeProvider(delays)
        finance, marketing, data_scientist, report, ceo = real_agents(provider)
        graph = build_company_graph(
            finance_agent=finance,
            marketing_agent=marketing,
            data_scientist_agent=data_scientist,
            report_agent=report,
            ceo_agent=ceo,
        )

        result = asyncio.run(graph.ainvoke(initial_state()))

        completion_orders.append(
            tuple(
                event.removesuffix(":end")
                for event in provider.events
                if event.endswith(":end")
                and event.split(":", maxsplit=1)[0]
                in {"finance", "marketing", "data_scientist"}
            )
        )
        final_results.append(
            {
                key: result[key]
                for key in (
                    "finance_result",
                    "marketing_result",
                    "data_scientist_result",
                    "report_result",
                    "ceo_result",
                )
            }
        )

    assert completion_orders == [
        ("marketing", "data_scientist", "finance"),
        ("finance", "data_scientist", "marketing"),
    ]
    assert final_results[0] == final_results[1]


def test_each_node_is_isolated_returns_only_owned_update_and_never_mutates() -> None:
    """Thin adapters must preserve input state and expose one result key each."""

    state = initial_state()
    state.update(
        {
            "finance_result": finance_output().model_dump(mode="json"),
            "marketing_result": marketing_output().model_dump(mode="json"),
            "data_scientist_result": data_scientist_output().model_dump(mode="json"),
            "report_result": report_output().model_dump(mode="json"),
        }
    )
    original = deepcopy(state)
    finance_agent = AsyncMock()
    finance_agent.run.return_value = finance_output()
    marketing_agent = AsyncMock()
    marketing_agent.run.return_value = marketing_output()
    data_scientist_agent = AsyncMock()
    data_scientist_agent.run.return_value = data_scientist_output()
    report_agent = AsyncMock()
    report_agent.run.return_value = report_output()
    ceo_agent = AsyncMock()
    ceo_agent.run.return_value = ceo_output()

    async def invoke_nodes() -> list[CompanyState]:
        return [
            await FinanceNode(finance_agent)(state),  # type: ignore[arg-type]
            await MarketingNode(marketing_agent)(state),  # type: ignore[arg-type]
            await DataScientistNode(data_scientist_agent)(state),  # type: ignore[arg-type]
            await ReportNode(report_agent)(state),  # type: ignore[arg-type]
            await CEONode(ceo_agent)(state),  # type: ignore[arg-type]
        ]

    updates = asyncio.run(invoke_nodes())

    assert state == original
    assert updates == [
        {"finance_result": finance_output().model_dump(mode="json")},
        {"marketing_result": marketing_output().model_dump(mode="json")},
        {"data_scientist_result": data_scientist_output().model_dump(mode="json")},
        {"report_result": report_output().model_dump(mode="json")},
        {"ceo_result": ceo_output().model_dump(mode="json")},
    ]
    report_call = report_agent.run.await_args.kwargs
    assert report_call["finance_result"] == finance_output()
    assert report_call["marketing_result"] == marketing_output()
    assert report_call["data_scientist_result"] == data_scientist_output()
    ceo_call = ceo_agent.run.await_args.kwargs
    assert ceo_call["report_result"] == report_output()


def test_builds_are_fresh_and_keep_dependency_injection_explicit() -> None:
    """Repeated construction must not reuse graphs, nodes, or hidden globals."""

    first_agents = tuple(AsyncMock() for _ in range(5))
    second_agents = tuple(AsyncMock() for _ in range(5))
    first = build_company_graph(
        finance_agent=first_agents[0],  # type: ignore[arg-type]
        marketing_agent=first_agents[1],  # type: ignore[arg-type]
        data_scientist_agent=first_agents[2],  # type: ignore[arg-type]
        report_agent=first_agents[3],  # type: ignore[arg-type]
        ceo_agent=first_agents[4],  # type: ignore[arg-type]
    )
    second = build_company_graph(
        finance_agent=second_agents[0],  # type: ignore[arg-type]
        marketing_agent=second_agents[1],  # type: ignore[arg-type]
        data_scientist_agent=second_agents[2],  # type: ignore[arg-type]
        report_agent=second_agents[3],  # type: ignore[arg-type]
        ceo_agent=second_agents[4],  # type: ignore[arg-type]
    )

    assert first is not second
    assert first.nodes[FINANCE_NODE].bound is not second.nodes[FINANCE_NODE].bound


def test_checkpoint_configuration_requires_an_injected_checkpointer() -> None:
    """Enabled checkpointing must never hide backend construction in builder."""

    agents = tuple(AsyncMock() for _ in range(5))

    with pytest.raises(ConfigurationError, match="requires an injected"):
        build_company_graph(
            finance_agent=agents[0],  # type: ignore[arg-type]
            marketing_agent=agents[1],  # type: ignore[arg-type]
            data_scientist_agent=agents[2],  # type: ignore[arg-type]
            report_agent=agents[3],  # type: ignore[arg-type]
            ceo_agent=agents[4],  # type: ignore[arg-type]
            settings=checkpoint_settings(True),
        )


def test_disabled_checkpoint_configuration_preserves_default_behavior() -> None:
    """A supplied backend remains inactive unless configuration enables it."""

    agents = tuple(AsyncMock() for _ in range(5))
    checkpointer = InMemorySaver()

    graph = build_company_graph(
        finance_agent=agents[0],  # type: ignore[arg-type]
        marketing_agent=agents[1],  # type: ignore[arg-type]
        data_scientist_agent=agents[2],  # type: ignore[arg-type]
        report_agent=agents[3],  # type: ignore[arg-type]
        ceo_agent=agents[4],  # type: ignore[arg-type]
        settings=checkpoint_settings(False),
        checkpointer=checkpointer,
    )

    assert graph.checkpointer is None
    assert graph.store is None


def test_checkpointed_and_uncheckpointed_async_execution_are_identical() -> None:
    """Checkpoint support must not alter workflow behavior or output state."""

    plain_provider = ParallelFakeProvider()
    plain_agents = real_agents(plain_provider)
    plain_graph = build_company_graph(
        finance_agent=plain_agents[0],
        marketing_agent=plain_agents[1],
        data_scientist_agent=plain_agents[2],
        report_agent=plain_agents[3],
        ceo_agent=plain_agents[4],
    )
    checkpoint_provider = ParallelFakeProvider()
    checkpoint_agents = real_agents(checkpoint_provider)
    checkpointer = InMemorySaver()
    checkpointed_graph = build_company_graph(
        finance_agent=checkpoint_agents[0],
        marketing_agent=checkpoint_agents[1],
        data_scientist_agent=checkpoint_agents[2],
        report_agent=checkpoint_agents[3],
        ceo_agent=checkpoint_agents[4],
        settings=checkpoint_settings(True),
        checkpointer=checkpointer,
    )
    checkpoint_config = {"configurable": {"thread_id": "company-checkpoint-test"}}

    plain_result = asyncio.run(plain_graph.ainvoke(initial_state()))
    checkpointed_result = asyncio.run(
        checkpointed_graph.ainvoke(initial_state(), checkpoint_config)
    )

    assert checkpointed_result == plain_result
    assert checkpointed_graph.checkpointer is checkpointer
    assert checkpointed_graph.store is None
    assert checkpointer.get_tuple(checkpoint_config) is not None
    assert checkpoint_provider.maximum_active_specialists == 3
