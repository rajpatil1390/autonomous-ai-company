"""Static rendering and contract tests for the Helm chart."""

from __future__ import annotations

import copy
import re
import tomllib
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
CHART_DIRECTORY = ROOT / "helm" / "autonomous-ai-company"
TEMPLATE_DIRECTORY = CHART_DIRECTORY / "templates"
EXPECTED_ROOT_FILES = {
    "Chart.yaml",
    "values.yaml",
    "values-dev.yaml",
    "values-staging.yaml",
    "values-prod.yaml",
}
EXPECTED_TEMPLATE_FILES = {
    "_helpers.tpl",
    "namespace.yaml",
    "deployment.yaml",
    "service.yaml",
    "ingress.yaml",
    "configmap.yaml",
    "secret.example.yaml",
    "persistentvolumeclaim.yaml",
    "networkpolicy.yaml",
    "hpa.yaml",
    "NOTES.txt",
}
INCLUDE_VALUES = {
    "autonomous-ai-company.name": "autonomous-ai-company",
    "autonomous-ai-company.fullname": "autonomous-ai-company-api",
    "autonomous-ai-company.configMapName": "autonomous-ai-company-config",
}
EXPRESSION_PATTERN = re.compile(r"{{-?\s*(.*?)\s*-?}}")
IF_PATTERN = re.compile(r"^{{-?\s*if\s+(.+?)\s*}}$")
END_PATTERN = re.compile(r"^{{-?\s*end\s*}}$")
VALUE_PATTERN = re.compile(r"\.Values(?:\.[A-Za-z0-9_]+)+")


def load_yaml(path: Path) -> dict[str, Any]:
    """Load one mapping from a chart YAML file."""

    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Model Helm's recursive values merge for static test rendering."""

    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def value_at(values: dict[str, Any], expression: str) -> Any:
    """Resolve a dotted .Values expression or fail on an absent value."""

    current: Any = values
    for key in expression.removeprefix(".Values.").split("."):
        current = current[key]
    return current


def scalar(value: Any, *, quoted: bool) -> str:
    """Render the scalar subset used by these templates."""

    if quoted:
        return f'"{str(value).lower() if isinstance(value, bool) else value}"'
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def render_expression(expression: str, values: dict[str, Any]) -> str:
    """Render the intentionally small Helm expression surface used by the chart."""

    include_match = re.fullmatch(r'include\s+"([^"]+)"\s+\.', expression)
    if include_match:
        return INCLUDE_VALUES[include_match.group(1)]

    parts = [part.strip() for part in expression.split("|")]
    assert parts[0].startswith(".Values.")
    assert len(parts) <= 2
    assert len(parts) == 1 or parts[1] == "quote"
    return scalar(value_at(values, parts[0]), quoted=len(parts) == 2)


def render_template(filename: str, values: dict[str, Any]) -> dict[str, Any] | None:
    """Statically render one YAML template without invoking Helm."""

    rendered_lines: list[str] = []
    active: list[bool] = [True]
    for line in (
        (TEMPLATE_DIRECTORY / filename).read_text(encoding="utf-8").splitlines()
    ):
        stripped = line.strip()
        if if_match := IF_PATTERN.fullmatch(stripped):
            condition = bool(value_at(values, if_match.group(1)))
            active.append(active[-1] and condition)
            continue
        if END_PATTERN.fullmatch(stripped):
            assert len(active) > 1
            active.pop()
            continue
        if active[-1]:
            rendered_lines.append(
                EXPRESSION_PATTERN.sub(
                    lambda match: render_expression(match.group(1), values), line
                )
            )

    assert active == [True]
    rendered = "\n".join(rendered_lines).strip()
    assert "{{" not in rendered
    if not rendered:
        return None
    document = yaml.safe_load(rendered)
    assert isinstance(document, dict)
    return document


def environment_values(filename: str | None = None) -> dict[str, Any]:
    """Return default values optionally merged with one environment override."""

    values = load_yaml(CHART_DIRECTORY / "values.yaml")
    if filename is not None:
        values = deep_merge(values, load_yaml(CHART_DIRECTORY / filename))
    return values


def render_environment(filename: str | None = None) -> dict[str, dict[str, Any]]:
    """Render every Kubernetes template for one values set, indexed by kind."""

    values = environment_values(filename)
    documents = [
        render_template(path.name, values) for path in TEMPLATE_DIRECTORY.glob("*.yaml")
    ]
    rendered = {document["kind"]: document for document in documents if document}
    assert len(rendered) == len([document for document in documents if document])
    return rendered


def test_chart_structure_and_metadata_match_the_project() -> None:
    """The chart should contain the requested files and project version."""

    assert {path.name for path in CHART_DIRECTORY.iterdir() if path.is_file()} == (
        EXPECTED_ROOT_FILES
    )
    assert {path.name for path in TEMPLATE_DIRECTORY.iterdir()} == (
        EXPECTED_TEMPLATE_FILES
    )
    chart = load_yaml(CHART_DIRECTORY / "Chart.yaml")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert chart == {
        "apiVersion": "v2",
        "name": "autonomous-ai-company",
        "description": (
            "Kubernetes deployment chart for the Autonomous AI Company API"
        ),
        "type": "application",
        "version": project["project"]["version"],
        "appVersion": project["project"]["version"],
    }


def test_helpers_and_template_control_structures_are_complete() -> None:
    """Helpers and condition blocks should be defined and balanced."""

    helpers = (TEMPLATE_DIRECTORY / "_helpers.tpl").read_text(encoding="utf-8")
    for helper in (
        *INCLUDE_VALUES,
        "autonomous-ai-company.selectorLabels",
        "autonomous-ai-company.labels",
    ):
        assert f'define "{helper}"' in helpers

    for path in TEMPLATE_DIRECTORY.glob("*.yaml"):
        content = path.read_text(encoding="utf-8")
        assert content.count("{{") == content.count("}}")
        assert len(IF_PATTERN.findall(content)) == len(END_PATTERN.findall(content))


def test_all_template_values_exist_in_the_default_values_file() -> None:
    """Every .Values reference must resolve before the chart is installed."""

    values = environment_values()
    chart_files = [*TEMPLATE_DIRECTORY.iterdir()]
    references = {
        match.group(0)
        for path in chart_files
        for match in VALUE_PATTERN.finditer(path.read_text(encoding="utf-8"))
    }
    assert references
    for reference in references:
        value_at(values, reference)


def test_default_render_preserves_required_kubernetes_resources() -> None:
    """Default rendering should preserve the existing manifest resource set."""

    rendered = render_environment()
    assert set(rendered) == {
        "Namespace",
        "Deployment",
        "Service",
        "Ingress",
        "ConfigMap",
        "PersistentVolumeClaim",
        "NetworkPolicy",
        "HorizontalPodAutoscaler",
    }
    assert {
        resource["metadata"].get("namespace") for resource in rendered.values()
    } == {
        None,
        "autonomous-ai-company",
    }


def test_default_render_is_equivalent_to_existing_manifests() -> None:
    """Templating must not redesign the established Kubernetes resources."""

    existing = {
        document["kind"]: document
        for path in (ROOT / "k8s").glob("*.yaml")
        if path.name != "secret.example.yaml"
        for document in [load_yaml(path)]
    }
    assert render_environment() == existing


def test_deployment_service_and_configmap_render_from_values() -> None:
    """Core workload parameters should flow into their existing contracts."""

    rendered = render_environment()
    deployment = rendered["Deployment"]
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert deployment["spec"]["replicas"] == 2
    assert container["image"] == "autonomous-ai-company-api:local"
    assert container["imagePullPolicy"] == "IfNotPresent"
    assert container["resources"] == {
        "requests": {"cpu": "500m", "memory": "512Mi"},
        "limits": {"cpu": "2", "memory": "2Gi"},
    }
    assert container["envFrom"] == [
        {"configMapRef": {"name": "autonomous-ai-company-config"}},
        {"secretRef": {"name": "autonomous-ai-company-secrets"}},
    ]
    service = rendered["Service"]
    assert service["spec"]["type"] == "ClusterIP"
    assert service["spec"]["ports"][0]["port"] == 8000
    assert rendered["ConfigMap"]["data"] == environment_values()["config"]


def test_ingress_storage_and_hpa_render_from_values() -> None:
    """Ingress, persistence, and scaling fields should remain configurable."""

    values = environment_values()
    values["ingress"].update(
        {
            "className": "custom-nginx",
            "host": "company.test",
            "tlsSecretName": "company-test-tls",
        }
    )
    values["persistence"].update({"storageClass": "fast", "size": "50Gi"})
    values["autoscaling"].update(
        {
            "minReplicas": 3,
            "maxReplicas": 12,
            "targetCPUUtilizationPercentage": 65,
            "targetMemoryUtilizationPercentage": 80,
        }
    )
    ingress = render_template("ingress.yaml", values)
    pvc = render_template("persistentvolumeclaim.yaml", values)
    hpa = render_template("hpa.yaml", values)
    assert ingress["spec"]["ingressClassName"] == "custom-nginx"
    assert ingress["spec"]["rules"][0]["host"] == "company.test"
    assert ingress["spec"]["tls"][0]["secretName"] == "company-test-tls"
    assert pvc["spec"]["storageClassName"] == "fast"
    assert pvc["spec"]["resources"]["requests"]["storage"] == "50Gi"
    assert (hpa["spec"]["minReplicas"], hpa["spec"]["maxReplicas"]) == (3, 12)
    targets = {
        metric["resource"]["name"]: metric["resource"]["target"]["averageUtilization"]
        for metric in hpa["spec"]["metrics"]
    }
    assert targets == {"cpu": 65, "memory": 80}


def test_environment_overrides_define_expected_capacity() -> None:
    """Development, staging, and production should express distinct capacity."""

    dev = render_environment("values-dev.yaml")
    staging = render_environment("values-staging.yaml")
    production = render_environment("values-prod.yaml")
    assert dev["Deployment"]["spec"]["replicas"] == 1
    assert "HorizontalPodAutoscaler" not in dev
    assert dev["Deployment"]["spec"]["template"]["spec"]["containers"][0]["resources"][
        "requests"
    ] == {"cpu": "100m", "memory": "128Mi"}
    assert staging["Deployment"]["spec"]["replicas"] == 2
    assert "HorizontalPodAutoscaler" not in staging
    assert staging["Ingress"]["spec"]["rules"][0]["host"].startswith("staging.")
    assert production["Deployment"]["spec"]["replicas"] == 2
    assert (
        production["Deployment"]["spec"]["template"]["spec"]["containers"][0]["image"]
        == "autonomous-ai-company-api:0.1.0"
    )
    assert production["HorizontalPodAutoscaler"]["spec"]["maxReplicas"] == 10


def test_optional_templates_and_example_secret_are_safe() -> None:
    """Optional resources should omit cleanly and the example Secret stay opt-in."""

    values = environment_values()
    assert render_template("secret.example.yaml", values) is None
    values["namespace"]["create"] = False
    values["ingress"]["enabled"] = False
    values["persistence"]["enabled"] = False
    values["networkPolicy"]["enabled"] = False
    values["autoscaling"]["enabled"] = False
    assert render_template("namespace.yaml", values) is None
    assert render_template("ingress.yaml", values) is None
    assert render_template("persistentvolumeclaim.yaml", values) is None
    assert render_template("networkpolicy.yaml", values) is None
    assert render_template("hpa.yaml", values) is None

    values["secret"]["createExample"] = True
    secret = render_template("secret.example.yaml", values)
    assert secret["metadata"]["name"] == "autonomous-ai-company-secrets"
    assert all(
        value.startswith("REPLACE_WITH_") for value in secret["stringData"].values()
    )


def test_notes_include_operational_commands_and_parameterized_endpoints() -> None:
    """Release notes should provide install, upgrade, access, and Secret guidance."""

    notes = (TEMPLATE_DIRECTORY / "NOTES.txt").read_text(encoding="utf-8")
    assert "helm install {{ .Release.Name }}" in notes
    assert "helm upgrade {{ .Release.Name }}" in notes
    assert "kubectl --namespace {{ .Values.namespace.name }} port-forward" in notes
    assert "https://{{ .Values.ingress.host }}" in notes
    assert "secret.createExample=true" in notes
