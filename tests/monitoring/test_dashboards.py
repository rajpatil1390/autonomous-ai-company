"""Static validation for provisioned Grafana and Prometheus assets."""

import json
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_DIRECTORY = ROOT / "monitoring" / "grafana" / "dashboards"
DASHBOARD_FILES = tuple(sorted(DASHBOARD_DIRECTORY.glob("*.json")))
PLACEHOLDER_TITLE = "Metric Unavailable (Not Yet Instrumented)"
METRIC_PREFIX = "autonomous_ai_company_"

EXPORTED_SERIES = {
    f"{METRIC_PREFIX}http_requests_total",
    f"{METRIC_PREFIX}http_request_duration_seconds_bucket",
    f"{METRIC_PREFIX}http_request_duration_seconds_sum",
    f"{METRIC_PREFIX}http_request_duration_seconds_count",
    f"{METRIC_PREFIX}workflow_runs_total",
    f"{METRIC_PREFIX}workflow_success_total",
    f"{METRIC_PREFIX}workflow_failures_total",
    f"{METRIC_PREFIX}workflow_duration_seconds_bucket",
    f"{METRIC_PREFIX}workflow_duration_seconds_sum",
    f"{METRIC_PREFIX}workflow_duration_seconds_count",
    f"{METRIC_PREFIX}workflow_active",
    f"{METRIC_PREFIX}agent_runs_total",
    f"{METRIC_PREFIX}agent_duration_seconds_bucket",
    f"{METRIC_PREFIX}agent_duration_seconds_sum",
    f"{METRIC_PREFIX}agent_duration_seconds_count",
    f"{METRIC_PREFIX}agent_retry_total",
    f"{METRIC_PREFIX}agent_failures_total",
    f"{METRIC_PREFIX}llm_requests_total",
    f"{METRIC_PREFIX}llm_latency_seconds_bucket",
    f"{METRIC_PREFIX}llm_latency_seconds_sum",
    f"{METRIC_PREFIX}llm_latency_seconds_count",
    f"{METRIC_PREFIX}llm_tokens_total",
    f"{METRIC_PREFIX}audit_events_total",
    f"{METRIC_PREFIX}audit_failures_total",
    f"{METRIC_PREFIX}auth_login_total",
    f"{METRIC_PREFIX}auth_failures_total",
}


def load_json(path: Path) -> dict[str, object]:
    """Parse one dashboard as strict JSON."""

    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> dict[str, object]:
    """Parse one infrastructure document as YAML."""

    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def panels_by_title(dashboard: dict[str, object]) -> dict[str, dict[str, object]]:
    """Index the dashboard's top-level panels by their visible title."""

    panels = dashboard["panels"]
    assert isinstance(panels, list)
    return {panel["title"]: panel for panel in panels}


def test_dashboard_files_are_valid_and_have_unique_identities() -> None:
    """All five dashboards should parse and have stable unique identities."""

    assert [path.name for path in DASHBOARD_FILES] == [
        "agents.json",
        "audit.json",
        "llm.json",
        "overview.json",
        "workflow.json",
    ]
    dashboards = [load_json(path) for path in DASHBOARD_FILES]
    uids = [dashboard["uid"] for dashboard in dashboards]
    titles = [dashboard["title"] for dashboard in dashboards]

    assert len(uids) == len(set(uids)) == 5
    assert len(titles) == len(set(titles)) == 5
    for dashboard in dashboards:
        assert dashboard["schemaVersion"] >= 41
        assert dashboard["editable"] is False
        assert dashboard["refresh"] == "30s"
        panels = dashboard["panels"]
        assert isinstance(panels, list) and panels
        panel_ids = [panel["id"] for panel in panels]
        assert len(panel_ids) == len(set(panel_ids))


def test_overview_and_workflow_dashboards_contain_required_panels() -> None:
    """Executive and workflow dashboards should cover the requested lifecycle."""

    overview = panels_by_title(load_json(DASHBOARD_DIRECTORY / "overview.json"))
    assert set(overview) == {
        "HTTP Requests/sec",
        "Active Workflows",
        "Workflow Success Rate",
        "Workflow Failure Rate",
        "Average Workflow Duration",
        "Workflow Duration P95",
        "LLM Requests/sec",
        "LLM Latency",
        "Agent Retry Rate",
    }

    workflow = panels_by_title(load_json(DASHBOARD_DIRECTORY / "workflow.json"))
    assert {
        "Workflow Completions",
        "Success vs Failure",
        "Parallel Agent Activity",
        "Current Active Workflows",
        "Workflow Duration Histogram",
        PLACEHOLDER_TITLE,
    } == set(workflow)
    assert "Workflow Starts" in workflow[PLACEHOLDER_TITLE]["options"]["content"]


def test_agent_dashboard_has_five_panels_for_every_agent() -> None:
    """Each specialist and executive agent should have the same operational view."""

    agents = panels_by_title(load_json(DASHBOARD_DIRECTORY / "agents.json"))
    expected = {
        f"{agent} - {metric}"
        for agent in ("Finance", "Marketing", "Data Scientist", "Report", "CEO")
        for metric in (
            "Requests",
            "Average Duration",
            "P95 Duration",
            "Failures",
            "Retries",
        )
    }
    assert set(agents) == expected
    assert len(agents) == 25


def test_llm_and_audit_dashboards_contain_required_panels() -> None:
    """Provider and audit dashboards should use available measurements honestly."""

    llm = panels_by_title(load_json(DASHBOARD_DIRECTORY / "llm.json"))
    assert set(llm) == {
        "Requests by Provider",
        "Requests by Model",
        "Latency",
        "Token Usage",
        "Failures",
        "Retries",
    }

    audit = panels_by_title(load_json(DASHBOARD_DIRECTORY / "audit.json"))
    assert set(audit) == {
        "Audit Events/sec",
        "Audit Failures",
        "Database Writes",
        PLACEHOLDER_TITLE,
    }
    assert "Audit Latency" in audit[PLACEHOLDER_TITLE]["options"]["content"]


def test_unavailable_panels_have_no_queries_or_estimates() -> None:
    """Unavailable measurements must remain explicit query-free placeholders."""

    placeholders = []
    for path in DASHBOARD_FILES:
        dashboard = load_json(path)
        placeholders.extend(
            panel
            for panel in dashboard["panels"]
            if panel["title"] == PLACEHOLDER_TITLE
        )

    assert len(placeholders) == 2
    assert {panel["description"] for panel in placeholders} == {
        "Workflow Starts is intentionally unavailable.",
        "Audit Latency is intentionally unavailable.",
    }
    for panel in placeholders:
        assert panel["type"] == "text"
        assert panel["targets"] == []
        assert "No PromQL query is configured" in panel["options"]["content"]


def test_every_promql_expression_uses_only_exported_metrics() -> None:
    """Dashboard queries must not invent or reference unrelated metric series."""

    expression_count = 0
    referenced: set[str] = set()
    metric_pattern = re.compile(r"autonomous_ai_company_[a-zA-Z_:][a-zA-Z0-9_:]*")

    for path in DASHBOARD_FILES:
        dashboard = load_json(path)
        for panel in dashboard["panels"]:
            for target in panel.get("targets", []):
                expression = target.get("expr")
                assert isinstance(expression, str) and expression.strip()
                assert target["datasource"]["uid"] == "prometheus"
                expression_count += 1
                referenced.update(metric_pattern.findall(expression))

    assert expression_count == 48
    assert referenced
    assert referenced <= EXPORTED_SERIES


def test_grafana_provisioning_is_valid_and_automatic() -> None:
    """Grafana should provision one default datasource and one file provider."""

    datasource = load_yaml(
        ROOT
        / "monitoring"
        / "grafana"
        / "provisioning"
        / "datasources"
        / "datasource.yaml"
    )
    assert datasource["apiVersion"] == 1
    assert len(datasource["datasources"]) == 1
    prometheus = datasource["datasources"][0]
    assert prometheus == {
        "name": "Prometheus",
        "uid": "prometheus",
        "type": "prometheus",
        "access": "proxy",
        "url": "http://prometheus:9090",
        "isDefault": True,
        "editable": False,
        "jsonData": {"httpMethod": "POST", "timeInterval": "15s"},
    }

    provisioning = load_yaml(
        ROOT
        / "monitoring"
        / "grafana"
        / "provisioning"
        / "dashboards"
        / "dashboards.yaml"
    )
    assert provisioning["apiVersion"] == 1
    assert len(provisioning["providers"]) == 1
    provider = provisioning["providers"][0]
    assert provider["type"] == "file"
    assert provider["editable"] is False
    assert provider["options"]["path"] == "/var/lib/grafana/dashboards"
    assert provider["updateIntervalSeconds"] == 30


def test_prometheus_configuration_scrapes_the_existing_metrics_endpoint() -> None:
    """Prometheus should scrape the host API without requiring an app container."""

    configuration = load_yaml(ROOT / "monitoring" / "prometheus" / "prometheus.yml")
    assert configuration["global"] == {
        "scrape_interval": "15s",
        "scrape_timeout": "10s",
        "evaluation_interval": "15s",
    }
    assert len(configuration["scrape_configs"]) == 1
    scrape = configuration["scrape_configs"][0]
    assert scrape["job_name"] == "autonomous-ai-company"
    assert scrape["metrics_path"] == "/metrics"
    assert scrape["scheme"] == "http"
    assert scrape["honor_labels"] is False
    assert scrape["static_configs"] == [
        {
            "targets": ["host.docker.internal:8000"],
            "labels": {"service": "autonomous-ai-company"},
        }
    ]


def test_monitoring_compose_is_valid_isolated_and_secret_safe() -> None:
    """Compose should run only monitoring services with explicit read-only mounts."""

    compose_path = ROOT / "docker-compose.monitoring.yml"
    compose = load_yaml(compose_path)
    assert compose["name"] == "autonomous-ai-company-monitoring"
    assert set(compose["services"]) == {"prometheus", "grafana"}
    assert set(compose["volumes"]) == {"prometheus_data", "grafana_data"}

    prometheus = compose["services"]["prometheus"]
    assert prometheus["image"] == "prom/prometheus:v3.12.0"
    assert "127.0.0.1:${PROMETHEUS_PORT:-9090}:9090" in prometheus["ports"]
    assert (
        "./monitoring/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro"
        in prometheus["volumes"]
    )
    assert "host.docker.internal:host-gateway" in prometheus["extra_hosts"]

    grafana = compose["services"]["grafana"]
    assert grafana["image"] == "grafana/grafana:13.0.2"
    assert "127.0.0.1:${GRAFANA_PORT:-3000}:3000" in grafana["ports"]
    assert (
        "./monitoring/grafana/provisioning:/etc/grafana/provisioning:ro"
        in grafana["volumes"]
    )
    assert (
        "./monitoring/grafana/dashboards:/var/lib/grafana/dashboards:ro"
        in grafana["volumes"]
    )
    password = grafana["environment"]["GF_SECURITY_ADMIN_PASSWORD"]
    assert password == "${GRAFANA_ADMIN_PASSWORD:?GRAFANA_ADMIN_PASSWORD is required}"
    assert "changeme" not in compose_path.read_text(encoding="utf-8").lower()
