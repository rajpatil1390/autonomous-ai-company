"""Static contract tests for production performance-testing assets."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
PERFORMANCE_DIRECTORY = ROOT / "performance"
K6_DIRECTORY = PERFORMANCE_DIRECTORY / "k6"
LOCUST_DIRECTORY = PERFORMANCE_DIRECTORY / "locust"
REPORT_DIRECTORY = PERFORMANCE_DIRECTORY / "reports"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "performance.yml"
K6_SCRIPTS = {
    name: K6_DIRECTORY / f"{name}.js"
    for name in ("workflow", "login", "streaming", "metrics")
}
LOCUST_FILES = {
    name: LOCUST_DIRECTORY / name for name in ("locustfile.py", "users.py", "config.py")
}


def load_workflow() -> dict[str, Any]:
    """Parse GitHub workflow YAML without coercing its `on` key."""

    workflow = yaml.load(
        WORKFLOW_PATH.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert isinstance(workflow, dict)
    return workflow


def workflow_steps() -> list[dict[str, Any]]:
    """Return the single smoke job's ordered steps."""

    steps = load_workflow()["jobs"]["performance-smoke"]["steps"]
    assert all(isinstance(step, dict) for step in steps)
    return steps


def step_named(name: str) -> dict[str, Any]:
    """Return one uniquely named workflow step."""

    matches = [step for step in workflow_steps() if step.get("name") == name]
    assert len(matches) == 1
    return matches[0]


def javascript_text(name: str) -> str:
    """Read one UTF-8 k6 script."""

    return K6_SCRIPTS[name].read_text(encoding="utf-8")


def test_all_requested_performance_assets_exist_and_are_nonempty() -> None:
    """The requested k6, Locust, report, workflow, and test assets must exist."""

    paths = [
        *K6_SCRIPTS.values(),
        K6_DIRECTORY / "thresholds.json",
        *LOCUST_FILES.values(),
        REPORT_DIRECTORY / "README-performance.md",
        WORKFLOW_PATH,
    ]
    assert all(path.is_file() for path in paths)
    assert all(path.stat().st_size > 0 for path in paths)


def test_thresholds_define_every_workload_and_exact_acceptance_policy() -> None:
    """Concurrency profiles and service objectives should match the contract."""

    policy = json.loads((K6_DIRECTORY / "thresholds.json").read_text())
    profiles = policy["profiles"]
    assert set(profiles) == {"smoke", "normal", "peak", "stress", "spike"}
    assert profiles["smoke"]["vus"] == 5
    assert profiles["normal"]["vus"] == 50
    assert profiles["peak"]["vus"] == 200
    assert profiles["stress"]["vus"] == 500
    assert profiles["spike"]["startVUs"] == 0
    assert [stage["target"] for stage in profiles["spike"]["stages"]] == [
        500,
        500,
        0,
    ]

    thresholds = policy["thresholds"]
    assert thresholds["health_p95"] == {
        "metric": "http_req_duration{endpoint:health}",
        "limit": "p(95)<100",
    }
    assert thresholds["login_p95"] == {
        "metric": "http_req_duration{endpoint:login}",
        "limit": "p(95)<300",
    }
    assert thresholds["workflow_p95"] == {
        "metric": "http_req_duration{endpoint:workflow}",
        "limit": "p(95)<3000",
    }
    assert thresholds["error_rate"]["limit"] == "rate<0.01"
    assert thresholds["successful_checks"]["limit"] == "rate>0.99"


def test_k6_scripts_have_balanced_static_syntax_and_standard_entrypoints() -> None:
    """Scripts should be structurally valid modules without requiring k6 locally."""

    pairs = {"(": ")", "[": "]", "{": "}"}
    for path in K6_SCRIPTS.values():
        text = path.read_text(encoding="utf-8")
        for opening, closing in pairs.items():
            assert text.count(opening) == text.count(closing)
        assert "import http from 'k6/http';" in text
        assert "export const options" in text
        assert "export default function" in text
        assert "export function handleSummary" in text
        assert "JSON.parse(open('./thresholds.json'))" in text


def test_k6_covers_every_required_endpoint_with_correct_authentication() -> None:
    """The endpoint-focused scripts must exercise the complete production surface."""

    combined = "\n".join(javascript_text(name) for name in K6_SCRIPTS)
    for endpoint in (
        "/health",
        "/auth/login",
        "/workflow/run",
        "/workflow/stream",
        "/metrics",
    ):
        assert endpoint in combined
    assert "Authorization: `Bearer ${token}`" in javascript_text("workflow")
    assert "Authorization: `Bearer ${token}`" in javascript_text("streaming")
    assert "Accept: 'text/event-stream'" in javascript_text("streaming")
    assert "event: workflow_started" in javascript_text("streaming")
    assert "event: workflow_completed" in javascript_text("streaming")
    assert "event: workflow_failed" in javascript_text("streaming")


def test_k6_workflow_payload_matches_the_strict_api_contract() -> None:
    """Both protected workflow scripts must supply every explicit input field."""

    required_fields = {
        "dataset",
        "previous_dataset",
        "data_scientist_series",
        "business_context",
        "executive_question",
    }
    for name in ("workflow", "streaming"):
        text = javascript_text(name)
        assert all(re.search(rf"\b{field}\s*:", text) for field in required_fields)


def test_k6_uses_environment_configuration_without_urls_or_credentials() -> None:
    """Targets and credentials must be injected instead of committed."""

    combined = "\n".join(javascript_text(name) for name in K6_SCRIPTS)
    assert "requiredEnvironment('BASE_URL')" in combined
    assert "requiredEnvironment('PERF_USERNAME')" in combined
    assert "requiredEnvironment('PERF_PASSWORD')" in combined
    assert not re.search(r"https?://", combined)
    assert "admin123" not in combined
    assert not re.search(r"const\s+password\s*=\s*['\"]", combined)


def test_locust_python_has_valid_syntax_without_importing_locust() -> None:
    """Every Locust source file should parse using the supported Python runtime."""

    for path in LOCUST_FILES.values():
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_locust_defines_realistic_roles_and_think_times() -> None:
    """Viewer, Analyst, and Manager should be concrete weighted user classes."""

    tree = ast.parse(LOCUST_FILES["users.py"].read_text(encoding="utf-8"))
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    assert {"PlatformUser", "Viewer", "Analyst", "Manager"} <= set(classes)
    for role in ("Viewer", "Analyst", "Manager"):
        node = classes[role]
        assert any(
            isinstance(base, ast.Name) and base.id == "PlatformUser"
            for base in node.bases
        )
        methods = {
            item.name: item for item in node.body if isinstance(item, ast.FunctionDef)
        }
        assert {
            "view_health",
            "view_metrics",
            "execute_workflow",
            "stream_workflow",
        } <= set(methods)
        assert any(
            isinstance(item, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "wait_time"
                for target in item.targets
            )
            for item in node.body
        )


def test_every_locust_role_authenticates_executes_and_streams() -> None:
    """Shared helpers and every role must cover protected workflow behavior."""

    users = LOCUST_FILES["users.py"].read_text(encoding="utf-8")
    assert "self._authenticate()" in users
    for endpoint in (
        '"/auth/login"',
        '"/health"',
        '"/metrics"',
        '"/workflow/run"',
        '"/workflow/stream"',
    ):
        assert endpoint in users
    assert "stream=True" in users
    assert "event: workflow_started" in users
    assert "event: workflow_completed" in users
    assert "event: workflow_failed" in users
    for role_block in re.split(r"\nclass (?:Viewer|Analyst|Manager)\(", users)[1:]:
        assert "self._execute_workflow()" in role_block
        assert "self._stream_workflow()" in role_block


def test_locust_configuration_has_no_hardcoded_target_or_credentials() -> None:
    """Locust configuration should fail closed when protected values are absent."""

    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in LOCUST_FILES.values()
    )
    assert '"BASE_URL"' in combined
    assert '"PERF_USERNAME"' in combined
    assert '"PERF_PASSWORD"' in combined
    assert "LoadTestConfigurationError" in combined
    assert not re.search(r"https?://", combined)
    assert "admin123" not in combined
    assert "autonomous_ai_company" not in combined


def test_performance_workflow_is_manual_smoke_only() -> None:
    """Heavy profiles must never execute from push or pull-request events."""

    workflow = load_workflow()
    assert workflow["on"] == {"workflow_dispatch": ""}
    assert set(workflow["jobs"]) == {"performance-smoke"}
    job = workflow["jobs"]["performance-smoke"]
    assert job["env"]["LOAD_PROFILE"] == "smoke"
    assert job["env"]["BASE_URL"] == "${{ vars.PERFORMANCE_BASE_URL }}"
    assert job["env"]["PERF_USERNAME"] == ("${{ secrets.PERFORMANCE_USERNAME }}")
    assert job["env"]["PERF_PASSWORD"] == ("${{ secrets.PERFORMANCE_PASSWORD }}")
    assert workflow["concurrency"]["cancel-in-progress"] == "false"


def test_workflow_installs_tools_and_runs_both_smoke_suites() -> None:
    """The manual job should provision pinned tools and run five-user workloads."""

    k6_install = step_named("Install k6")
    assert re.fullmatch(r"grafana/setup-k6-action@[0-9a-f]{40}", k6_install["uses"])
    assert k6_install["with"]["k6-version"] == "v2.0.0"
    assert "locust==2.44.4" in step_named("Install Locust")["run"]

    k6_run = step_named("Run k6 smoke profile")["run"]
    assert "for script in workflow login streaming metrics" in k6_run
    assert "LOAD_PROFILE=${LOAD_PROFILE}" in k6_run
    assert "k6-${script}.json" in k6_run
    assert "result=0" in k6_run
    assert "result=1" in k6_run
    assert 'exit "${result}"' in k6_run

    locust_step = step_named("Run Locust smoke profile")
    assert locust_step["if"] == "${{ !cancelled() }}"
    locust_run = locust_step["run"]
    assert "--users 5" in locust_run
    assert "--spawn-rate 1" in locust_run
    assert "--run-time 30s" in locust_run
    assert "--html performance/reports/generated/locust.html" in locust_run


def test_workflow_collects_and_uploads_every_required_artifact() -> None:
    """Raw results, human-readable output, and summaries must be retained."""

    summary_step = step_named("Collect summary statistics")
    assert summary_step["if"] == "always()"
    summary = summary_step["run"]
    assert 'glob("k6-*-summary.json")' in summary
    assert 'report_dir / "locust_stats.csv"' in summary
    assert 'report_dir / "summary.md"' in summary

    upload = step_named("Upload performance artifacts")
    assert upload["if"] == "always()"
    paths = upload["with"]["path"]
    assert "k6-*.json" in paths
    assert "locust.html" in paths
    assert "locust*.csv" in paths
    assert "summary.md" in paths
    assert upload["with"]["if-no-files-found"] == "error"


def test_workflow_contains_no_hardcoded_url_or_credentials() -> None:
    """The workflow should consume protected configuration without exposing it."""

    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert not re.search(r"https?://[A-Za-z0-9]", text)
    assert "admin123" not in text
    assert "PERFORMANCE_BASE_URL" in text
    assert "secrets.PERFORMANCE_USERNAME" in text
    assert "secrets.PERFORMANCE_PASSWORD" in text
    assert "${BASE_URL}" in text


def test_documentation_covers_execution_analysis_and_capacity_planning() -> None:
    """Operators should be able to run, interpret, and act on the tests safely."""

    documentation = (REPORT_DIRECTORY / "README-performance.md").read_text(
        encoding="utf-8"
    )
    for heading in (
        "Safety prerequisites",
        "k6 execution",
        "Locust execution",
        "Workload intent",
        "Interpreting results",
        "Bottleneck analysis",
        "Capacity planning and scaling",
    ):
        assert f"## {heading}" in documentation
    for profile in ("Smoke", "Normal", "Peak", "Stress", "Spike"):
        assert profile in documentation
    assert "The profiles define concurrency" in documentation
    assert "authoritative throughput result" in documentation
    assert "Grafana" in documentation
    assert "Prometheus" in documentation
    assert "Kubernetes HPA" in documentation
