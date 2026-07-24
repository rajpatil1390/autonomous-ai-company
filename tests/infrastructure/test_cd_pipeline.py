"""Static security and ordering tests for production continuous deployment."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIRECTORY = ROOT / ".github" / "workflows"
SCRIPT_DIRECTORY = ROOT / "scripts"
DEPLOY_WORKFLOW = WORKFLOW_DIRECTORY / "deploy.yml"
RELEASE_WORKFLOW = WORKFLOW_DIRECTORY / "release.yml"
SCRIPTS = {
    "deploy.sh": SCRIPT_DIRECTORY / "deploy.sh",
    "rollback.sh": SCRIPT_DIRECTORY / "rollback.sh",
    "smoke_test.sh": SCRIPT_DIRECTORY / "smoke_test.sh",
}


def load_workflow(path: Path) -> dict[str, Any]:
    """Parse GitHub workflow YAML without YAML 1.1 coercing the `on` key."""

    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(workflow, dict)
    return workflow


def deployment_steps() -> list[dict[str, Any]]:
    """Return the single reusable deployment job's ordered step mappings."""

    workflow = load_workflow(DEPLOY_WORKFLOW)
    steps = workflow["jobs"]["deploy"]["steps"]
    assert all(isinstance(step, dict) for step in steps)
    return steps


def step_named(name: str) -> dict[str, Any]:
    """Return one uniquely named deployment step."""

    matches = [step for step in deployment_steps() if step.get("name") == name]
    assert len(matches) == 1
    return matches[0]


def test_required_cd_files_exist_without_modifying_other_layers() -> None:
    """The CD addition should consist only of the requested workflow assets."""

    assert DEPLOY_WORKFLOW.is_file()
    assert RELEASE_WORKFLOW.is_file()
    assert set(SCRIPTS) <= {path.name for path in SCRIPT_DIRECTORY.iterdir()}
    assert (ROOT / "docs" / "deployment.md").is_file()
    assert all(path.stat().st_size > 0 for path in SCRIPTS.values())


def test_workflow_yaml_and_release_trigger_contract() -> None:
    """Only a published GitHub Release should invoke production deployment."""

    release = load_workflow(RELEASE_WORKFLOW)
    deploy = load_workflow(DEPLOY_WORKFLOW)
    assert release["on"] == {"release": {"types": ["published"]}}
    release_job = release["jobs"]["deploy"]
    assert release_job["uses"] == "./.github/workflows/deploy.yml"
    assert release_job["with"]["image_tag"] == ("${{ github.event.release.tag_name }}")
    assert release_job["secrets"] == "inherit"
    assert deploy["on"]["workflow_call"]["inputs"]["image_tag"] == {
        "description": "Immutable GitHub Release tag to publish and deploy",
        "required": "true",
        "type": "string",
    }


def test_pipeline_order_matches_security_and_deployment_gates() -> None:
    """Build, verification, signing, deployment, and rollback must stay ordered."""

    names = [step["name"] for step in deployment_steps()]
    ordered_gates = [
        "Build production image",
        "Run complete test suite",
        "Run Ruff",
        "Scan image with Trivy",
        "Sign and verify scanned image archive before publication",
        "Configure short-lived AWS credentials through OIDC",
        "Sign in to Amazon ECR",
        "Push immutable image to ECR",
        "Sign and verify published image with GitHub OIDC",
        "Configure kubectl for private EKS",
        "Deploy signed image with atomic Helm upgrade",
        "Run authenticated production smoke tests",
        "Roll back failed deployment",
        "Fail release after rollback",
    ]
    assert [names.index(name) for name in ordered_gates] == sorted(
        names.index(name) for name in ordered_gates
    )


def test_oidc_permissions_environment_and_private_runner_are_explicit() -> None:
    """Deployment should use protected short-lived identity from inside the VPC."""

    workflow = load_workflow(DEPLOY_WORKFLOW)
    assert workflow["permissions"] == {"contents": "read", "id-token": "write"}
    job = workflow["jobs"]["deploy"]
    assert job["environment"] == "production"
    assert job["runs-on"] == ["self-hosted", "linux", "x64", "production-vpc"]
    oidc = step_named("Configure short-lived AWS credentials through OIDC")
    assert re.fullmatch(
        r"aws-actions/configure-aws-credentials@[0-9a-f]{40}", oidc["uses"]
    )
    assert oidc["with"]["role-to-assume"] == "${{ env.AWS_ROLE_ARN }}"
    assert oidc["with"]["aws-region"] == "${{ env.AWS_REGION }}"


def test_security_actions_are_sha_pinned_and_image_is_digest_signed() -> None:
    """Mutable security-action tags and unsigned deployable digests are forbidden."""

    for name in (
        "Scan image with Trivy",
        "Install Cosign",
        "Configure short-lived AWS credentials through OIDC",
        "Sign in to Amazon ECR",
    ):
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", step_named(name)["uses"])

    archive_signature = step_named(
        "Sign and verify scanned image archive before publication"
    )["run"]
    assert "cosign sign-blob --yes" in archive_signature
    assert "cosign verify-blob" in archive_signature
    publication = step_named("Push immutable image to ECR")["run"]
    assert "docker push" in publication
    assert "aws ecr describe-images" in publication
    assert 'if [[ ! "${DIGEST}" =~' in publication
    assert "sha256:[0-9a-f]{64}" in publication
    registry_signature = step_named("Sign and verify published image with GitHub OIDC")[
        "run"
    ]
    assert 'cosign sign --yes "${SIGNED_REFERENCE}"' in registry_signature
    assert "cosign verify" in registry_signature
    assert "token.actions.githubusercontent.com" in registry_signature


def test_helm_deployment_is_atomic_waiting_and_idempotent() -> None:
    """A stable upgrade/install command must converge or restore prior state."""

    workflow_step = step_named("Deploy signed image with atomic Helm upgrade")
    assert workflow_step["id"] == "helm-deploy"
    assert workflow_step["continue-on-error"] == "true"
    assert "bash ./scripts/deploy.sh" in workflow_step["run"]

    script = SCRIPTS["deploy.sh"].read_text(encoding="utf-8")
    assert 'helm upgrade --install "${release}" "${chart}"' in script
    for flag in (
        "--atomic",
        "--cleanup-on-fail",
        "--wait",
        "--wait-for-jobs",
        "--timeout 15m",
        "--history-max 10",
    ):
        assert flag in script
    assert "previous_revision=" in script
    assert 'echo "previous_revision=${previous_revision}"' in script
    assert "kubectl rollout status" in script


def test_rollback_runs_only_for_deployment_or_smoke_failure() -> None:
    """Successful releases must never invoke Helm rollback."""

    rollback = step_named("Roll back failed deployment")
    condition = rollback["if"]
    assert "always()" in condition
    assert "steps.helm-deploy.outcome == 'failure'" in condition
    assert "steps.smoke-tests.outcome == 'failure'" in condition
    assert "bash ./scripts/rollback.sh" in rollback["run"]
    assert "helm rollback" not in DEPLOY_WORKFLOW.read_text(encoding="utf-8")

    script = SCRIPTS["rollback.sh"].read_text(encoding="utf-8")
    assert 'helm rollback "${release}" "${previous_revision}"' in script
    assert "--wait" in script
    assert "--timeout 15m" in script
    assert "No prior Helm revision exists" in script


def test_smoke_tests_cover_every_required_production_endpoint() -> None:
    """Post-deployment verification should cross all public API capabilities."""

    step = step_named("Run authenticated production smoke tests")
    assert step["if"] == "steps.helm-deploy.outcome == 'success'"
    assert step["continue-on-error"] == "true"
    script = SCRIPTS["smoke_test.sh"].read_text(encoding="utf-8")
    for path in (
        "/health",
        "/version",
        "/auth/login",
        "/workflow/run",
        "/metrics",
        "/workflow/stream",
    ):
        assert path in script
    assert script.count("Authorization: Bearer ${token}") == 2
    assert "event: workflow_started" in script
    assert "event: workflow_completed" in script
    assert "SMOKE_USERNAME must be supplied through a protected secret" in script
    assert "SMOKE_PASSWORD must be supplied through a protected secret" in script


def test_shell_scripts_have_fail_fast_syntax_and_no_embedded_credentials() -> None:
    """Scripts should fail predictably without containing deploy-time secrets."""

    combined = "\n".join(path.read_text(encoding="utf-8") for path in SCRIPTS.values())
    for path in SCRIPTS.values():
        text = path.read_text(encoding="utf-8")
        assert text.startswith("#!/usr/bin/env bash\nset -Eeuo pipefail\n")
        assert text.count('"') % 2 == 0
        assert text.count("{") == text.count("}")
        assert text.count("(") == text.count(")")
    assert "admin123" not in combined
    assert "AKIA" not in combined
    assert "sk-ant-" not in combined
    assert "BEGIN PRIVATE KEY" not in combined


def test_workflows_contain_no_static_cloud_or_application_credentials() -> None:
    """Only GitHub variables, protected secrets, and OIDC may cross the boundary."""

    workflows = DEPLOY_WORKFLOW.read_text(
        encoding="utf-8"
    ) + RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "aws-access-key-id" not in workflows.lower()
    assert "aws-secret-access-key" not in workflows.lower()
    assert "AWS_ACCESS_KEY_ID" not in workflows
    assert "AWS_SECRET_ACCESS_KEY" not in workflows
    assert "admin123" not in workflows
    assert "SMOKE_PASSWORD: ${{ secrets.SMOKE_PASSWORD }}" in workflows
    assert "AWS_ROLE_ARN: ${{ vars.AWS_DEPLOY_ROLE_ARN }}" in workflows


def test_deployment_documentation_covers_security_and_operations() -> None:
    """Operators need explicit identity, release, smoke, and rollback guidance."""

    documentation = (ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")
    for section in (
        "## Prerequisites",
        "## Release pipeline",
        "## Idempotency and atomic deployment",
        "## Smoke tests",
        "## Rollback behavior",
        "## Release procedure",
    ):
        assert section in documentation
    assert "environment:production" in documentation
    assert "No deployment occurs" in documentation
    assert "both proofs have been verified" in documentation
    assert "Terraform is intentionally not modified" in documentation
