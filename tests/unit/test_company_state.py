"""Unit tests for the dependency-free shared company workflow state."""

import json
from concurrent.futures import ThreadPoolExecutor
from typing import get_type_hints, is_typeddict

from autonomous_ai_company.graph.company_state import CompanyState


STATE_FIELDS = {
    "dataset",
    "finance_result",
    "marketing_result",
    "data_scientist_result",
    "report_result",
    "ceo_result",
    "audit_events",
    "generation_results",
    "execution_status",
    "errors",
    "metadata",
}


def test_company_state_constructs_with_every_shared_field() -> None:
    """The complete workflow envelope should retain every declared value."""

    state: CompanyState = {
        "dataset": [{"revenue": "300.30", "order_count": 2}],
        "finance_result": {"risk_level": "low"},
        "marketing_result": {"campaigns": ["retention"]},
        "data_scientist_result": {"trend": "positive"},
        "report_result": {"title": "Quarterly review"},
        "ceo_result": {"decision": "continue investment"},
        "audit_events": [{"event_type": "start"}],
        "generation_results": [{"provider": "anthropic", "total_tokens": 50}],
        "execution_status": "completed",
        "errors": [],
        "metadata": {"run_id": "run-1", "tags": ["phase-b"]},
    }

    assert set(state) == STATE_FIELDS
    assert state["dataset"][0]["revenue"] == "300.30"
    assert state["finance_result"] == {"risk_level": "low"}
    assert state["execution_status"] == "completed"


def test_company_state_supports_optional_partial_updates() -> None:
    """A node should be able to return only the fields it owns."""

    finance_update: CompanyState = {
        "finance_result": {"risk_level": "medium"},
    }
    status_update: CompanyState = {"execution_status": "running"}
    empty_update: CompanyState = {}

    assert finance_update == {"finance_result": {"risk_level": "medium"}}
    assert status_update == {"execution_status": "running"}
    assert empty_update == {}


def test_company_state_round_trips_through_standard_json() -> None:
    """Checkpointing should require no custom encoder or project objects."""

    state: CompanyState = {
        "dataset": [{"revenue": "0.30", "active": True, "segment": None}],
        "finance_result": {"confidence_score": 0.9},
        "audit_events": [{"timestamp": "2026-07-15T10:00:00Z"}],
        "generation_results": [{"latency_ms": 12.5}],
        "execution_status": "running",
        "errors": [],
        "metadata": {"attempt": 1},
    }

    serialized = json.dumps(state, sort_keys=True)

    assert json.loads(serialized) == state


def test_parallel_nodes_can_build_disjoint_updates_without_shared_mutation() -> None:
    """Parallel workers should produce isolated updates for deterministic merge."""

    base_state: CompanyState = {
        "dataset": [{"revenue": "100.00"}],
        "execution_status": "running",
    }

    def build_update(agent_name: str) -> CompanyState:
        if agent_name == "finance":
            return {"finance_result": {"source": agent_name}}
        if agent_name == "marketing":
            return {"marketing_result": {"source": agent_name}}
        return {"data_scientist_result": {"source": agent_name}}

    with ThreadPoolExecutor(max_workers=3) as executor:
        updates = tuple(
            executor.map(
                build_update,
                ("finance", "marketing", "data_scientist"),
            )
        )

    merged_state: CompanyState = dict(base_state)
    for update in updates:
        merged_state.update(update)

    assert base_state == {
        "dataset": [{"revenue": "100.00"}],
        "execution_status": "running",
    }
    assert merged_state["finance_result"] == {"source": "finance"}
    assert merged_state["marketing_result"] == {"source": "marketing"}
    assert merged_state["data_scientist_result"] == {"source": "data_scientist"}
    assert len({id(update) for update in updates}) == 3


def test_company_state_exposes_the_expected_typed_dict_contract() -> None:
    """Static tooling should see every shared field as an optional state key."""

    annotations = get_type_hints(CompanyState)

    assert is_typeddict(CompanyState)
    assert set(annotations) == STATE_FIELDS
    assert CompanyState.__required_keys__ == frozenset()
    assert CompanyState.__optional_keys__ == frozenset(STATE_FIELDS)
