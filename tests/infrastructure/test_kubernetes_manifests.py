"""Static contract tests for the Kubernetes deployment manifests."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
K8S_DIRECTORY = ROOT / "k8s"
NAMESPACE = "autonomous-ai-company"
EXPECTED_FILES = {
    "configmap.yaml",
    "deployment.yaml",
    "hpa.yaml",
    "ingress.yaml",
    "namespace.yaml",
    "networkpolicy.yaml",
    "persistentvolumeclaim.yaml",
    "secret.example.yaml",
    "service.yaml",
}


def load_manifest(filename: str) -> dict[str, object]:
    """Parse one manifest as a single Kubernetes resource."""

    document = yaml.safe_load((K8S_DIRECTORY / filename).read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    assert {"apiVersion", "kind", "metadata"} <= document.keys()
    return document


def container_from(deployment: dict[str, object]) -> dict[str, object]:
    """Return the Deployment's single application container."""

    containers = deployment["spec"]["template"]["spec"]["containers"]
    assert len(containers) == 1
    return containers[0]


def test_manifest_set_yaml_syntax_resources_and_namespace_consistency() -> None:
    """The directory should contain exactly one valid resource of every kind."""

    assert {path.name for path in K8S_DIRECTORY.glob("*.yaml")} == EXPECTED_FILES
    manifests = {filename: load_manifest(filename) for filename in EXPECTED_FILES}
    expected_kinds = {
        "namespace.yaml": "Namespace",
        "deployment.yaml": "Deployment",
        "service.yaml": "Service",
        "ingress.yaml": "Ingress",
        "configmap.yaml": "ConfigMap",
        "secret.example.yaml": "Secret",
        "persistentvolumeclaim.yaml": "PersistentVolumeClaim",
        "networkpolicy.yaml": "NetworkPolicy",
        "hpa.yaml": "HorizontalPodAutoscaler",
    }
    assert {
        filename: manifest["kind"] for filename, manifest in manifests.items()
    } == expected_kinds

    namespace = manifests["namespace.yaml"]
    assert namespace["metadata"]["name"] == NAMESPACE
    assert "namespace" not in namespace["metadata"]
    for filename, manifest in manifests.items():
        if filename != "namespace.yaml":
            assert manifest["metadata"]["namespace"] == NAMESPACE


def test_deployment_strategy_image_resources_and_selectors() -> None:
    """Deployment capacity and rolling updates should preserve availability."""

    deployment = load_manifest("deployment.yaml")
    assert deployment["apiVersion"] == "apps/v1"
    spec = deployment["spec"]
    assert spec["replicas"] == 2
    assert spec["strategy"] == {
        "type": "RollingUpdate",
        "rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1},
    }
    assert spec["selector"]["matchLabels"] == spec["template"]["metadata"]["labels"]

    container = container_from(deployment)
    assert container["image"] == "autonomous-ai-company-api:local"
    assert container["imagePullPolicy"] == "IfNotPresent"
    assert container["ports"] == [
        {"name": "http", "containerPort": 8000, "protocol": "TCP"}
    ]
    assert container["resources"] == {
        "requests": {"cpu": "500m", "memory": "512Mi"},
        "limits": {"cpu": "2", "memory": "2Gi"},
    }


def test_all_health_probes_use_the_existing_health_endpoint() -> None:
    """Startup, readiness, and liveness should independently gate pod health."""

    container = container_from(load_manifest("deployment.yaml"))
    probes = {
        name: container[name]
        for name in ("startupProbe", "readinessProbe", "livenessProbe")
    }
    for probe in probes.values():
        assert probe["httpGet"] == {
            "path": "/health",
            "port": "http",
            "scheme": "HTTP",
        }
        assert probe["timeoutSeconds"] == 3
        assert probe["failureThreshold"] >= 3
    assert probes["startupProbe"]["failureThreshold"] == 12
    assert probes["readinessProbe"]["successThreshold"] == 1


def test_pod_and_container_security_context_are_restricted() -> None:
    """The pod must match the non-root, least-privilege container image contract."""

    deployment = load_manifest("deployment.yaml")
    pod_spec = deployment["spec"]["template"]["spec"]
    assert pod_spec["automountServiceAccountToken"] is False
    assert pod_spec["securityContext"] == {
        "runAsNonRoot": True,
        "runAsUser": 10001,
        "runAsGroup": 10001,
        "fsGroup": 10001,
        "seccompProfile": {"type": "RuntimeDefault"},
    }

    container = container_from(deployment)
    assert container["securityContext"] == {
        "runAsNonRoot": True,
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]},
    }
    assert container["volumeMounts"] == [
        {"name": "temporary-files", "mountPath": "/tmp"}
    ]
    assert pod_spec["volumes"] == [
        {"name": "temporary-files", "emptyDir": {"sizeLimit": "64Mi"}}
    ]
    assert all("hostPath" not in volume for volume in pod_spec["volumes"])
    assert all("persistentVolumeClaim" not in volume for volume in pod_spec["volumes"])


def test_configuration_and_secret_references_are_separated() -> None:
    """Non-secret settings and secret material must cross distinct boundaries."""

    deployment = load_manifest("deployment.yaml")
    container = container_from(deployment)
    assert container["envFrom"] == [
        {"configMapRef": {"name": "autonomous-ai-company-config"}},
        {"secretRef": {"name": "autonomous-ai-company-secrets"}},
    ]

    config = load_manifest("configmap.yaml")["data"]
    assert config["APP_PORT"] == "8000"
    assert config["METRICS_ENABLED"] == "true"
    assert config["POSTGRES_ENABLED"] == "false"
    assert not any(
        fragment in key
        for key in config
        for fragment in ("API_KEY", "SECRET", "PASSWORD", "TRACKING_URI", "ENDPOINT")
    )

    secret = load_manifest("secret.example.yaml")
    assert secret["type"] == "Opaque"
    assert set(secret["stringData"]) == {
        "ANTHROPIC_API_KEY",
        "JWT_SECRET_KEY",
        "POSTGRES_PASSWORD",
    }
    assert all(
        value.startswith("REPLACE_WITH_") for value in secret["stringData"].values()
    )
    assert secret["metadata"]["annotations"] == {
        "autonomous-ai-company.example/secret-template": "replace-before-apply"
    }


def test_service_selector_and_port_match_the_deployment() -> None:
    """The internal service must select the API pods and their named HTTP port."""

    deployment = load_manifest("deployment.yaml")
    service = load_manifest("service.yaml")
    assert service["apiVersion"] == "v1"
    assert service["spec"]["type"] == "ClusterIP"
    assert service["spec"]["selector"] == deployment["spec"]["selector"]["matchLabels"]
    assert service["spec"]["ports"] == [
        {
            "name": "http",
            "port": 8000,
            "targetPort": "http",
            "protocol": "TCP",
        }
    ]


def test_ingress_is_nginx_tls_ready_and_targets_the_service() -> None:
    """Ingress should route TLS-ready HTTP traffic to the ClusterIP service."""

    ingress = load_manifest("ingress.yaml")
    assert ingress["apiVersion"] == "networking.k8s.io/v1"
    assert ingress["spec"]["ingressClassName"] == "nginx"
    assert (
        ingress["metadata"]["annotations"]["nginx.ingress.kubernetes.io/ssl-redirect"]
        == "true"
    )
    assert ingress["spec"]["tls"] == [
        {
            "hosts": ["autonomous-ai-company.example.com"],
            "secretName": "autonomous-ai-company-tls",
        }
    ]
    path = ingress["spec"]["rules"][0]["http"]["paths"][0]
    assert path["path"] == "/"
    assert path["pathType"] == "Prefix"
    assert path["backend"] == {
        "service": {
            "name": "autonomous-ai-company-api",
            "port": {"number": 8000},
        }
    }
    assert not (K8S_DIRECTORY / "autonomous-ai-company-tls.yaml").exists()


def test_hpa_targets_cpu_memory_and_the_api_deployment() -> None:
    """Autoscaling should stay within 2-10 pods using both resource pressures."""

    hpa = load_manifest("hpa.yaml")
    assert hpa["apiVersion"] == "autoscaling/v2"
    assert hpa["spec"]["scaleTargetRef"] == {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "name": "autonomous-ai-company-api",
    }
    assert hpa["spec"]["minReplicas"] == 2
    assert hpa["spec"]["maxReplicas"] == 10
    targets = {
        metric["resource"]["name"]: metric["resource"]["target"]
        for metric in hpa["spec"]["metrics"]
    }
    assert targets == {
        "cpu": {"type": "Utilization", "averageUtilization": 70},
        "memory": {"type": "Utilization", "averageUtilization": 75},
    }
    assert hpa["spec"]["behavior"]["scaleDown"]["stabilizationWindowSeconds"] == 300


def test_network_policy_defaults_to_deny_with_explicit_required_flows() -> None:
    """Only named ingress peers and required DNS, database, and TLS egress pass."""

    policy = load_manifest("networkpolicy.yaml")
    assert policy["apiVersion"] == "networking.k8s.io/v1"
    spec = policy["spec"]
    assert spec["policyTypes"] == ["Ingress", "Egress"]
    assert spec["podSelector"]["matchLabels"] == {
        "app.kubernetes.io/name": "autonomous-ai-company",
        "app.kubernetes.io/component": "api",
    }
    assert len(spec["ingress"]) == 1
    ingress = spec["ingress"][0]
    assert ingress["ports"] == [{"protocol": "TCP", "port": 8000}]
    ingress_names = {
        source.get("podSelector", {})
        .get("matchLabels", {})
        .get("app.kubernetes.io/name")
        for source in ingress["from"]
    }
    assert ingress_names == {"ingress-nginx", "prometheus", "grafana", "postgresql"}

    assert len(spec["egress"]) == 3
    egress_ports = {
        (port["protocol"], port["port"])
        for rule in spec["egress"]
        for port in rule["ports"]
    }
    assert egress_ports == {("UDP", 53), ("TCP", 53), ("TCP", 5432), ("TCP", 443)}
    external = spec["egress"][2]["to"][0]["ipBlock"]
    assert external["cidr"] == "0.0.0.0/0"
    assert set(external["except"]) == {
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
    }


def test_pvc_is_reserved_for_postgresql_audit_storage() -> None:
    """Database persistence should remain separate from the stateless API pod."""

    pvc = load_manifest("persistentvolumeclaim.yaml")
    assert pvc["apiVersion"] == "v1"
    assert pvc["metadata"]["name"] == "postgres-audit-data"
    assert pvc["metadata"]["labels"] == {
        "app.kubernetes.io/name": "postgresql",
        "app.kubernetes.io/component": "audit-storage",
        "app.kubernetes.io/part-of": "autonomous-ai-company",
    }
    assert pvc["metadata"]["annotations"] == {
        "autonomous-ai-company.example/purpose": "PostgreSQL append-only audit storage"
    }
    assert pvc["spec"] == {
        "accessModes": ["ReadWriteOnce"],
        "resources": {"requests": {"storage": "20Gi"}},
        "volumeMode": "Filesystem",
    }
