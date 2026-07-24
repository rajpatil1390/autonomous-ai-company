"""Implement experiment tracking behind the provider-neutral client contract.

Only this infrastructure adapter imports MLflow. Explicit run identifiers are
used instead of MLflow's global active-run stack so one request-scoped client
can safely track concurrent specialist agents.
"""

import json
from collections.abc import Mapping
from pathlib import PurePosixPath
from threading import RLock
from time import time

import mlflow
from mlflow import MlflowClient
from mlflow.entities import Metric, Param, RunTag

from autonomous_ai_company.observability.tracking_models import (
    AgentTracking,
    RunStatus,
    TrackingValue,
    WorkflowTracking,
)


_SAFE_METRICS = {
    "workflow_duration_ms",
    "agent_duration_ms",
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "retry_count",
    "success",
}
_SAFE_PARAMS = {"provider", "model_name", "request_id", "stop_reason", "attempt"}
_SAFE_TAGS = {"workflow_run_id", "agent_name", "status", "exception_type"}
_SAFE_ARTIFACTS = {"ceo_report.json", "audit_summary.json", "workflow_summary.json"}


class MLflowTrackingClient:
    """Own one request's workflow parent and nested MLflow agent runs.

    The adapter creates the configured experiment once, lazily creates a
    workflow parent when its first agent begins, and synchronizes lifecycle
    state because the specialist branches may start concurrently.
    """

    def __init__(
        self,
        tracking_uri: str,
        experiment_name: str,
        artifact_location: str | None = None,
    ) -> None:
        """Bind an isolated MLflow client to deployment-owned configuration."""

        self._client = MlflowClient(tracking_uri=tracking_uri)
        self._lock = RLock()
        self._workflow_runs: dict[str, str] = {}
        self._workflow_started_ms: dict[str, int] = {}
        self._agent_parents: dict[str, tuple[str, str, bool]] = {}
        self._workflow_agents: dict[str, list[dict[str, str]]] = {}

        experiment = self._client.get_experiment_by_name(experiment_name)
        if experiment is None:
            self._experiment_id = self._client.create_experiment(
                experiment_name,
                artifact_location=artifact_location,
            )
        else:
            self._experiment_id = experiment.experiment_id

    def start_run(self, tracking: WorkflowTracking | AgentTracking) -> str:
        """Create an idempotent parent or a new explicitly nested child run."""

        with self._lock:
            if isinstance(tracking, WorkflowTracking):
                return self._ensure_workflow(tracking)

            parent_id = self._ensure_workflow(
                WorkflowTracking(
                    run_id=tracking.workflow_run_id,
                    started_at=tracking.started_at,
                )
            )
            child = self._client.create_run(
                self._experiment_id,
                start_time=int(tracking.started_at.timestamp() * 1_000),
                tags={
                    mlflow.utils.mlflow_tags.MLFLOW_RUN_NAME: tracking.agent_name,
                    mlflow.utils.mlflow_tags.MLFLOW_PARENT_RUN_ID: parent_id,
                    "workflow_run_id": tracking.workflow_run_id,
                    "agent_name": tracking.agent_name,
                },
            )
            child_id = child.info.run_id
            self._agent_parents[child_id] = (
                tracking.workflow_run_id,
                tracking.agent_name,
                tracking.closes_workflow,
            )
            return child_id

    def _ensure_workflow(self, tracking: WorkflowTracking) -> str:
        """Return the existing workflow parent or create it exactly once."""

        existing = self._workflow_runs.get(tracking.run_id)
        if existing is not None:
            return existing
        started_ms = int(tracking.started_at.timestamp() * 1_000)
        parent = self._client.create_run(
            self._experiment_id,
            start_time=started_ms,
            tags={
                mlflow.utils.mlflow_tags.MLFLOW_RUN_NAME: tracking.workflow_name,
                "workflow_run_id": tracking.run_id,
            },
        )
        parent_id = parent.info.run_id
        self._workflow_runs[tracking.run_id] = parent_id
        self._workflow_started_ms[tracking.run_id] = started_ms
        self._workflow_agents[tracking.run_id] = []
        return parent_id

    def log_metrics(
        self,
        run_handle: str,
        metrics: Mapping[str, int | float],
    ) -> None:
        """Log only allowlisted numeric operational telemetry."""

        timestamp = int(time() * 1_000)
        safe_metrics = [
            Metric(key, float(value), timestamp, 0)
            for key, value in metrics.items()
            if key in _SAFE_METRICS
        ]
        if safe_metrics:
            self._client.log_batch(run_handle, metrics=safe_metrics)

    def log_params(
        self,
        run_handle: str,
        params: Mapping[str, TrackingValue],
    ) -> None:
        """Log allowlisted parameters and numbered SHA-256 prompt hashes."""

        safe_params = [
            Param(key, str(value))
            for key, value in params.items()
            if key in _SAFE_PARAMS or key.startswith("prompt_hash_attempt_")
        ]
        if safe_params:
            self._client.log_batch(run_handle, params=safe_params)

    def log_tags(
        self,
        run_handle: str,
        tags: Mapping[str, TrackingValue],
    ) -> None:
        """Log only bounded run classifications, never arbitrary metadata."""

        safe_tags = [
            RunTag(key, str(value)) for key, value in tags.items() if key in _SAFE_TAGS
        ]
        if safe_tags:
            self._client.log_batch(run_handle, tags=safe_tags)

    def log_artifact(
        self,
        run_handle: str,
        artifact_name: str,
        content: str,
    ) -> None:
        """Log only explicitly approved JSON summaries without caller file I/O."""

        normalized_name = PurePosixPath(artifact_name).name
        if normalized_name not in _SAFE_ARTIFACTS:
            return
        self._client.log_text(run_handle, content, normalized_name)

    def end_run(self, run_handle: str, status: RunStatus = "FINISHED") -> None:
        """End a child and close its workflow when marked as terminal."""

        with self._lock:
            self._client.set_terminated(run_handle, status=status)
            parent_context = self._agent_parents.pop(run_handle, None)
            if parent_context is None:
                return
            workflow_run_id, agent_name, closes_workflow = parent_context
            self._workflow_agents[workflow_run_id].append(
                {"agent_name": agent_name, "status": status}
            )
            if not closes_workflow:
                return
            parent_id = self._workflow_runs.pop(workflow_run_id)
            started_ms = self._workflow_started_ms.pop(workflow_run_id)
            duration_ms = max(0, int(time() * 1_000) - started_ms)
            self.log_metrics(parent_id, {"workflow_duration_ms": duration_ms})
            workflow_summary = {
                "run_id": workflow_run_id,
                "status": status,
                "agents": sorted(
                    self._workflow_agents.pop(workflow_run_id),
                    key=lambda agent: agent["agent_name"],
                ),
            }
            self.log_artifact(
                parent_id,
                "workflow_summary.json",
                json.dumps(workflow_summary, indent=2, sort_keys=True),
            )
            self._client.set_terminated(parent_id, status=status)
