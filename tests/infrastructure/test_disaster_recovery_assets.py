"""Static safety tests for disaster-recovery and backup assets."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
DR_DIRECTORY = ROOT / "dr"
BACKUP_DIRECTORY = DR_DIRECTORY / "backup"
KUBERNETES_DIRECTORY = DR_DIRECTORY / "kubernetes"
RUNBOOK_DIRECTORY = DR_DIRECTORY / "runbooks"
POLICY_PATH = ROOT / "docs" / "disaster-recovery.md"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "disaster-recovery.yml"
SCRIPTS = {
    name: BACKUP_DIRECTORY / name
    for name in ("postgres-backup.sh", "postgres-restore.sh", "verify-backup.sh")
}
MANIFESTS = {
    "backup": KUBERNETES_DIRECTORY / "backup-cronjob.yaml",
    "restore": KUBERNETES_DIRECTORY / "restore-job.yaml",
}
RUNBOOKS = {
    name: RUNBOOK_DIRECTORY / f"{name}.md"
    for name in (
        "database-failure",
        "cluster-recovery",
        "region-failure",
        "ransomware",
        "backup-validation",
    )
}
RUNBOOK_HEADINGS = (
    "Detection",
    "Immediate response",
    "Recovery steps",
    "Validation",
    "Rollback",
    "Communication checklist",
)


def load_yaml(path: Path) -> dict[str, Any]:
    """Load one standard YAML mapping safely."""

    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def load_workflow() -> dict[str, Any]:
    """Load workflow YAML without YAML 1.1 coercing its `on` key."""

    document = yaml.load(
        WORKFLOW_PATH.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert isinstance(document, dict)
    return document


def container_environment(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the first workload container's unique environment entries."""

    kind = document["kind"]
    if kind == "CronJob":
        pod_spec = document["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    else:
        pod_spec = document["spec"]["template"]["spec"]
    items = pod_spec["containers"][0]["env"]
    environment = {item["name"]: item for item in items}
    assert len(environment) == len(items)
    return environment


def workflow_steps(job_name: str) -> list[dict[str, Any]]:
    """Return one workflow job's ordered steps."""

    steps = load_workflow()["jobs"][job_name]["steps"]
    assert all(isinstance(step, dict) for step in steps)
    return steps


def step_named(job_name: str, name: str) -> dict[str, Any]:
    """Return one uniquely named workflow step."""

    matches = [step for step in workflow_steps(job_name) if step.get("name") == name]
    assert len(matches) == 1
    return matches[0]


def test_all_requested_recovery_assets_exist_and_are_nonempty() -> None:
    """Scripts, manifests, runbooks, policy, and workflow must all be present."""

    paths = [
        *SCRIPTS.values(),
        *MANIFESTS.values(),
        *RUNBOOKS.values(),
        POLICY_PATH,
        WORKFLOW_PATH,
    ]
    assert all(path.is_file() for path in paths)
    assert all(path.stat().st_size > 0 for path in paths)


def test_shell_scripts_use_fail_fast_static_syntax_contracts() -> None:
    """Scripts should have balanced shell structures without executing them."""

    for path in SCRIPTS.values():
        text = path.read_text(encoding="utf-8")
        assert text.startswith("#!/usr/bin/env bash\nset -Eeuo pipefail\n")
        assert text.count('"') % 2 == 0
        assert len(re.findall(r"^if\b", text, re.MULTILINE)) == len(
            re.findall(r"^fi$", text, re.MULTILINE)
        )
        assert len(re.findall(r"^for\b", text, re.MULTILINE)) == len(
            re.findall(r"^done$", text, re.MULTILINE)
        )
        assert text.count("{") == text.count("}")
        assert "set -x" not in text
    workflow_validation = step_named(
        "validate-scripts", "Validate shell syntax without execution"
    )["run"]
    assert 'bash -n "${script}"' in workflow_validation


def test_scripts_require_environment_and_contain_no_hardcoded_paths() -> None:
    """Runtime targets and work directories must come from configuration."""

    combined = "\n".join(path.read_text(encoding="utf-8") for path in SCRIPTS.values())
    for name in (
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DATABASE",
        "POSTGRES_USER",
        "BACKUP_FILE",
    ):
        assert name in combined
    for forbidden_path in ("/backups", "/restore-work", "/tmp/", "/var/lib/"):
        assert forbidden_path not in combined
    assert "eval " not in combined
    assert "curl " not in combined
    assert "wget " not in combined


def test_backup_script_creates_validated_checksum_protected_archives() -> None:
    """Backup creation should validate the logical archive before retention."""

    script = SCRIPTS["postgres-backup.sh"].read_text(encoding="utf-8")
    assert "pg_dump" in script
    for flag in ("--format=custom", "--compress=9", "--no-owner", "--no-acl"):
        assert flag in script
    assert "pg_restore --list" in script
    assert "sha256sum" in script
    assert script.index("pg_restore --list") < script.index(
        'sha256sum -- "${final_name}"'
    )
    assert "BACKUP_ENCRYPTION_PROGRAM" in script
    assert "REQUIRE_BACKUP_ENCRYPTION:-true" in script
    assert '"${BACKUP_ENCRYPTION_PROGRAM}" "${plain_partial}" "${final_path}"' in script
    assert "umask 077" in script


def test_backup_retention_is_bounded_to_configured_directory_and_database() -> None:
    """Retention must not recurse or delete unrelated files."""

    script = SCRIPTS["postgres-backup.sh"].read_text(encoding="utf-8")
    assert 'BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-35}"' in script
    assert 'find "${backup_directory}"' in script
    assert "-maxdepth 1" in script
    assert '-name "${POSTGRES_DATABASE}-*.dump*"' in script
    assert '-mtime "+${BACKUP_RETENTION_DAYS}"' in script
    assert "-delete" in script
    assert '[[ "${backup_directory}" != "/" ]]' in script


def test_restore_requires_checksum_and_two_manual_confirmations() -> None:
    """No restore command may run until artifact and operator guards pass."""

    script = SCRIPTS["postgres-restore.sh"].read_text(encoding="utf-8")
    token = "I_UNDERSTAND_THIS_REPLACES_DATABASE_CONTENTS"
    assert token in script
    assert '"${RESTORE_CONFIRM_DATABASE}" == "${POSTGRES_DATABASE}"' in script
    assert "sha256sum --check --status" in script
    assert "pg_restore --list" in script
    destructive_restore = script.rindex("pg_restore \\")
    assert script.index(token) < destructive_restore
    assert script.index("sha256sum --check --status") < destructive_restore
    assert script.index("pg_restore --list") < destructive_restore
    for flag in ("--clean", "--if-exists", "--exit-on-error", "--single-transaction"):
        assert flag in script
    assert "dropdb" not in script
    assert "createdb" not in script


def test_verifier_checks_checksum_decryption_catalog_and_relations() -> None:
    """Verification should reject unreadable or incomplete logical archives."""

    script = SCRIPTS["verify-backup.sh"].read_text(encoding="utf-8")
    assert "sha256sum --check --status" in script
    assert "BACKUP_DECRYPTION_PROGRAM" in script
    assert "pg_restore --list" in script
    assert 'REQUIRED_RELATIONS="${REQUIRED_RELATIONS:-audit_events}"' in script
    assert "required relation is absent from archive" in script
    assert script.index("sha256sum --check --status") < script.index(
        "pg_restore --list"
    )


def test_scripts_never_print_or_embed_passwords() -> None:
    """Credential names may be consumed, but their values must never be logged."""

    combined = "\n".join(path.read_text(encoding="utf-8") for path in SCRIPTS.values())
    assert "PGPASSWORD" not in combined
    assert "POSTGRES_PASSWORD" not in combined
    assert "password=" not in combined.lower()
    assert not re.search(r"printf[^\n]*(?:PASSWORD|SECRET|TOKEN)", combined)


def test_backup_cronjob_has_daily_utc_suspended_schedule() -> None:
    """The backup schedule should be daily but inert until production review."""

    document = load_yaml(MANIFESTS["backup"])
    assert document["apiVersion"] == "batch/v1"
    assert document["kind"] == "CronJob"
    assert document["metadata"]["namespace"] == "autonomous-ai-company"
    spec = document["spec"]
    assert spec["schedule"] == "0 2 * * *"
    assert spec["timeZone"] == "Etc/UTC"
    assert spec["suspend"] is True
    assert spec["concurrencyPolicy"] == "Forbid"
    assert spec["startingDeadlineSeconds"] == 3600


def test_restore_job_is_manual_suspended_and_disabled_by_default() -> None:
    """Applying the restore template must never modify PostgreSQL."""

    document = load_yaml(MANIFESTS["restore"])
    assert document["apiVersion"] == "batch/v1"
    assert document["kind"] == "Job"
    assert document["metadata"]["namespace"] == "autonomous-ai-company"
    assert document["spec"]["suspend"] is True
    assert document["spec"]["parallelism"] == 1
    assert document["spec"]["completions"] == 1
    assert document["spec"]["backoffLimit"] == 0
    environment = container_environment(document)
    assert environment["ALLOW_POSTGRES_RESTORE"]["value"] == "DISABLED"
    assert environment["RESTORE_CONFIRM_DATABASE"]["value"] == "DISABLED"


def test_kubernetes_workloads_use_placeholders_secrets_and_restricted_security() -> (
    None
):
    """DR jobs should be configurable and follow the existing pod security posture."""

    for path in MANIFESTS.values():
        document = load_yaml(path)
        if document["kind"] == "CronJob":
            pod_spec = document["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        else:
            pod_spec = document["spec"]["template"]["spec"]
        assert pod_spec["automountServiceAccountToken"] is False
        assert pod_spec["securityContext"]["runAsNonRoot"] is True
        container = pod_spec["containers"][0]
        assert container["image"] == "REPLACE_WITH_PINNED_BACKUP_IMAGE"
        assert container["securityContext"]["runAsNonRoot"] is True
        assert container["securityContext"]["allowPrivilegeEscalation"] is False
        assert container["securityContext"]["readOnlyRootFilesystem"] is True
        assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
        assert "resources" in container
        assert any(
            "secretKeyRef" in item.get("valueFrom", {}) for item in container["env"]
        )
        assert any(
            volume.get("persistentVolumeClaim", {}).get("claimName")
            == "REPLACE_WITH_BACKUP_PVC_NAME"
            for volume in pod_spec["volumes"]
        )


def test_manifests_contain_no_credentials_or_destructive_commands() -> None:
    """Templates should reference secrets without embedding or executing values."""

    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in MANIFESTS.values()
    )
    assert "stringData:" not in combined
    assert not re.search(r"^data:\s*", combined, re.MULTILINE)
    assert "REPLACE_WITH_POSTGRES_PASSWORD" not in combined
    assert "I_UNDERSTAND_THIS_REPLACES_DATABASE_CONTENTS" not in combined
    assert "dropdb" not in combined
    assert "kubectl" not in combined


def test_every_runbook_contains_the_complete_incident_contract() -> None:
    """Each recovery scenario must cover response through communications."""

    for path in RUNBOOKS.values():
        text = path.read_text(encoding="utf-8")
        for heading in RUNBOOK_HEADINGS:
            assert f"## {heading}" in text
    cluster = RUNBOOKS["cluster-recovery"].read_text(encoding="utf-8")
    assert "Node failure" in cluster
    assert "Cluster loss" in cluster
    assert "single-node failure" in cluster
    assert "total cluster loss" in cluster


def test_policy_defines_rto_rpo_schedules_retention_and_restore_proof() -> None:
    """The DR policy should state measurable objectives and validation cadence."""

    policy = POLICY_PATH.read_text(encoding="utf-8")
    for heading in (
        "Recovery objectives",
        "Backup schedule",
        "Retention schedule",
        "Encryption and key management",
        "Restore safety",
        "Restore verification process",
        "Recovery testing schedule",
        "Relationship to chaos engineering",
    ):
        assert f"## {heading}" in policy
    assert "Recovery Point Objective (RPO)" in policy
    assert "Recovery Time Objective (RTO)" in policy
    assert "24 hours" in policy
    assert "0 2 * * *" in policy
    assert "35 days" in policy
    assert "12 months" in policy
    assert "7 years" in policy
    for cadence in (
        "Daily",
        "Weekly",
        "Monthly",
        "Quarterly",
        "Semiannually",
        "Annually",
    ):
        assert cadence in policy
    assert "only an isolated restore proves recoverability" in policy


def test_workflow_is_manual_static_validation_only_and_ordered() -> None:
    """GitHub Actions must inspect assets without touching a database or cluster."""

    workflow = load_workflow()
    assert workflow["on"] == {"workflow_dispatch": ""}
    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    assert list(jobs) == [
        "validate-scripts",
        "validate-manifests",
        "validate-documentation",
        "upload-artifacts",
    ]
    assert "needs" not in jobs["validate-scripts"]
    assert jobs["validate-manifests"]["needs"] == "validate-scripts"
    assert jobs["validate-documentation"]["needs"] == "validate-manifests"
    assert jobs["upload-artifacts"]["needs"] == [
        "validate-scripts",
        "validate-manifests",
        "validate-documentation",
    ]
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "pg_dump ",
        "pg_restore ",
        "kubectl ",
        "helm ",
        "psql ",
        "secrets.",
        "POSTGRES_PASSWORD",
    ):
        assert forbidden not in text


def test_workflow_validates_contracts_and_uploads_all_assets() -> None:
    """Manual validation should enforce safety and retain every definition."""

    manifest_validation = step_named(
        "validate-manifests", "Validate schedule and disabled restore"
    )["run"]
    assert 'backup["spec"]["schedule"] == "0 2 * * *"' in manifest_validation
    assert 'backup["spec"]["suspend"] is True' in manifest_validation
    assert 'restore["spec"]["suspend"] is True' in manifest_validation
    assert 'env["ALLOW_POSTGRES_RESTORE"] == "DISABLED"' in manifest_validation

    documentation_validation = step_named(
        "validate-documentation", "Validate runbook completeness"
    )["run"]
    assert "len(records) == 5" in documentation_validation
    for heading in RUNBOOK_HEADINGS:
        assert f'"{heading}"' in documentation_validation

    upload = step_named(
        "upload-artifacts", "Upload backup, restore, and recovery definitions"
    )
    paths = upload["with"]["path"]
    assert "dr/backup/*.sh" in paths
    assert "dr/kubernetes/*.yaml" in paths
    assert "dr/runbooks/*.md" in paths
    assert "docs/disaster-recovery.md" in paths
    assert upload["with"]["if-no-files-found"] == "error"
