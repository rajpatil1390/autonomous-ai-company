# PostgreSQL unavailable runbook

## Symptoms

- Audit writes fail, database connections time out, or PostgreSQL health and storage alerts fire.
- Workflow errors contain separately observable audit failures.
- API health may remain available while persistent audit operations degrade.

## Diagnosis

Check PostgreSQL endpoint resolution, network policy, credentials delivery, connection limits, locks, storage capacity, database logs, failover state, and cloud status. Determine whether impact is latency, connection refusal, authentication, corruption, or total loss. Confirm the primary application exception is not masked by audit failure.

## Dashboards

- Autonomous AI Company – Audit
- Autonomous AI Company – Overview
- PostgreSQL connections, locks, transactions, storage, and recovery dashboards supplied by the platform
- Kubernetes network and workload dashboards

## Metrics

- `autonomous_ai_company_audit_events_total{status="success"}`
- `autonomous_ai_company_audit_failures_total`
- `autonomous_ai_company_workflow_failures_total`
- `autonomous_ai_company_http_requests_total{status=~"5.."}`
- PostgreSQL availability, connection, lock, storage, and replication metrics when configured

## Logs

Inspect PostgreSQL logs, connection errors, AuditError chains, Kubernetes events, network-policy decisions, and traces from API through audit storage. Do not expose connection strings or passwords. Preserve corruption and recovery evidence before changing storage.

## Recovery

Restore routing, credentials, storage capacity, or managed failover according to evidence. For corruption or database loss, follow the database-failure disaster-recovery runbook and restore into an isolated target. Keep audit failures observable and avoid recursive logging attempts.

## Escalation

Declare SEV-1 for corruption, complete database loss, unbounded application hangs, or unknown audit integrity. Use SEV-2 for bounded persistence degradation. Page database, platform, service, and security owners as appropriate.

## Rollback

Revert the identified network, credential, connection-pool, schema, or deployment change. Never delete the database or its volume to force recovery. After failover writes begin, failback requires a separate data-reconciliation plan.

## Verification

Confirm new connections, ordered audit writes, existing audit readability, JSONB validity, indexes, no duplicate events, valid workflow and SSE completion, bounded error handling, normal PostgreSQL metrics, and compliance with RPO/RTO when recovery was required.

