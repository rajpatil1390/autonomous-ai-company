"""Static safety and completeness tests for chaos-engineering assets."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
CHAOS_DIRECTORY = ROOT / "chaos"
LITMUS_DIRECTORY = CHAOS_DIRECTORY / "litmus"
SCENARIO_DIRECTORY = CHAOS_DIRECTORY / "scenarios"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "chaos.yml"
GUIDE_PATH = ROOT / "docs" / "chaos-engineering.md"
MANIFESTS = {
    name: LITMUS_DIRECTORY / f"{name}.yaml"
    for name in (
        "pod-delete",
        "network-delay",
        "cpu-hog",
        "memory-hog",
        "database-loss",
    )
}
SCENARIOS = {
    name: SCENARIO_DIRECTORY / f"{name}.md"
    for name in ("workflow", "rollback", "recovery", "disaster")
}
EXPECTED_EXPERIMENTS = {
    "pod-delete": "pod-delete",
    "network-delay": "pod-network-latency",
    "cpu-hog": "pod-cpu-hog",
    "memory-hog": "pod-memory-hog",
    "database-loss": "pod-network-loss",
}


def load_yaml(path: Path) -> dict[str, Any]:
    """Load one YAML mapping using safe construction."""

    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def load_workflow() -> dict[str, Any]:
    """Load GitHub YAML without coercing the `on` key to a boolean."""

    document = yaml.load(
        WORKFLOW_PATH.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert isinstance(document, dict)
    return document


def experiment_environment(document: dict[str, Any]) -> dict[str, str]:
    """Return one ChaosEngine experiment's environment as a unique mapping."""

    experiments = document["spec"]["experiments"]
    assert len(experiments) == 1
    items = experiments[0]["spec"]["components"]["env"]
    environment = {item["name"]: item["value"] for item in items}
    assert len(environment) == len(items)
    return environment


def workflow_steps(job_name: str) -> list[dict[str, Any]]:
    """Return one workflow job's ordered step mappings."""

    steps = load_workflow()["jobs"][job_name]["steps"]
    assert all(isinstance(step, dict) for step in steps)
    return steps


def step_named(job_name: str, name: str) -> dict[str, Any]:
    """Return one uniquely named workflow step."""

    matches = [step for step in workflow_steps(job_name) if step.get("name") == name]
    assert len(matches) == 1
    return matches[0]


def test_all_requested_chaos_assets_exist_and_are_nonempty() -> None:
    """Every requested definition, scenario, guide, workflow, and test must exist."""

    paths = [*MANIFESTS.values(), *SCENARIOS.values(), WORKFLOW_PATH, GUIDE_PATH]
    assert all(path.is_file() for path in paths)
    assert all(path.stat().st_size > 0 for path in paths)


def test_manifests_are_valid_namespaced_chaos_engines() -> None:
    """All definitions should use the expected Litmus API and namespace."""

    engine_names: set[str] = set()
    for path in MANIFESTS.values():
        document = load_yaml(path)
        assert document["apiVersion"] == "litmuschaos.io/v1alpha1"
        assert document["kind"] == "ChaosEngine"
        metadata = document["metadata"]
        assert metadata["namespace"] == "autonomous-ai-company"
        assert metadata["labels"]["app.kubernetes.io/name"] == ("autonomous-ai-company")
        assert metadata["labels"]["app.kubernetes.io/component"] == "chaos"
        engine_names.add(metadata["name"])
    assert len(engine_names) == len(MANIFESTS)


def test_every_manifest_is_stopped_annotation_gated_and_retained() -> None:
    """Applying a definition must never inject chaos without explicit opt-in."""

    for path in MANIFESTS.values():
        document = load_yaml(path)
        spec = document["spec"]
        assert spec["engineState"] == "stop"
        assert spec["annotationCheck"] == "true"
        assert spec["jobCleanUpPolicy"] == "retain"
        assert spec["chaosServiceAccount"] == "litmus-chaos-runner"
        assert (
            document["metadata"]["annotations"][
                "chaos.autonomous-ai-company.io/safety-state"
            ]
            == "stopped"
        )


def test_target_selectors_match_only_the_existing_api_deployment() -> None:
    """Pod-level faults must not select unrelated components or namespaces."""

    expected_selector = (
        "app.kubernetes.io/name=autonomous-ai-company,app.kubernetes.io/component=api"
    )
    for path in MANIFESTS.values():
        appinfo = load_yaml(path)["spec"]["appinfo"]
        assert appinfo == {
            "appns": "autonomous-ai-company",
            "applabel": expected_selector,
            "appkind": "deployment",
        }


def test_experiment_names_and_common_blast_radius_are_exact() -> None:
    """Each file should select one intended experiment and one of two API pods."""

    names: set[str] = set()
    for asset_name, expected_name in EXPECTED_EXPERIMENTS.items():
        document = load_yaml(MANIFESTS[asset_name])
        experiments = document["spec"]["experiments"]
        assert len(experiments) == 1
        assert experiments[0]["name"] == expected_name
        names.add(experiments[0]["name"])
        environment = experiment_environment(document)
        assert environment["TARGET_CONTAINER"] == "api"
        assert environment["PODS_AFFECTED_PERC"] == "50"
        assert environment["SEQUENCE"] == "serial"
        assert 0 < int(environment["TOTAL_CHAOS_DURATION"]) <= 60
    assert len(names) == len(MANIFESTS)


def test_pod_delete_is_single_graceful_failure() -> None:
    """The API failure definition must never force-delete every replica."""

    environment = experiment_environment(load_yaml(MANIFESTS["pod-delete"]))
    assert environment["FORCE"] == "false"
    assert environment["TOTAL_CHAOS_DURATION"] == "30"
    assert environment["CHAOS_INTERVAL"] == "30"


def test_cpu_and_memory_pressure_respect_existing_resource_limits() -> None:
    """Resource faults should be bounded to one pod and a short observation window."""

    cpu = experiment_environment(load_yaml(MANIFESTS["cpu-hog"]))
    memory = experiment_environment(load_yaml(MANIFESTS["memory-hog"]))
    assert cpu["CPU_CORES"] == "2"
    assert cpu["TOTAL_CHAOS_DURATION"] == "60"
    assert memory["MEMORY_CONSUMPTION"] == "1800"
    assert memory["NUMBER_OF_WORKERS"] == "1"
    assert memory["TOTAL_CHAOS_DURATION"] == "60"


def test_network_faults_are_scoped_only_to_postgresql() -> None:
    """Latency and loss must not impair arbitrary destinations or ports."""

    expected_host = "postgresql.autonomous-ai-company.svc.cluster.local"
    delay = experiment_environment(load_yaml(MANIFESTS["network-delay"]))
    loss = experiment_environment(load_yaml(MANIFESTS["database-loss"]))
    for environment in (delay, loss):
        assert environment["DESTINATION_HOSTS"] == expected_host
        assert environment["DESTINATION_PORTS"] == "5432"
        assert environment["NETWORK_INTERFACE"] == "eth0"
        assert "DESTINATION_IPS" not in environment
    assert delay["NETWORK_LATENCY"] == "500"
    assert delay["JITTER"] == "100"
    assert loss["NETWORK_PACKET_LOSS_PERCENTAGE"] == "100"
    assert loss["TOTAL_CHAOS_DURATION"] == "45"


def test_manifests_contain_no_destructive_active_defaults() -> None:
    """Definitions should require deliberate activation and preserve the database."""

    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in MANIFESTS.values()
    )
    assert not re.search(r"engineState:\s*active", combined)
    assert not re.search(r"annotationCheck:\s*[\"']?false", combined)
    assert not re.search(r"name:\s*FORCE\s*\n\s*value:\s*[\"']?true", combined)
    assert "kubectl" not in combined
    assert "password" not in combined.lower()
    assert "secret" not in combined.lower()


def test_scenarios_document_expected_results_failures_and_recovery() -> None:
    """Every game-day phase should define evidence and safe stopping conditions."""

    workflow = SCENARIOS["workflow"].read_text(encoding="utf-8")
    rollback = SCENARIOS["rollback"].read_text(encoding="utf-8")
    recovery = SCENARIOS["recovery"].read_text(encoding="utf-8")
    disaster = SCENARIOS["disaster"].read_text(encoding="utf-8")
    for heading in (
        "Preconditions",
        "Steady-state checks",
        "Opt-in execution procedure",
        "Expected results",
        "Failure criteria",
        "Evidence",
    ):
        assert f"## {heading}" in workflow
    assert "## Immediate stop" in rollback
    assert "## Experiment-specific rollback" in rollback
    assert "## Rollback failure criteria" in rollback
    assert "## Kubernetes recovery" in recovery
    assert "## Data and audit recovery" in recovery
    assert "## Success criteria" in recovery
    assert "## Authorization boundary" in disaster
    assert "never deletes the database" in disaster
    assert "Do not combine database loss" in disaster


def test_rollback_commands_are_parameterized_and_fail_safe() -> None:
    """Runbook commands should stop injection without broad hardcoded targets."""

    rollback = SCENARIOS["rollback"].read_text(encoding="utf-8")
    assert '"${CHAOS_NAMESPACE}"' in rollback
    assert '"${CHAOS_ENGINE}"' in rollback
    assert '"${TARGET_POD}"' in rollback
    assert '"engineState":"stop"' in rollback
    assert "litmuschaos.io/chaos-" in rollback
    assert "--all" not in rollback
    assert "delete namespace" not in rollback


def test_main_guide_covers_complete_safe_operating_contract() -> None:
    """The operator guide should connect approval, execution, and learning."""

    guide = GUIDE_PATH.read_text(encoding="utf-8")
    for heading in (
        "Prerequisites",
        "Experiment catalog",
        "Opt-in execution",
        "Expected results and failure criteria",
        "Rollback",
        "Recovery validation",
        "Observability",
        "Relationship to load testing",
        "Improving Kubernetes configuration",
    ):
        assert f"## {heading}" in guide
    assert "spec.engineState` is `stop`" in guide
    assert "annotationCheck" in guide
    assert "Never activate from GitHub Actions" in guide
    assert "Prometheus" in guide
    assert "Grafana" in guide
    assert "HPA" in guide
    assert "PodDisruptionBudget" in guide


def test_workflow_is_manual_static_validation_only() -> None:
    """GitHub Actions must never connect to a cluster or inject a fault."""

    workflow = load_workflow()
    assert workflow["on"] == {"workflow_dispatch": ""}
    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    assert list(jobs) == [
        "validate-manifests",
        "validate-scenarios",
        "upload-artifacts",
    ]
    assert "needs" not in jobs["validate-manifests"]
    assert jobs["validate-scenarios"]["needs"] == "validate-manifests"
    assert jobs["upload-artifacts"]["needs"] == [
        "validate-manifests",
        "validate-scenarios",
    ]
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "kubectl",
        "litmusctl",
        "helm ",
        "engineState: active",
        "KUBECONFIG",
        "AWS_ACCESS_KEY_ID",
        "secrets.",
    ):
        assert forbidden not in text


def test_workflow_validates_safety_and_uploads_all_assets() -> None:
    """The manual workflow should enforce stopped defaults and archive definitions."""

    manifest_validation = step_named(
        "validate-manifests", "Validate manifest safety contracts"
    )["run"]
    assert 'spec["engineState"] == "stop"' in manifest_validation
    assert 'spec["annotationCheck"] == "true"' in manifest_validation
    assert 'env["PODS_AFFECTED_PERC"] == "50"' in manifest_validation
    assert "len(records) == 5" in manifest_validation

    scenario_validation = step_named(
        "validate-scenarios", "Validate scenario contracts"
    )["run"]
    for name in ("workflow.md", "rollback.md", "recovery.md", "disaster.md"):
        assert name in scenario_validation

    upload = step_named("upload-artifacts", "Upload chaos definitions and runbooks")
    paths = upload["with"]["path"]
    assert "chaos/litmus/*.yaml" in paths
    assert "chaos/scenarios/*.md" in paths
    assert "docs/chaos-engineering.md" in paths
    assert upload["with"]["if-no-files-found"] == "error"
