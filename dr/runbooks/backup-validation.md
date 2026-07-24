# Backup validation and restore rehearsal runbook

## Detection

Backup monitoring detects a missing archive, failed checksum, encryption error, empty catalog, absent `audit_events` relation, retention anomaly, or missed daily schedule. A scheduled rehearsal also begins with this detection phase even when no failure exists.

## Immediate response

1. Quarantine the suspect archive and checksum without deleting either.
2. Prevent lifecycle promotion of an unverified backup.
3. Confirm whether a previous validated recovery point remains within RPO.
4. Open an operational incident when backup coverage falls outside RPO or multiple generations fail.
5. Preserve job logs, Kubernetes events, storage metadata, encryption-key version, and source database health.

## Recovery steps

1. Run `verify-backup.sh` in an isolated verifier with the backup, checksum, decryption wrapper, work directory, and required relations supplied through environment variables.
2. If checksum or catalog verification fails, create a new backup after confirming source database integrity; do not relabel the failed artifact as valid.
3. For the scheduled restore rehearsal, create an empty isolated PostgreSQL database and a uniquely named copy of the suspended restore Job.
4. Set the exact confirmation token and target database only after peer review.
5. Restore, validate contents and application compatibility, then destroy the isolated rehearsal database under its approved cleanup procedure.
6. Record measured restore duration and recovered timestamp.

## Validation

- SHA-256 verification passes for the encrypted or plaintext artifact actually retained.
- Decryption succeeds with the expected key version without exposing plaintext outside temporary storage.
- `pg_restore --list` succeeds and required relations, including `audit_events`, are present.
- An isolated restore completes and passes schema, row-count, timestamp-ordering, JSONB, index, authentication, workflow, SSE, and audit tests.
- Measured recovery point and restore duration satisfy RPO and RTO.

## Rollback

Stop the rehearsal Job, preserve its logs, remove access to the isolated target, and retain the previous validated backup designation. If the rehearsal touched any non-isolated database, immediately declare an incident and follow the database-failure runbook.

## Communication checklist

- Backup identifier, creation time, checksum, encryption-key version, and storage tier
- Validation or rehearsal owner, reviewer, start/end time, and environment
- RPO/RTO result, restore duration, and recovered timestamp
- Failed checks, quarantined artifacts, replacement backup, and incident reference
- Database, security, compliance, platform, and service-owner approvals
- Follow-up actions and next scheduled rehearsal

