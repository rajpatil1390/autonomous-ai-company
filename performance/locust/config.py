"""Load Locust configuration exclusively from the process environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


class LoadTestConfigurationError(ValueError):
    """Report missing load-test configuration before traffic is generated."""


def _required_environment(name: str) -> str:
    """Return a non-empty environment value without providing unsafe defaults."""

    value = os.getenv(name, "").strip()
    if not value:
        raise LoadTestConfigurationError(
            f"{name} must be supplied through the environment"
        )
    return value


@dataclass(frozen=True, slots=True)
class LoadTestConfig:
    """Hold request-scoped test settings without exposing mutable credentials."""

    base_url: str
    username: str
    password: str
    request_timeout_seconds: float


def load_config() -> LoadTestConfig:
    """Build a validated configuration for one Locust worker process."""

    timeout_text = os.getenv("PERF_REQUEST_TIMEOUT_SECONDS", "45")
    try:
        timeout = float(timeout_text)
    except ValueError as error:
        raise LoadTestConfigurationError(
            "PERF_REQUEST_TIMEOUT_SECONDS must be numeric"
        ) from error
    if timeout <= 0:
        raise LoadTestConfigurationError(
            "PERF_REQUEST_TIMEOUT_SECONDS must be positive"
        )
    return LoadTestConfig(
        base_url=_required_environment("BASE_URL").rstrip("/"),
        username=_required_environment("PERF_USERNAME"),
        password=_required_environment("PERF_PASSWORD"),
        request_timeout_seconds=timeout,
    )


def workflow_payload() -> dict[str, Any]:
    """Return one small, valid and deterministic workflow request body."""

    return {
        "dataset": [
            {
                "revenue": 100,
                "cost": 60,
                "customer_id": "locust-customer",
                "segment": "Enterprise",
            }
        ],
        "previous_dataset": [
            {
                "revenue": 80,
                "cost": 50,
                "customer_id": "locust-customer",
                "segment": "Enterprise",
            }
        ],
        "data_scientist_series": [10, 20, 30],
        "business_context": "Controlled Locust performance test workload.",
        "executive_question": "Which priority should be approved?",
    }
