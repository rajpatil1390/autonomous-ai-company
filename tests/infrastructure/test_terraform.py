"""Static contract tests for the production AWS Terraform assets."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TERRAFORM_DIRECTORY = ROOT / "cloud" / "terraform"
AWS_DIRECTORY = ROOT / "cloud" / "aws"
EXPECTED_TERRAFORM_FILES = {
    "providers.tf",
    "variables.tf",
    "outputs.tf",
    "versions.tf",
    "main.tf",
    "networking.tf",
    "eks.tf",
    "rds.tf",
    "ecr.tf",
    "iam.tf",
    "monitoring.tf",
    "secrets.tf",
    "locals.tf",
    "terraform.tfvars.example",
}
EXPECTED_AWS_FILES = {
    "README-aws.md",
    "ecr.md",
    "eks.md",
    "rds.md",
    "secrets-manager.md",
    "iam.md",
    "architecture.drawio",
}


def terraform_text(*filenames: str) -> str:
    """Read selected Terraform files or the complete configuration."""

    paths = (
        [TERRAFORM_DIRECTORY / filename for filename in filenames]
        if filenames
        else sorted(TERRAFORM_DIRECTORY.glob("*.tf"))
    )
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def labels(block_type: str, text: str) -> set[str]:
    """Return first labels from Terraform blocks of the requested type."""

    return set(re.findall(rf'\b{block_type}\s+"([^"]+)"', text))


def resource_names(resource_type: str, text: str) -> set[str]:
    """Return local names for resources of one provider type."""

    return set(
        re.findall(rf'\bresource\s+"{re.escape(resource_type)}"\s+"([^"]+)"', text)
    )


def assert_hcl_delimiters_are_balanced(text: str) -> None:
    """Validate braces/brackets/parentheses while ignoring strings and comments."""

    pairs = {"}": "{", "]": "[", ")": "("}
    stack: list[str] = []
    index = 0
    in_string = False
    in_line_comment = False
    in_block_comment = False
    escaped = False
    while index < len(text):
        character = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if in_line_comment:
            if character == "\n":
                in_line_comment = False
        elif in_block_comment:
            if character == "*" and following == "/":
                in_block_comment = False
                index += 1
        elif in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character == "#" or (character == "/" and following == "/"):
            in_line_comment = True
            if character == "/":
                index += 1
        elif character == "/" and following == "*":
            in_block_comment = True
            index += 1
        elif character in "{[(":
            stack.append(character)
        elif character in "}])":
            assert stack and stack.pop() == pairs[character]
        index += 1
    assert not in_string
    assert not in_block_comment
    assert not stack


def test_required_cloud_asset_structure() -> None:
    """Only the requested AWS and Terraform assets should define this layer."""

    assert {path.name for path in TERRAFORM_DIRECTORY.iterdir()} == (
        EXPECTED_TERRAFORM_FILES
    )
    assert {path.name for path in AWS_DIRECTORY.iterdir()} == EXPECTED_AWS_FILES
    assert all(path.stat().st_size > 0 for path in TERRAFORM_DIRECTORY.iterdir())
    assert all(path.stat().st_size > 0 for path in AWS_DIRECTORY.iterdir())


def test_terraform_files_have_static_hcl_syntax_integrity() -> None:
    """Every HCL file should have closed strings, comments, and delimiters."""

    for path in [
        *TERRAFORM_DIRECTORY.glob("*.tf"),
        TERRAFORM_DIRECTORY / "terraform.tfvars.example",
    ]:
        assert_hcl_delimiters_are_balanced(path.read_text(encoding="utf-8"))

    versions = terraform_text("versions.tf")
    assert 'required_version = ">= 1.10, < 2.0"' in versions
    assert 'source  = "hashicorp/aws"' in versions
    assert 'source  = "hashicorp/tls"' in versions
    assert 'backend "s3" {}' in versions


def test_required_variables_outputs_and_global_tags() -> None:
    """Inputs, deployment outputs, and uniform ownership tags must be explicit."""

    variable_names = labels("variable", terraform_text("variables.tf"))
    assert {
        "aws_region",
        "project_name",
        "environment",
        "vpc_cidr",
        "availability_zone_count",
        "eks_version",
        "node_instance_types",
        "rds_instance_class",
        "github_organization",
        "github_repository",
        "terraform_operator_principal_arns",
        "otlp_endpoint",
    } <= variable_names

    assert labels("output", terraform_text("outputs.tf")) == {
        "cluster_name",
        "region",
        "ecr_repository_url",
        "rds_endpoint",
        "secret_arns",
        "prometheus_workspace_endpoint",
        "grafana_workspace_endpoint",
        "otlp_endpoint",
    }
    providers = terraform_text("providers.tf")
    locals = terraform_text("locals.tf")
    assert "default_tags" in providers
    assert all(tag in locals for tag in ("Project", "Environment", "ManagedBy"))


def test_all_terraform_references_are_declared() -> None:
    """Static references should not point to missing variables or AWS objects."""

    text = terraform_text()
    declared_variables = labels("variable", terraform_text("variables.tf"))
    referenced_variables = set(re.findall(r"\bvar\.([A-Za-z0-9_]+)", text))
    assert referenced_variables <= declared_variables

    declared_objects = set(
        re.findall(
            r'\b(?:resource|data)\s+"(aws_[^"]+)"\s+"([^"]+)"',
            text,
        )
    )
    referenced_objects = set(
        re.findall(r"(?<![\w\"])(aws_[A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\b", text)
    )
    assert referenced_objects <= declared_objects


def test_networking_is_multi_zone_and_separates_public_private_subnets() -> None:
    """The VPC should provide resilient public egress and private workloads."""

    text = terraform_text("networking.tf")
    assert resource_names("aws_vpc", text) == {"main"}
    assert resource_names("aws_internet_gateway", text) == {"main"}
    assert resource_names("aws_nat_gateway", text) == {"main"}
    assert resource_names("aws_subnet", text) == {"public", "private"}
    assert resource_names("aws_route_table", text) == {"public", "private"}
    assert "map_public_ip_on_launch = true" in text
    assert "map_public_ip_on_launch = false" in text
    assert 'cidr_block = "0.0.0.0/0"' in text
    assert resource_names("aws_vpc_endpoint", text) == {"secretsmanager"}
    assert "com.amazonaws.${var.aws_region}.secretsmanager" in text


def test_eks_managed_cluster_oidc_nodes_and_autoscaling_contracts() -> None:
    """EKS must be private, encrypted, managed, observable, and autoscaler-ready."""

    eks = terraform_text("eks.tf")
    iam = terraform_text("iam.tf")
    assert resource_names("aws_eks_cluster", eks) == {"main"}
    assert resource_names("aws_eks_node_group", eks) == {"main"}
    assert resource_names("aws_iam_openid_connect_provider", eks) == {"eks"}
    assert "endpoint_private_access = true" in eks
    assert "endpoint_public_access  = false" in eks
    assert 'resources = ["secrets"]' in eks
    assert "enabled_cluster_log_types" in eks
    assert '"k8s.io/cluster-autoscaler/enabled"' in eks
    assert "ignore_changes = [scaling_config[0].desired_size]" in eks
    assert resource_names("aws_iam_role", iam) >= {
        "eks_cluster",
        "eks_nodes",
        "cluster_autoscaler",
    }
    assert "autoscaling:SetDesiredCapacity" in iam
    assert "system:serviceaccount:kube-system:cluster-autoscaler" in iam


def test_rds_is_private_encrypted_backed_up_and_deletion_protected() -> None:
    """The audit database must preserve confidentiality and recoverability."""

    text = terraform_text("rds.tf")
    assert resource_names("aws_db_instance", text) == {"audit"}
    assert resource_names("aws_db_subnet_group", text) == {"audit"}
    assert "[for subnet in aws_subnet.private : subnet.id]" in text
    assert "publicly_accessible    = false" in text
    assert "storage_encrypted     = true" in text
    assert "multi_az               = true" in text
    assert "backup_retention_period = var.rds_backup_retention_days" in text
    assert "deletion_protection       = true" in text
    assert "skip_final_snapshot       = false" in text
    assert "manage_master_user_password   = true" in text
    assert "enabled_cloudwatch_logs_exports" in text


def test_ecr_scans_encrypts_and_expires_images() -> None:
    """The registry must prevent tag replacement and limit retained images."""

    text = terraform_text("ecr.tf")
    assert resource_names("aws_ecr_repository", text) == {"application"}
    assert resource_names("aws_ecr_lifecycle_policy", text) == {"application"}
    assert 'image_tag_mutability = "IMMUTABLE"' in text
    assert "scan_on_push = true" in text
    assert 'encryption_type = "AES256"' in text
    assert "sinceImagePushed" in text
    assert "imageCountMoreThan" in text


def test_secrets_are_metadata_only_and_no_secret_values_are_hardcoded() -> None:
    """Terraform may manage secret identities but must never receive payloads."""

    secrets = terraform_text("secrets.tf")
    all_terraform = terraform_text()
    tfvars = (TERRAFORM_DIRECTORY / "terraform.tfvars.example").read_text(
        encoding="utf-8"
    )
    assert resource_names("aws_secretsmanager_secret", secrets) == {
        "anthropic_api_key",
        "jwt_secret_key",
    }
    assert "aws_secretsmanager_secret_version" not in all_terraform
    assert "manage_master_user_password   = true" in all_terraform
    assert not re.search(r"(?im)^\s*(password|api_key|jwt_secret)\s*=", all_terraform)
    assert "REPLACE_WITH_" in tfvars
    assert not any(
        forbidden in tfvars.lower()
        for forbidden in ("sk-ant-", "-----begin private key-----", "eyjhb")
    )


def test_iam_roles_are_separated_and_federated_without_static_keys() -> None:
    """Runtime, deployment, cluster, and provisioning trust must stay separate."""

    text = terraform_text("iam.tf")
    roles = resource_names("aws_iam_role", text)
    assert {
        "eks_cluster",
        "eks_nodes",
        "application",
        "cluster_autoscaler",
        "cicd",
        "terraform",
    } <= roles
    assert resource_names("aws_iam_openid_connect_provider", text) == {"github"}
    assert "token.actions.githubusercontent.com:sub" in text
    assert "repo:${var.github_organization}/${var.github_repository}" in text
    assert "system:serviceaccount:${var.kubernetes_namespace}" in text
    assert "AdministratorAccess" not in text
    assert all(
        service_wildcard not in text
        for service_wildcard in ('"iam:*"', '"kms:*"', '"eks:*"', '"ecr:*"')
    )
    assert not resource_names("aws_iam_access_key", text)


def test_monitoring_provisions_prometheus_grafana_and_otlp_placeholder() -> None:
    """Managed metrics and dashboards should exist without inventing an OTLP service."""

    text = terraform_text("monitoring.tf")
    assert resource_names("aws_prometheus_workspace", text) == {"main"}
    assert resource_names("aws_grafana_workspace", text) == {"main"}
    assert 'data_sources             = ["PROMETHEUS"]' in text
    assert "aws_prometheus_workspace.main.arn" in text
    assert resource_names("aws_cloudwatch_log_group", text) == {"otel_collector"}
    assert "OTLPPlaceholder = var.otlp_endpoint" in text


def test_documentation_and_architecture_cover_the_operational_lifecycle() -> None:
    """Operators need deployment, recovery, cost, IAM, and secret guidance."""

    readme = (AWS_DIRECTORY / "README-aws.md").read_text(encoding="utf-8")
    for section in (
        "## Architecture",
        "## Deployment flow",
        "## CI/CD integration",
        "## Helm deployment",
        "## Secrets Manager integration",
        "## Disaster recovery",
        "## Cost optimization",
    ):
        assert section in readme
    assert "terraform apply" in readme
    assert "explicit operator action" in readme
    assert "GitHub Actions uses OIDC" in readme
    assert "helm upgrade --install" in readme

    diagram = ET.parse(AWS_DIRECTORY / "architecture.drawio")
    assert diagram.getroot().tag == "mxfile"
    values = {
        cell.attrib.get("value", "")
        for cell in diagram.findall(".//mxCell")
        if "value" in cell.attrib
    }
    assert any("EKS" in value for value in values)
    assert any("RDS PostgreSQL" in value for value in values)
    assert any("ECR" in value for value in values)
    assert any("Managed Grafana" in value for value in values)


def test_no_state_plan_or_credentials_are_generated() -> None:
    """Static assets must not include deployment state, plans, or credentials."""

    generated_patterns = (
        "*.tfstate",
        "*.tfstate.*",
        "*.tfplan",
        "*.pem",
        "*.key",
    )
    assert not any(
        path
        for pattern in generated_patterns
        for path in (ROOT / "cloud").rglob(pattern)
    )
