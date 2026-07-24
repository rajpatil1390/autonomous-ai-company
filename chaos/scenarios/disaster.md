# Disaster scenario: prolonged PostgreSQL unavailability

## Objective

Validate graceful degradation and recovery when API-to-PostgreSQL connectivity is unavailable beyond a normal transient timeout. This scenario uses reversible network loss from API pods; it never deletes the database, volume, schema, or audit rows.

## Authorization boundary

Run only in an approved game day after the shorter `database-loss.yaml` experiment has passed in a non-production environment. A database owner, application owner, incident commander, and rollback operator must be present. Confirm backups and restore evidence before starting.

## Scenario sequence

1. Capture the steady state and evidence defined in [workflow.md](workflow.md).
2. Verify the database-loss engine is stopped, annotation-gated, limited to one API pod, scoped to the PostgreSQL host and port 5432, and bounded in duration.
3. Start the approved live engine using the opt-in workflow.
4. Submit synthetic authenticated requests at a low fixed rate.
5. Observe timeout behavior, error isolation, service responsiveness, audit-failure metrics, database connections, and replica health.
6. Stop the experiment at its time limit or immediately on a failure criterion.
7. Perform [rollback.md](rollback.md) and [recovery.md](recovery.md).

Do not combine database loss with pod deletion, CPU pressure, memory pressure, load testing, deployment, or database maintenance during this scenario.

## Expected results

- The API remains reachable and observable.
- PostgreSQL-dependent audit writes fail in a bounded and explicit way.
- Audit failures never replace primary workflow failures.
- Requests do not hang indefinitely or corrupt shared workflow state.
- The database remains unchanged by the network fault.
- New audit events persist in order after connectivity is restored.

## Failure criteria

Declare an incident for unbounded request hangs, total API loss, unexpected database mutation, silent audit loss, primary errors masked by audit errors, cross-pod workflow corruption, impact beyond the approved pod/host/port, or recovery-objective breach.

## Disaster recovery evidence

Retain database health and backup status, application and audit errors, Kubernetes events, Litmus results, dashboard snapshots, start/stop/recovery timestamps, post-recovery workflow identifiers, and a comparison of pre-test and post-test audit history.

## Follow-up

Convert every discovered gap into an owned action with severity, due date, verification method, and configuration or runbook change. Repeat only after the fix is deployed and the same steady-state measurements are available.

