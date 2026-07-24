# Database corruption and failure runbook

## Detection

- PostgreSQL health checks, connection attempts, or audit writes fail repeatedly.
- Database logs report corruption, failed recovery, checksum errors, storage faults, or unexpected schema changes.
- Audit row counts, ordering, or append-only invariants differ from the last validated baseline.
- Monitoring shows rising database latency, exhausted connections, replication lag, or storage saturation.

Record the detection time, affected databases, last known-good transaction time, current primary identity, and whether corruption is logical, physical, or still unconfirmed.

## Immediate response

1. Declare an incident and assign incident commander, database lead, application lead, communications lead, and scribe.
2. Stop deployments, migrations, retention deletion, and automated failover changes.
3. Isolate a suspected corrupted writer without deleting its volumes, logs, or snapshots.
4. Preserve database logs, storage snapshots, audit evidence, Kubernetes events, and configuration.
5. If continuing writes can expand damage, place the affected database or application path into the approved restricted mode.
6. Identify the latest checksum-valid, decryptable backup and its recovery point.

## Recovery steps

1. Restore into a new isolated database; never overwrite the only affected database first.
2. Verify the backup checksum, decrypt through the approved KMS-backed wrapper, and inspect the `pg_restore` catalog.
3. Use a uniquely named copy of the suspended restore Job and set the exact backup, checksum, destination, confirmation database, and restore token.
4. Restore with network access limited to the isolated target.
5. Apply required schema compatibility checks and compare critical audit counts and timestamps.
6. Quiesce writers, capture the final recovery boundary, and promote the validated database through the approved failover procedure.
7. Rotate credentials if compromise cannot be excluded.

## Validation

- PostgreSQL accepts connections and reports a clean recovery state.
- `audit_events` exists, indexes are present, JSONB values parse, timestamps are ordered, and append-only history matches the selected recovery point.
- Authentication, one workflow run, and one SSE workflow complete against the recovered database.
- Audit failures do not mask primary errors and new audit events persist exactly once.
- Error rate, latency, connection count, and storage signals remain stable through the observation period.

## Rollback

If validation fails, stop traffic to the recovered target, preserve its evidence, and return routing to the last stable read-only or restricted state. Do not reconnect the suspected corrupted primary. Select an earlier validated recovery point or escalate to PostgreSQL specialist recovery.

## Communication checklist

- Incident identifier, severity, commander, and secure collaboration channel
- Impacted services, customers, regions, and data interval
- Selected recovery point, estimated data loss bounded by RPO, and current RTO status
- Decision log for write isolation, restore selection, promotion, and credential rotation
- Regulatory, legal, security, customer-support, and executive notifications as required
- Recovery confirmation, residual risk, follow-up owners, and post-incident review time

