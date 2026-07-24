"""Integration tests for local, provider-neutral MLflow experiment tracking."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from mlflow import MlflowClient
from pydantic import SecretStr, ValidationError

from autonomous_ai_company.bootstrap import _build_tracking_client
from autonomous_ai_company.agents.ceo_agent import CEOAgent
from autonomous_ai_company.agents.data_scientist_agent import DataScientistAgent
from autonomous_ai_company.agents.finance_agent import FinanceAgent
from autonomous_ai_company.agents.marketing_agent import MarketingAgent
from autonomous_ai_company.agents.report_agent import ReportAgent
from autonomous_ai_company.audit.audit_logger import AuditLogger
from autonomous_ai_company.bootstrap import build_company_graph, build_finance_agent
from autonomous_ai_company.config import Settings
from autonomous_ai_company.observability.mlflow_tracker import MLflowTrackingClient
from autonomous_ai_company.observability.tracking_models import (
    AgentTracking,
    AuditTracking,
    GenerationTracking,
    NullTrackingClient,
    TrackingClient,
    WorkflowTracking,
)


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
PROMPT_HASH = f"sha256:{'a' * 64}"


def settings(**overrides: object) -> Settings:
    """Build isolated settings without reading a developer environment."""

    values: dict[str, object] = {
        "ANTHROPIC_API_KEY": SecretStr("test-api-key"),
        "MODEL_NAME": "test-model",
        "TEMPERATURE": 0.2,
        "MAX_TOKENS": 512,
        "LOG_LEVEL": "INFO",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def file_tracking_uri(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Enable MLflow's explicit compatibility switch for its local file store."""

    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")
    tracking_directory = tmp_path / "tracking"
    tracking_directory.mkdir()
    return tracking_directory.as_uri()


def test_tracking_dtos_are_immutable_strict_and_json_serializable() -> None:
    """Tracking records must remain safe DTOs rather than provider objects."""

    workflow = WorkflowTracking(run_id="workflow-1", started_at=NOW)
    agent = AgentTracking(
        workflow_run_id=workflow.run_id,
        agent_name="finance_agent",
        started_at=NOW,
    )
    generation = GenerationTracking(
        provider="fake",
        model_name="deterministic",
        prompt_hash=PROMPT_HASH,
        attempt=1,
    )
    audit = AuditTracking(
        event_count=2,
        error_count=0,
        event_types=("start", "finish"),
    )

    assert json.loads(workflow.model_dump_json())["started_at"].endswith("Z")
    assert json.loads(agent.model_dump_json())["closes_workflow"] is False
    assert json.loads(generation.model_dump_json())["input_tokens"] is None
    assert json.loads(audit.model_dump_json())["event_types"] == ["start", "finish"]
    with pytest.raises(ValidationError):
        WorkflowTracking(run_id="workflow-1", started_at=NOW, secret="value")
    with pytest.raises(ValidationError):
        GenerationTracking(
            provider="fake",
            model_name="model",
            prompt_hash="raw prompt",
            attempt=1,
        )
    with pytest.raises(ValidationError):
        AgentTracking(workflow_run_id="", agent_name="finance", started_at=NOW)
    with pytest.raises(ValidationError):
        AuditTracking(event_count=-1, error_count=0)
    with pytest.raises(ValidationError):
        workflow.run_id = "changed"


def test_null_tracking_client_is_a_complete_disabled_implementation() -> None:
    """Disabled tracking must preserve agent behavior without side effects."""

    client = NullTrackingClient()
    workflow = WorkflowTracking(run_id="disabled", started_at=NOW)
    agent = AgentTracking(
        workflow_run_id="disabled",
        agent_name="finance_agent",
        started_at=NOW,
    )

    assert isinstance(client, TrackingClient)
    assert client.start_run(workflow) == "workflow:disabled"
    handle = client.start_run(agent)
    assert handle == "agent:disabled:finance_agent"
    client.log_metrics(handle, {"success": 1})
    client.log_params(handle, {"provider": "fake"})
    client.log_tags(handle, {"status": "FINISHED"})
    client.log_artifact(handle, "workflow_summary.json", "{}")
    client.end_run(handle)
    client.end_run(handle, "FAILED")


def test_mlflow_tracks_nested_runs_telemetry_artifacts_and_safe_fields(
    file_tracking_uri: str,
    tmp_path: Path,
) -> None:
    """A real local MLflow store should contain only approved observations."""

    artifact_directory = tmp_path / "artifacts"
    artifact_directory.mkdir()
    experiment_name = "company-integration"
    tracker = MLflowTrackingClient(
        file_tracking_uri,
        experiment_name,
        artifact_directory.as_uri(),
    )
    same_experiment_tracker = MLflowTrackingClient(
        file_tracking_uri,
        experiment_name,
    )
    workflow = WorkflowTracking(run_id="workflow-real", started_at=NOW)
    parent_handle = tracker.start_run(workflow)
    assert tracker.start_run(workflow) == parent_handle

    finance_handle = tracker.start_run(
        AgentTracking(
            workflow_run_id=workflow.run_id,
            agent_name="finance_agent",
            started_at=NOW,
        )
    )
    tracker.log_metrics(
        finance_handle,
        {
            "latency_ms": 12.5,
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "unsupported": 999,
        },
    )
    tracker.log_params(
        finance_handle,
        {
            "provider": "fake",
            "model_name": "deterministic",
            "prompt_hash_attempt_1": PROMPT_HASH,
            "raw_prompt": "ignore me",
            "api_key": "ignore me too",
        },
    )
    tracker.log_tags(
        finance_handle,
        {
            "status": "FINISHED",
            "generated_text": "ignore response",
            "jwt": "ignore token",
        },
    )
    tracker.log_artifact(finance_handle, "../../passwords.txt", "secret")
    tracker.log_artifact(finance_handle, "audit_summary.json", '{"events": 4}')
    tracker.end_run(finance_handle)

    ceo_handle = same_experiment_tracker.start_run(
        AgentTracking(
            workflow_run_id="second-workflow",
            agent_name="ceo_agent",
            started_at=NOW,
            closes_workflow=True,
        )
    )
    same_experiment_tracker.log_metrics(ceo_handle, {})
    same_experiment_tracker.log_params(ceo_handle, {})
    same_experiment_tracker.log_tags(ceo_handle, {})
    same_experiment_tracker.log_artifact(
        ceo_handle,
        "ceo_report.json",
        '{"executive_summary": "safe"}',
    )
    same_experiment_tracker.end_run(ceo_handle, "FAILED")

    standalone_parent = tracker.start_run(
        WorkflowTracking(run_id="standalone", started_at=NOW)
    )
    tracker.end_run(standalone_parent, "KILLED")

    client = MlflowClient(tracking_uri=file_tracking_uri)
    experiment = client.get_experiment_by_name(experiment_name)
    assert experiment is not None
    assert experiment.artifact_location == artifact_directory.as_uri()
    runs = client.search_runs([experiment.experiment_id])
    finance_run = client.get_run(finance_handle)
    assert finance_run.data.metrics["latency_ms"] == 12.5
    assert finance_run.data.metrics["total_tokens"] == 15
    assert "unsupported" not in finance_run.data.metrics
    assert finance_run.data.params == {
        "provider": "fake",
        "model_name": "deterministic",
        "prompt_hash_attempt_1": PROMPT_HASH,
    }
    assert "raw_prompt" not in finance_run.data.params
    assert "api_key" not in finance_run.data.params
    assert "generated_text" not in finance_run.data.tags
    assert "jwt" not in finance_run.data.tags
    assert finance_run.data.tags["mlflow.parentRunId"] == parent_handle
    artifacts = client.list_artifacts(finance_handle)
    assert [artifact.path for artifact in artifacts] == ["audit_summary.json"]
    downloaded = client.download_artifacts(finance_handle, "audit_summary.json")
    assert json.loads(Path(downloaded).read_text(encoding="utf-8")) == {"events": 4}
    assert client.get_run(ceo_handle).info.status == "FAILED"
    second_parent_id = client.get_run(ceo_handle).data.tags["mlflow.parentRunId"]
    assert client.get_run(second_parent_id).info.status == "FAILED"
    parent_artifacts = client.list_artifacts(second_parent_id)
    assert [artifact.path for artifact in parent_artifacts] == ["workflow_summary.json"]
    summary_path = client.download_artifacts(
        second_parent_id,
        "workflow_summary.json",
    )
    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    assert summary == {
        "agents": [{"agent_name": "ceo_agent", "status": "FAILED"}],
        "run_id": "second-workflow",
        "status": "FAILED",
    }
    assert client.get_run(standalone_parent).info.status == "KILLED"
    assert len(runs) == 5


def test_bootstrap_selects_one_request_scoped_tracking_client(
    file_tracking_uri: str,
) -> None:
    """Composition must select Null or MLflow without exposing it to the graph."""

    disabled = _build_tracking_client(settings())
    assert isinstance(disabled, NullTrackingClient)

    enabled_settings = settings(
        MLFLOW_ENABLED=True,
        MLFLOW_TRACKING_URI=file_tracking_uri,
        MLFLOW_EXPERIMENT_NAME="bootstrap-experiment",
    )
    enabled = _build_tracking_client(enabled_settings)
    assert isinstance(enabled, MLflowTrackingClient)

    with patch(
        "autonomous_ai_company.bootstrap.MLflowTrackingClient",
        return_value=Mock(spec=TrackingClient),
    ) as tracker_factory:
        selected = _build_tracking_client(enabled_settings)
    assert selected is tracker_factory.return_value
    tracker_factory.assert_called_once_with(
        tracking_uri=file_tracking_uri,
        experiment_name="bootstrap-experiment",
        artifact_location=None,
    )


def test_enabled_mlflow_requires_a_tracking_uri() -> None:
    """Configuration should reject an enabled adapter with no backend URI."""

    with pytest.raises(ValidationError, match="MLFLOW_TRACKING_URI"):
        settings(MLFLOW_ENABLED=True)


class FinalizationFailureTrackingClient(NullTrackingClient):
    """Exercise agent protection from an unavailable tracking backend."""

    def end_run(self, run_handle: str, status: str = "FINISHED") -> None:
        """Simulate a backend failure after primary application work."""

        raise RuntimeError("tracking unavailable")


@pytest.mark.parametrize(
    "agent_name",
    ["finance", "marketing", "data_scientist", "report", "ceo"],
)
def test_agents_do_not_mask_primary_failures_when_tracking_finalization_fails(
    agent_name: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Tracking failures must not replace deterministic application failures."""

    provider = Mock()
    audit_logger = AuditLogger()
    tracker = FinalizationFailureTrackingClient()
    if agent_name == "finance":
        operation = FinanceAgent(provider, audit_logger, tracker).run(
            "tracking-failure",
            (),
            (),
            "context",
        )
    elif agent_name == "marketing":
        operation = MarketingAgent(provider, audit_logger, tracker).run(
            "tracking-failure",
            (),
            (),
            "context",
        )
    elif agent_name == "data_scientist":
        operation = DataScientistAgent(provider, audit_logger, tracker).run(
            "tracking-failure",
            (),
            "context",
        )
    elif agent_name == "report":
        operation = ReportAgent(provider, audit_logger, tracker).run(
            "tracking-failure",
            object(),  # type: ignore[arg-type]
            None,
            None,
        )
    else:
        operation = CEOAgent(provider, audit_logger, tracker).run(
            "tracking-failure",
            object(),  # type: ignore[arg-type]
            None,
            None,
            None,
        )

    with pytest.raises(Exception) as captured:
        asyncio.run(operation)

    assert type(captured.value) is not RuntimeError
    assert "tracking finalization failed: RuntimeError" in caplog.text


def test_enabled_standalone_agent_receives_the_composed_tracking_client() -> None:
    """The standalone composition path should inject tracking when enabled."""

    configured = settings(
        MLFLOW_ENABLED=True,
        MLFLOW_TRACKING_URI="file:///temporary",
    )
    audit_logger = Mock()
    llm_router = Mock()
    tracking_client = Mock(spec=TrackingClient)
    expected_agent = Mock()
    with (
        patch(
            "autonomous_ai_company.bootstrap._build_runtime_dependencies",
            return_value=(
                configured,
                audit_logger,
                llm_router,
                tracking_client,
            ),
        ),
        patch(
            "autonomous_ai_company.bootstrap.FinanceAgent",
            return_value=expected_agent,
        ) as agent_factory,
    ):
        result = build_finance_agent()

    assert result is expected_agent
    agent_factory.assert_called_once_with(
        llm_provider=llm_router,
        audit_logger=audit_logger,
        tracking_client=tracking_client,
    )


def test_company_graph_agents_share_one_request_scoped_tracking_client(
    file_tracking_uri: str,
) -> None:
    """All nested agents in one compiled graph must share one lifecycle owner."""

    configured = settings(
        MLFLOW_ENABLED=True,
        MLFLOW_TRACKING_URI=file_tracking_uri,
        MLFLOW_EXPERIMENT_NAME="shared-client",
    )
    with (
        patch(
            "autonomous_ai_company.bootstrap.get_settings",
            return_value=configured,
        ),
        patch(
            "autonomous_ai_company.llm.claude_client.AsyncAnthropic",
            return_value=Mock(),
        ),
    ):
        graph = build_company_graph()

    agent_nodes = [
        graph.nodes[name].bound.afunc
        for name in ("finance", "marketing", "data_scientist", "report", "ceo")
    ]
    trackers = {id(node._agent._tracking_client) for node in agent_nodes}
    assert len(trackers) == 1
    assert isinstance(
        agent_nodes[0]._agent._tracking_client,
        MLflowTrackingClient,
    )
