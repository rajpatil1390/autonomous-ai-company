"""Define provider-neutral metrics contracts used by application orchestrators.

Keeping the protocol separate from the Prometheus adapter prevents agents and
other application code from depending on a monitoring vendor. The deliberately
narrow label vocabulary also prevents high-cardinality or sensitive values from
becoming part of the process-wide metrics surface.
"""

from collections.abc import Mapping
import logging
from typing import Protocol, TypeAlias, runtime_checkable


MetricValue: TypeAlias = int | float
MetricLabels: TypeAlias = Mapping[str, str]
_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class MetricsCollector(Protocol):
    """Describe the only metrics operations available to application code."""

    def increment_counter(
        self,
        name: str,
        value: MetricValue = 1,
        labels: MetricLabels | None = None,
    ) -> None:
        """Increase one monotonically growing metric by a non-negative value."""

    def observe_histogram(
        self,
        name: str,
        value: MetricValue,
        labels: MetricLabels | None = None,
    ) -> None:
        """Observe one non-negative duration or distribution value."""

    def set_gauge(
        self,
        name: str,
        value: MetricValue,
        labels: MetricLabels | None = None,
    ) -> None:
        """Set one instantaneous value that may increase or decrease."""


class NullMetricsCollector:
    """Preserve the metrics contract with zero side effects when disabled."""

    def increment_counter(
        self,
        name: str,
        value: MetricValue = 1,
        labels: MetricLabels | None = None,
    ) -> None:
        """Discard one counter increment intentionally."""

    def observe_histogram(
        self,
        name: str,
        value: MetricValue,
        labels: MetricLabels | None = None,
    ) -> None:
        """Discard one histogram observation intentionally."""

    def set_gauge(
        self,
        name: str,
        value: MetricValue,
        labels: MetricLabels | None = None,
    ) -> None:
        """Discard one gauge value intentionally."""


def record_generation_metrics(
    collector: MetricsCollector,
    *,
    agent: str,
    provider: str,
    model: str,
    latency_ms: float | None,
    total_tokens: int | None,
) -> None:
    """Record one successful generation using only bounded operational labels."""

    try:
        labels = {
            "agent": agent,
            "provider": provider,
            "model": model,
            "status": "success",
        }
        collector.increment_counter("llm_requests_total", labels=labels)
        if latency_ms is not None:
            collector.observe_histogram(
                "llm_latency_seconds",
                latency_ms / 1_000,
                labels,
            )
        if total_tokens is not None:
            collector.increment_counter("llm_tokens_total", total_tokens, labels)
    except Exception as error:
        _LOGGER.error("Generation metrics failed: %s", type(error).__name__)


def record_failed_generation_metrics(
    collector: MetricsCollector,
    *,
    agent: str,
) -> None:
    """Record a failed request without inventing unavailable provider telemetry."""

    try:
        collector.increment_counter(
            "llm_requests_total",
            labels={
                "agent": agent,
                "provider": "unknown",
                "model": "unknown",
                "status": "failure",
            },
        )
    except Exception as error:
        _LOGGER.error("Failed-generation metrics failed: %s", type(error).__name__)


def record_agent_metrics(
    collector: MetricsCollector,
    *,
    agent: str,
    duration_seconds: float,
    retry_count: int,
    success: bool,
) -> None:
    """Record one completed agent lifecycle without run-specific labels."""

    try:
        status = "success" if success else "failure"
        labels = {"agent": agent, "status": status}
        collector.increment_counter("agent_runs_total", labels=labels)
        collector.observe_histogram("agent_duration_seconds", duration_seconds, labels)
        if retry_count:
            collector.increment_counter(
                "agent_retry_total",
                retry_count,
                {"agent": agent},
            )
        if not success:
            collector.increment_counter("agent_failures_total", labels={"agent": agent})
    except Exception as error:
        _LOGGER.error("Agent metrics failed: %s", type(error).__name__)
