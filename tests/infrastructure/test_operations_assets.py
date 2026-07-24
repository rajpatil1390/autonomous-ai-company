"""Static validation for SRE operational assets."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
OPERATIONS = ROOT / "operations"
ALERTMANAGER_PATH = OPERATIONS / "alertmanager" / "alertmanager.yml"
ROUTING_PATH = OPERATIONS / "alertmanager" / "routing.md"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "operations.yml"
SLO_FILES = {
    name: OPERATIONS / "slo" / f"{name}.md" for name in ("slos", "slis", "error-budget")
}
RUNBOOKS = {
    name: OPERATIONS / "runbooks" / f"{name}.md"
    for name in (
        "api-down",
        "high-latency",
        "authentication-failure",
        "database-unavailable",
        "llm-provider-failure",
        "workflow-failure",
    )
}
ONCALL_FILES = {
    name: OPERATIONS / "oncall" / name
    for name in (
        "escalation-policy.md",
        "incident-template.md",
        "postmortem-template.md",
    )
}
RUNBOOK_HEADINGS = (
    "Symptoms",
    "Diagnosis",
    "Dashboards",
    "Metrics",
    "Logs",
    "Recovery",
    "Escalation",
    "Rollback",
    "Verification",
)
EXPORTED_METRICS = {
    "agent_duration_seconds",
    "agent_failures_total",
    "agent_retry_total",
    "agent_runs_total",
    "audit_events_total",
    "audit_failures_total",
    "auth_failures_total",
    "auth_login_total",
    "http_request_duration_seconds",
    "http_requests_total",
    "llm_latency_seconds",
    "llm_requests_total",
    "llm_tokens_total",
    "workflow_active",
    "workflow_duration_seconds",
    "workflow_failures_total",
    "workflow_runs_total",
    "workflow_success_total",
}


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML mapping with safe construction."""

    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def load_workflow() -> dict[str, Any]:
    """Load Actions YAML without YAML 1.1 coercing the `on` key."""

    document = yaml.load(
        WORKFLOW_PATH.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert isinstance(document, dict)
    return document


def test_all_requested_operations_assets_exist_and_are_nonempty() -> None:
    """Every requested configuration, guide, template, and test input exists."""

    paths = [
        ALERTMANAGER_PATH,
        ROUTING_PATH,
        WORKFLOW_PATH,
        *SLO_FILES.values(),
        *RUNBOOKS.values(),
        *ONCALL_FILES.values(),
    ]
    assert len(paths) == 15
    assert all(path.is_file() for path in paths)
    assert all(path.stat().st_size > 0 for path in paths)


def test_alertmanager_default_route_and_grouping_policy() -> None:
    """The root route must group related alerts and use a safe placeholder."""

    config = load_yaml(ALERTMANAGER_PATH)
    assert config["global"] == {"resolve_timeout": "5m"}
    route = config["route"]
    assert route["receiver"] == "default-placeholder"
    assert route["group_by"] == ["alertname", "namespace", "service"]
    assert route["group_wait"] == "30s"
    assert route["group_interval"] == "5m"
    assert route["repeat_interval"] == "4h"


def test_alertmanager_has_explicit_warning_and_critical_routes() -> None:
    """Severity routes must select separate credential-free receivers."""

    routes = load_yaml(ALERTMANAGER_PATH)["route"]["routes"]
    by_matcher = {route["matchers"][0]: route for route in routes}
    assert set(by_matcher) == {'severity="critical"', 'severity="warning"'}
    critical = by_matcher['severity="critical"']
    warning = by_matcher['severity="warning"']
    assert critical["receiver"] == "critical-placeholder"
    assert critical["continue"] is False
    assert critical["repeat_interval"] == "30m"
    assert warning["receiver"] == "warning-placeholder"
    assert warning["continue"] is False
    assert warning["repeat_interval"] == "4h"


def test_alertmanager_inhibition_rules_suppress_only_related_alerts() -> None:
    """Critical symptoms suppress matching lower-value notifications only."""

    rules = load_yaml(ALERTMANAGER_PATH)["inhibit_rules"]
    assert len(rules) == 2
    assert rules[0]["source_matchers"] == ['severity="critical"']
    assert rules[0]["target_matchers"] == ['severity="warning"']
    assert rules[0]["equal"] == ["alertname", "namespace", "service"]
    assert rules[1]["source_matchers"] == [
        'alertname="APIUnavailable"',
        'severity="critical"',
    ]
    assert rules[1]["target_matchers"] == ['severity=~"warning|critical"']
    assert rules[1]["equal"] == ["namespace", "service"]


def test_alertmanager_receivers_are_placeholders_without_secrets() -> None:
    """Receiver definitions must not contain external integration credentials."""

    config = load_yaml(ALERTMANAGER_PATH)
    receivers = config["receivers"]
    assert {receiver["name"] for receiver in receivers} == {
        "critical-placeholder",
        "default-placeholder",
        "warning-placeholder",
    }
    assert all(set(receiver) == {"name"} for receiver in receivers)
    text = ALERTMANAGER_PATH.read_text(encoding="utf-8").lower()
    assert not re.search(
        r"(api_key|password|token|webhook_url|smtp_auth_password)", text
    )


def test_routing_guide_documents_policy_and_external_receiver_ownership() -> None:
    """Operators need routing, inhibition, and receiver integration guidance."""

    text = ROUTING_PATH.read_text(encoding="utf-8")
    for heading in (
        "Required alert labels",
        "Default route",
        "Warning route",
        "Critical route",
        "Inhibition",
        "Receiver integration",
        "Ownership and review",
    ):
        assert f"## {heading}" in text
    assert "outside source control" in text


def test_slos_define_every_required_service_objective() -> None:
    """Each objective must state target, measurement, budget, and cadence."""

    text = SLO_FILES["slos"].read_text(encoding="utf-8")
    expected_rows = {
        "API availability": "99.9%",
        "Workflow success rate": "99.0%",
        "Authentication reliability": "99.9%",
        "Audit persistence": "99.99%",
        "LLM latency": "95.0% below 5 seconds",
        "Streaming reliability": "99.0%",
    }
    for objective, target in expected_rows.items():
        row = next(
            line for line in text.splitlines() if line.startswith(f"| {objective} |")
        )
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert cells[1] == target
        assert all(cells[index] for index in (2, 3, 4))
    assert "rolling 30-day windows" in text


def test_slis_reference_only_exported_metrics_and_disclose_telemetry_gaps() -> None:
    """The SLI catalog must never invent application instrumentation."""

    text = SLO_FILES["slis"].read_text(encoding="utf-8")
    references = set(re.findall(r"autonomous_ai_company_([a-z_]+)", text))
    normalized = {
        name.removesuffix("_bucket").removesuffix("_count").removesuffix("_sum")
        for name in references
    }
    assert normalized <= EXPORTED_METRICS
    assert "no path label exists" in text
    assert "do not count terminal SSE events" in text
    assert "No exact PromQL is claimed" in text


def test_error_budget_policy_guides_release_decisions_without_fake_alerts() -> None:
    """Budget consumption must lead to explicit, reviewable release policy."""

    text = SLO_FILES["error-budget"].read_text(encoding="utf-8")
    for heading in (
        "Definition",
        "Release policy",
        "Burn rate",
        "Decision process",
        "Reset and review",
    ):
        assert f"## {heading}" in text
    assert "does not create Prometheus alert rules" in text
    assert "validated against real traffic before paging" in text


def test_runbooks_have_the_complete_operational_contract() -> None:
    """Every failure mode must be diagnosable, recoverable, and verifiable."""

    for path in RUNBOOKS.values():
        text = path.read_text(encoding="utf-8")
        for heading in RUNBOOK_HEADINGS:
            assert f"## {heading}" in text
        assert "SEV-" in text
        assert "rollback" in text.lower()


def test_runbooks_reference_only_existing_application_metrics() -> None:
    """Operational procedures must not direct responders to fictional metrics."""

    text = "\n".join(path.read_text(encoding="utf-8") for path in RUNBOOKS.values())
    references = set(re.findall(r"autonomous_ai_company_([a-z_]+)", text))
    normalized = {
        name.removesuffix("_bucket").removesuffix("_count").removesuffix("_sum")
        for name in references
    }
    assert normalized <= EXPORTED_METRICS


def test_oncall_policy_defines_severity_escalation_and_safe_handoffs() -> None:
    """The escalation policy must make ownership and timing unambiguous."""

    text = ONCALL_FILES["escalation-policy.md"].read_text(encoding="utf-8")
    for severity in ("SEV-1 Critical", "SEV-2 High", "SEV-3 Medium", "SEV-4 Low"):
        assert severity in text
    for heading in (
        "Incident Severity Matrix",
        "Escalation Flow",
        "Incident Roles",
        "Communication",
        "Handoff",
        "Review and Maintenance",
    ):
        assert f"## {heading}" in text
    assert "Never assume that sending a notification transfers ownership" in text


def test_incident_template_supports_live_coordination_and_communications() -> None:
    """The active record must capture impact, decisions, rollback, and closure."""

    text = ONCALL_FILES["incident-template.md"].read_text(encoding="utf-8")
    for heading in (
        "Incident Metadata",
        "Impact",
        "Detection",
        "Current Assessment",
        "Timeline",
        "Actions and Decisions",
        "Recovery and Rollback",
        "Communication Template",
        "Escalations",
        "Closure Checklist",
    ):
        assert f"## {heading}" in text
    assert "Do not include credentials or sensitive payloads" in text


def test_postmortem_template_is_blameless_and_action_oriented() -> None:
    """Postmortems must connect causes and budget impact to verified actions."""

    text = ONCALL_FILES["postmortem-template.md"].read_text(encoding="utf-8")
    for heading in (
        "Summary",
        "Impact",
        "Detection",
        "Timeline",
        "Root Cause and Contributing Factors",
        "Response and Recovery",
        "What Went Well",
        "What Could Be Improved",
        "Corrective Actions",
        "SLO and Error-Budget Decision",
        "Lessons and Follow-Up",
        "Approval",
    ):
        assert f"## {heading}" in text
    assert "without assigning\npersonal blame" in text
    assert "independently verifiable" in text


def test_operations_workflow_is_manual_validation_only() -> None:
    """The workflow must never deploy or execute operational changes."""

    workflow = load_workflow()
    assert workflow["on"] == {"workflow_dispatch": ""}
    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    assert list(jobs) == [
        "validate-alertmanager",
        "validate-documentation",
        "upload-artifacts",
    ]
    assert jobs["validate-documentation"]["needs"] == "validate-alertmanager"
    assert jobs["upload-artifacts"]["needs"] == [
        "validate-alertmanager",
        "validate-documentation",
    ]
    text = WORKFLOW_PATH.read_text(encoding="utf-8").lower()
    for forbidden in ("kubectl", "helm ", "amtool", "docker", "terraform"):
        assert forbidden not in text


def test_operations_workflow_validates_and_uploads_all_asset_groups() -> None:
    """Static checks must precede artifact publication with no missing groups."""

    workflow = load_workflow()
    jobs = workflow["jobs"]
    alert_steps = jobs["validate-alertmanager"]["steps"]
    assert any(
        step.get("name") == "Validate routing and inhibition contracts"
        for step in alert_steps
    )
    docs_steps = jobs["validate-documentation"]["steps"]
    assert any(
        step.get("name") == "Validate SLO, runbook, and on-call completeness"
        for step in docs_steps
    )
    upload_steps = jobs["upload-artifacts"]["steps"]
    upload = next(
        step
        for step in upload_steps
        if step.get("uses") == "actions/upload-artifact@v6"
    )
    paths = upload["with"]["path"]
    for asset_group in ("alertmanager", "slo", "runbooks", "oncall"):
        assert f"operations/{asset_group}/" in paths
    assert upload["with"]["if-no-files-found"] == "error"


def test_operations_assets_contain_no_credentials_or_real_receivers() -> None:
    """Committed operational assets must be safe templates without secrets."""

    paths = [
        ALERTMANAGER_PATH,
        ROUTING_PATH,
        WORKFLOW_PATH,
        *SLO_FILES.values(),
        *RUNBOOKS.values(),
        *ONCALL_FILES.values(),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    secret_assignment = re.compile(
        r"(?im)^\s*(password|api[_-]?key|secret|token)\s*[:=]\s*[^<{$\s]"
    )
    assert secret_assignment.search(combined) is None
    assert "pagerduty_configs:" not in combined
    assert "slack_configs:" not in combined
    assert "email_configs:" not in combined
    assert "webhook_configs:" not in combined
