# Disaster recovery policy

## Purpose and scope

Disaster recovery protects the production service, PostgreSQL audit history, configuration, secrets, and deployment capability from corruption, infrastructure loss, regional outage, and destructive compromise. These assets are infrastructure-only: they neither change application behavior nor execute a backup or restore when committed or validated.

## Recovery objectives

Recovery Point Objective (RPO) is the maximum acceptable interval of data that may need to be reconstructed after recovery. Recovery Time Objective (RTO) is the maximum target duration from incident declaration until the service is restored to its agreed minimum operating state.

Initial production objectives are:

| Scope | RPO | RTO | Minimum recovered state |
|---|---:|---:|---|
| PostgreSQL audit database | 24 hours | 4 hours | Valid database, ordered audit history, new writes accepted |
| Kubernetes cluster loss with database available | No database loss | 4 hours | API, ingress, authentication, workflows, and observability available |
| Full regional outage | 24 hours | 8 hours | Single recovery-region writer and validated external traffic |
| Ransomware or destructive compromise | Last verified clean point | 24 hours | Clean-room infrastructure with rotated trust and security approval |

These are explicit engineering targets, not guarantees. Business, compliance, legal, and security owners must approve them and revisit them after every exercise or material architecture change. A 24-hour database RPO follows from one daily logical backup; a tighter RPO requires additional replication or backup frequency outside this step.

## Backup schedule

- Daily logical PostgreSQL backup at 02:00 UTC, expressed by `0 2 * * *`.
- The committed CronJob is suspended until its image digest, dedicated backup PVC or object-storage integration, encryption wrapper, secret references, and first restore rehearsal are approved.
- Every backup uses PostgreSQL custom format, no ownership or ACL restoration, maximum archive compression, an external encryption wrapper, and a SHA-256 checksum sidecar.
- Backup success is declared only after `pg_restore --list` succeeds and the final retained artifact is checksummed.
- Backup generation and verification must emit operational metadata without passwords, tokens, plaintext data, or encryption keys.

## Retention schedule

| Tier | Retention | Enforcement |
|---|---:|---|
| Daily operational backups | 35 days | Backup script on its dedicated storage tier |
| Monthly immutable copies | 12 months | Object-storage lifecycle and retention lock |
| Yearly compliance copies | 7 years, when legally required | Separate immutable archive account and approved policy |

Retention must satisfy applicable data-minimization and legal requirements. The script deletes only matching PostgreSQL backup artifacts older than `BACKUP_RETENTION_DAYS` inside the explicitly configured backup directory. Monthly and yearly promotion belongs to storage lifecycle policy, not the application or script.

Maintain at least three copies across two storage technologies with one immutable, access-isolated copy. Backup storage, encryption keys, and recovery identities must not share the same failure domain or administrative trust as production writers.

## Encryption and key management

`postgres-backup.sh` requires `BACKUP_ENCRYPTION_PROGRAM` by default. This is a narrow adapter contract: an approved executable receives plaintext input and encrypted output paths. The executable should use envelope encryption with a managed KMS key, authenticated encryption, key-version metadata, and an identity dedicated to backup creation.

The scripts contain no encryption key, command template, `eval`, or plaintext credential. Restore and verification accept a separate `BACKUP_DECRYPTION_PROGRAM`. Plaintext exists only in a restricted temporary directory and is removed by a trap.

## Restore safety

Restore is manual and disabled through independent controls:

- the Kubernetes Job is `suspend: true`;
- `ALLOW_POSTGRES_RESTORE` defaults to `DISABLED` in the template;
- the script requires the exact token `I_UNDERSTAND_THIS_REPLACES_DATABASE_CONTENTS`;
- `RESTORE_CONFIRM_DATABASE` must exactly match `POSTGRES_DATABASE`;
- backup and checksum must be colocated and pass SHA-256 validation; and
- the archive catalog must parse before any database modification begins.

Always restore into an empty isolated database first. Never overwrite the only production database or use the restore template without a peer-reviewed, uniquely named copy.

## Restore verification process

1. Identify the required recovery timestamp and choose the newest eligible backup at or before it.
2. Verify retention-lock state, artifact identity, SHA-256 checksum, encryption key version, and provenance.
3. Decrypt through the approved wrapper into isolated temporary storage.
4. Parse the custom-format catalog and confirm required relations such as `audit_events`.
5. Restore into an isolated PostgreSQL target using a manually enabled Job.
6. Validate schema, indexes, row counts, UTC timestamp ordering, JSONB parsing, append-only audit history, and the recovered timestamp.
7. Run authentication, one workflow, one SSE workflow, and new audit-write checks.
8. Measure restore duration and compare recovered time and service time with RPO and RTO.
9. Obtain database, application, security, and incident-command approval before promotion.

Checksum and catalog checks prove artifact integrity and readability, but only an isolated restore proves recoverability.

## Recovery testing schedule

| Frequency | Test |
|---|---|
| Every backup | Non-empty archive, catalog parsing, encryption output, and SHA-256 generation |
| Daily | Verify the newest retained checksum and archive catalog |
| Weekly | Restore a sampled backup into an ephemeral isolated database and validate required relations |
| Monthly | Full database restore plus authenticated workflow, SSE, and audit validation |
| Quarterly | Node and complete cluster recovery rehearsal |
| Semiannually | Regional failover tabletop and technical exercise |
| Annually | Ransomware clean-room recovery exercise |

Failed validation immediately removes the artifact's “validated” status and starts the backup-validation runbook. Track restore duration and recovered timestamp as trends, not merely pass/fail results.

## Incident runbooks

- [Database corruption and failure](../dr/runbooks/database-failure.md)
- [Node failure and cluster loss](../dr/runbooks/cluster-recovery.md)
- [Region outage](../dr/runbooks/region-failure.md)
- [Ransomware and destructive compromise](../dr/runbooks/ransomware.md)
- [Backup validation and restore rehearsal](../dr/runbooks/backup-validation.md)

Each runbook defines detection, immediate response, recovery, validation, rollback, and communication requirements.

## Roles and authority

The incident commander owns scope, priority, and go/no-go decisions. The database lead owns backup selection, restore, and writer identity. The platform lead owns infrastructure, cluster, routing, and storage. The security lead owns compromise boundaries, credentials, evidence, and clean-room approval. The communications lead owns consistent stakeholder updates. No single operator should both select and promote a production restore without peer review.

## Evidence and auditability

Retain backup identifier, source database identity, creation timestamp, recovered timestamp, checksum, encryption-key version, image digest, script revision, CronJob/Job definition, storage tier, retention state, validation result, restore duration, approvers, incident identifier, and cleanup result.

Never retain database passwords, JWTs, API keys, plaintext backup content, encryption keys, or raw customer prompts in logs or reports.

## Relationship to chaos engineering

Chaos engineering validates behavior while faults are injected; disaster recovery validates rebuilding and restoring after service continuity is no longer sufficient. The PostgreSQL network-loss experiment tests graceful failure, while these assets prove that a verified backup can re-establish durable state. Chaos findings should update recovery assumptions, and restore exercises should define the recovery objectives used by future chaos game days.

## Change control

Any change to RPO, RTO, schedule, retention, encryption, backup location, restore guard, database version, schema, or recovery region requires review by platform, database, security, and service owners. Repeat an isolated restore after the change before treating new backups as production recovery points.

