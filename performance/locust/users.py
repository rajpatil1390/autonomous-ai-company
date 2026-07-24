"""Define realistic authenticated Locust user roles for the platform."""

from __future__ import annotations

from typing import Any

from locust import HttpUser, between, task

from config import LoadTestConfig, load_config, workflow_payload


class PlatformUser(HttpUser):
    """Share safe authentication and request helpers across concrete roles."""

    abstract = True
    config: LoadTestConfig
    authorization_headers: dict[str, str]

    def on_start(self) -> None:
        """Authenticate each simulated user before protected requests begin."""

        self.config = load_config()
        self.client.base_url = self.config.base_url
        self.authorization_headers = {}
        self._authenticate()

    def _authenticate(self) -> None:
        """Obtain a bearer token while recording authentication failures."""

        with self.client.post(
            "/auth/login",
            json={
                "username": self.config.username,
                "password": self.config.password,
            },
            name="/auth/login",
            timeout=self.config.request_timeout_seconds,
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"login returned HTTP {response.status_code}")
                return
            try:
                token = response.json()["access_token"]
            except (KeyError, TypeError, ValueError):
                response.failure("login response did not contain an access token")
                return
            self.authorization_headers = {"Authorization": f"Bearer {token}"}
            response.success()

    def _health(self) -> None:
        """Read the public health endpoint."""

        self.client.get(
            "/health",
            name="/health",
            timeout=self.config.request_timeout_seconds,
        )

    def _metrics(self) -> None:
        """Read the public Prometheus endpoint when production metrics are enabled."""

        self.client.get(
            "/metrics",
            name="/metrics",
            timeout=self.config.request_timeout_seconds,
        )

    def _execute_workflow(self) -> None:
        """Run one authenticated workflow and validate its terminal response."""

        with self.client.post(
            "/workflow/run",
            json=workflow_payload(),
            headers=self.authorization_headers,
            name="/workflow/run",
            timeout=self.config.request_timeout_seconds,
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"workflow returned HTTP {response.status_code}")
                return
            try:
                recommendation = response.json()["final_recommendation"]
            except (KeyError, TypeError, ValueError):
                response.failure("workflow response was incomplete")
                return
            if not recommendation:
                response.failure("workflow recommendation was empty")
                return
            response.success()

    def _stream_workflow(self) -> None:
        """Consume one authenticated SSE response through a terminal event."""

        headers = {
            **self.authorization_headers,
            "Accept": "text/event-stream",
        }
        with self.client.post(
            "/workflow/stream",
            json=workflow_payload(),
            headers=headers,
            name="/workflow/stream",
            timeout=self.config.request_timeout_seconds,
            stream=True,
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"stream returned HTTP {response.status_code}")
                return
            started = False
            terminal = False
            for raw_line in response.iter_lines():
                line = _line_text(raw_line)
                started = started or line == "event: workflow_started"
                if line in {
                    "event: workflow_completed",
                    "event: workflow_failed",
                }:
                    terminal = True
                    break
            if not started or not terminal:
                response.failure("stream did not include start and terminal events")
                return
            response.success()


def _line_text(value: Any) -> str:
    """Normalize Requests byte or text SSE lines for deterministic comparisons."""

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


class Viewer(PlatformUser):
    """Model read-heavy users who occasionally request full analysis."""

    weight = 5
    wait_time = between(2, 6)

    @task(5)
    def view_health(self) -> None:
        """Check service readiness."""

        self._health()

    @task(3)
    def view_metrics(self) -> None:
        """Inspect platform metrics."""

        self._metrics()

    @task(1)
    def execute_workflow(self) -> None:
        """Occasionally execute a complete workflow."""

        self._execute_workflow()

    @task(1)
    def stream_workflow(self) -> None:
        """Occasionally follow workflow progress."""

        self._stream_workflow()


class Analyst(PlatformUser):
    """Model users who repeatedly execute and observe analytical workflows."""

    weight = 3
    wait_time = between(2, 5)

    @task(1)
    def view_health(self) -> None:
        """Check service readiness."""

        self._health()

    @task(1)
    def view_metrics(self) -> None:
        """Inspect platform metrics."""

        self._metrics()

    @task(4)
    def execute_workflow(self) -> None:
        """Execute the analyst's primary workflow operation."""

        self._execute_workflow()

    @task(3)
    def stream_workflow(self) -> None:
        """Follow workflow progress in real time."""

        self._stream_workflow()


class Manager(PlatformUser):
    """Model decision-makers who favor completed and streamed recommendations."""

    weight = 2
    wait_time = between(4, 10)

    @task(1)
    def view_health(self) -> None:
        """Check service readiness."""

        self._health()

    @task(1)
    def view_metrics(self) -> None:
        """Inspect platform metrics."""

        self._metrics()

    @task(3)
    def execute_workflow(self) -> None:
        """Request a completed executive recommendation."""

        self._execute_workflow()

    @task(4)
    def stream_workflow(self) -> None:
        """Follow executive workflow progress to completion."""

        self._stream_workflow()
