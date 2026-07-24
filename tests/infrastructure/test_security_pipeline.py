"""Static contract tests for the production security validation pipeline."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "security.yml"
SECURITY_DIRECTORY = ROOT / "security"
POLICY_FILES = {
    "trivy": SECURITY_DIRECTORY / "trivy.yaml",
    "bandit": SECURITY_DIRECTORY / "bandit.yaml",
    "semgrep": SECURITY_DIRECTORY / "semgrep.yaml",
    "osv": SECURITY_DIRECTORY / "osv-scanner.yaml",
    "syft": SECURITY_DIRECTORY / "syft.yaml",
}
DOCUMENTATION_FILES = {
    "cosign": SECURITY_DIRECTORY / "cosign-policy.md",
    "security": SECURITY_DIRECTORY / "SECURITY.md",
}
EXPECTED_JOB_ORDER = [
    "dependency-audit",
    "filesystem-scan",
    "container-scan",
    "bandit",
    "semgrep",
    "sbom",
    "osv-scan",
    "cosign-verification",
]


def load_yaml(path: Path) -> dict[str, Any]:
    """Load YAML without treating GitHub's `on` key as a boolean."""

    document = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(document, dict)
    return document


def load_workflow() -> dict[str, Any]:
    """Return the parsed security workflow."""

    return load_yaml(WORKFLOW_PATH)


def job_steps(job_name: str) -> list[dict[str, Any]]:
    """Return one job's ordered step mappings."""

    steps = load_workflow()["jobs"][job_name]["steps"]
    assert all(isinstance(step, dict) for step in steps)
    return steps


def step_named(job_name: str, name: str) -> dict[str, Any]:
    """Return one uniquely named step from a job."""

    matches = [step for step in job_steps(job_name) if step.get("name") == name]
    assert len(matches) == 1
    return matches[0]


def test_all_requested_security_assets_exist_and_are_nonempty() -> None:
    """Every requested workflow, policy, report policy, and test asset must exist."""

    assert WORKFLOW_PATH.is_file()
    assert all(path.is_file() for path in POLICY_FILES.values())
    assert all(path.is_file() for path in DOCUMENTATION_FILES.values())
    assert all(
        path.stat().st_size > 0
        for path in (*POLICY_FILES.values(), *DOCUMENTATION_FILES.values())
    )


def test_workflow_triggers_and_permissions_are_least_privilege() -> None:
    """Security validation runs on the required events with read-only defaults."""

    workflow = load_workflow()
    assert workflow["on"] == {
        "pull_request": "",
        "push": {"branches": ["main"]},
        "workflow_dispatch": "",
    }
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["env"]["PYTHON_VERSION"] == "3.12"
    assert workflow["concurrency"]["cancel-in-progress"] == "true"


def test_jobs_are_complete_and_explicitly_ordered() -> None:
    """The evidence-producing checks follow the requested production sequence."""

    jobs = load_workflow()["jobs"]
    assert list(jobs) == EXPECTED_JOB_ORDER
    assert "needs" not in jobs[EXPECTED_JOB_ORDER[0]]
    for previous, current in zip(
        EXPECTED_JOB_ORDER[:-1], EXPECTED_JOB_ORDER[1:], strict=True
    ):
        assert jobs[current]["needs"] == previous
        assert jobs[current]["if"] == "${{ !cancelled() }}"


def test_dependency_audit_generates_and_uploads_json() -> None:
    """pip-audit should inspect installed dependencies and retain its report."""

    command = step_named("dependency-audit", "Audit installed dependencies")["run"]
    assert "pip-audit --local" in command
    assert "--format json" in command
    assert "--output results/pip-audit.json" in command
    upload = step_named("dependency-audit", "Upload pip-audit report")
    assert upload["if"] == "always()"
    assert upload["with"]["path"] == "results/pip-audit.json"


def test_trivy_scans_filesystem_and_built_production_image() -> None:
    """Trivy should apply one policy to source and the actual production target."""

    filesystem = step_named("filesystem-scan", "Scan repository with Trivy")
    container = step_named("container-scan", "Scan production image with Trivy")
    assert filesystem["with"]["scan-type"] == "fs"
    assert filesystem["with"]["scan-ref"] == "."
    assert filesystem["with"]["output"] == "results/trivy-filesystem.json"
    assert container["with"]["scan-type"] == "image"
    assert container["with"]["output"] == "results/trivy-container.json"
    assert filesystem["with"]["trivy-config"] == "security/trivy.yaml"
    assert container["with"]["trivy-config"] == "security/trivy.yaml"
    build = step_named("container-scan", "Build local production image")["run"]
    assert "docker build" in build
    assert "--target production" in build


def test_bandit_and_semgrep_generate_machine_readable_reports() -> None:
    """Python-specific scanners must use committed policies and JSON output."""

    bandit = step_named("bandit", "Run Bandit")["run"]
    assert "--configfile security/bandit.yaml" in bandit
    assert "--recursive src" in bandit
    assert "--format json" in bandit
    assert "results/bandit.json" in bandit
    semgrep = step_named("semgrep", "Run local and maintained Semgrep policies")["run"]
    for policy in ("security/semgrep.yaml", "p/python", "p/security-audit"):
        assert f"--config {policy}" in semgrep
    assert "--json" in semgrep
    assert "--error" in semgrep
    assert "results/semgrep.json" in semgrep


def test_syft_generates_both_required_sbom_formats() -> None:
    """The SBOM job should retain SPDX and CycloneDX representations."""

    install = step_named("sbom", "Install pinned Syft")
    assert re.fullmatch(
        r"anchore/sbom-action/download-syft@[0-9a-f]{40}", install["uses"]
    )
    command = step_named("sbom", "Generate SPDX and CycloneDX SBOMs")["run"]
    assert "--config security/syft.yaml" in command
    assert "spdx-json=results/sbom.spdx.json" in command
    assert "cyclonedx-json=results/sbom.cyclonedx.json" in command
    paths = step_named("sbom", "Upload SBOM artifacts")["with"]["path"]
    assert "results/sbom.spdx.json" in paths
    assert "results/sbom.cyclonedx.json" in paths


def test_osv_scan_uses_recursive_json_policy_and_uploads_report() -> None:
    """OSV should inspect all dependency manifests and fail on findings."""

    policy = load_yaml(POLICY_FILES["osv"])
    assert policy == {
        "schema_version": "1",
        "scan_path": ".",
        "recursive": "true",
        "output_format": "json",
        "output_file": "results/osv.json",
        "fail_on_vulnerability": "true",
        "ignored_vulnerabilities": [],
    }
    scanner = step_named("osv-scan", "Scan dependency manifests with OSV-Scanner")
    assert re.fullmatch(
        r"google/osv-scanner-action/osv-scanner-action@[0-9a-f]{40}",
        scanner["uses"],
    )
    args = scanner["with"]["scan-args"]
    assert "--recursive" in args
    assert "--format=json" in args
    assert "--output=results/osv.json" in args
    upload = step_named("osv-scan", "Upload OSV report")
    assert upload["with"]["path"] == "results/osv.json"


def test_cosign_only_verifies_digest_bound_keyless_signatures() -> None:
    """The final gate must verify, never create, a production signature."""

    workflow = load_workflow()
    job = workflow["jobs"]["cosign-verification"]
    assert job["permissions"] == {"contents": "read", "id-token": "write"}
    validation = step_named("cosign-verification", "Validate digest and trust inputs")[
        "run"
    ]
    assert "@sha256:[0-9a-f]{64}" in validation
    verification = step_named("cosign-verification", "Verify keyless image signature")[
        "run"
    ]
    assert "cosign verify" in verification
    assert "--certificate-identity-regexp" in verification
    assert "https://token.actions.githubusercontent.com" in verification
    assert "--output json" in verification
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert re.search(r"\bcosign\s+verify\b", workflow_text)
    assert not re.search(r"\bcosign\s+sign(?:-blob)?\b", workflow_text)


def test_every_scanner_report_is_uploaded_even_after_a_finding() -> None:
    """Each scanner must preserve evidence through an unconditional artifact step."""

    workflow = load_workflow()
    expected_paths = {
        "dependency-audit": "results/pip-audit.json",
        "filesystem-scan": "results/trivy-filesystem.json",
        "container-scan": "results/trivy-container.json",
        "bandit": "results/bandit.json",
        "semgrep": "results/semgrep.json",
        "osv-scan": "results/osv.json",
        "cosign-verification": "results/cosign-verification.json",
    }
    for job_name, report_path in expected_paths.items():
        uploads = [
            step
            for step in workflow["jobs"][job_name]["steps"]
            if "upload-artifact" in step.get("uses", "")
        ]
        assert len(uploads) == 1
        assert uploads[0]["if"] == "always()"
        assert uploads[0]["with"]["path"] == report_path
        assert uploads[0]["with"]["if-no-files-found"] == "error"


def test_all_external_security_actions_are_immutable_sha_pinned() -> None:
    """Mutable third-party action tags must not control security-sensitive jobs."""

    workflow = load_workflow()
    protected_owners = {
        "aquasecurity",
        "anchore",
        "google",
        "sigstore",
        "aws-actions",
    }
    matching_actions: list[str] = []
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            action = step.get("uses", "")
            if action.split("/", maxsplit=1)[0] in protected_owners:
                matching_actions.append(action)
                assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", action)
    assert matching_actions


def test_scanner_configuration_is_valid_and_fail_closed() -> None:
    """Committed scanner policies should use strict, low-noise security defaults."""

    trivy = load_yaml(POLICY_FILES["trivy"])
    assert trivy["exit-code"] == "1"
    assert trivy["severity"] == ["HIGH", "CRITICAL"]
    assert set(trivy["scanners"]) == {"vuln", "secret", "misconfig"}
    assert trivy["ignore-unfixed"] == "true"

    bandit = load_yaml(POLICY_FILES["bandit"])
    assert "tests" in bandit["exclude_dirs"]
    assert bandit["skips"] == []

    semgrep = load_yaml(POLICY_FILES["semgrep"])
    rules = semgrep["rules"]
    assert len(rules) >= 5
    assert len({rule["id"] for rule in rules}) == len(rules)
    assert all(rule["severity"] == "ERROR" for rule in rules)
    assert all(rule["languages"] == ["python"] for rule in rules)

    syft = load_yaml(POLICY_FILES["syft"])
    assert syft["check-for-app-update"] == "false"
    assert "./.git/**" in syft["exclude"]


def test_security_policy_covers_reporting_disclosure_and_response() -> None:
    """The disclosure policy should give reporters a safe, actionable process."""

    policy = DOCUMENTATION_FILES["security"].read_text(encoding="utf-8")
    for heading in (
        "Supported versions",
        "Reporting a vulnerability",
        "Response timeline",
        "Coordinated disclosure",
    ):
        assert f"## {heading}" in policy
    assert "Report a vulnerability" in policy
    assert "Do not open a public issue" in policy
    assert "1 business day" in policy
    assert "3 business days" in policy


def test_cosign_policy_documents_identity_and_slsa_boundary() -> None:
    """Signature verification documentation must define trust and provenance limits."""

    policy = DOCUMENTATION_FILES["cosign"].read_text(encoding="utf-8")
    assert "immutable digest" in policy
    assert "Keyless verification" in policy
    assert "Trusted identities" in policy
    assert "token.actions.githubusercontent.com" in policy
    assert "SLSA compatibility" in policy
    assert "not by itself a SLSA provenance statement" in policy


def test_workflow_contains_no_embedded_credentials_or_secret_values() -> None:
    """The workflow should consume OIDC and repository variables, never static keys."""

    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    forbidden = (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "BEGIN PRIVATE KEY",
        "password:",
        "${{ secrets.",
    )
    assert all(value not in text for value in forbidden)
    assert "id-token: write" in text
    assert "AWS_SECURITY_READ_ROLE_ARN" in text
    assert "SECURITY_IMAGE_REFERENCE" in text
    assert "COSIGN_TRUSTED_IDENTITY_REGEXP" in text
