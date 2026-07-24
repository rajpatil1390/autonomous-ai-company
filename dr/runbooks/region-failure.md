# Region outage runbook

## Detection

- Cloud provider status and independent probes confirm loss of regional control plane, networking, compute, database, or object storage.
- Multiple availability zones fail simultaneously or the regional service cannot satisfy the documented RTO.
- External health checks show production unavailable while global dependencies remain reachable.

Require evidence from at least two independent signals before declaring regional failover, unless the incident commander authorizes immediate action for safety.

## Immediate response

1. Declare a critical incident and activate the regional disaster-recovery team.
2. Freeze releases, infrastructure applies, key rotation, backup expiration, and DNS changes outside the controlled failover plan.
3. Confirm the secondary region is not affected and has access to signed images, immutable backups, Terraform state, Helm values, and Secrets Manager replicas.
4. Determine the latest replicated or backup recovery point and communicate the possible data-loss window.
5. Prevent split-brain writes before enabling a secondary database writer.

## Recovery steps

1. Provision or activate networking, EKS, node groups, ingress, monitoring, identity, and least-privilege roles in the recovery region.
2. Restore PostgreSQL from the latest validated cross-region backup or promote an approved replica.
3. Load secrets from the recovery region's secret store; never copy plaintext credentials through chat or CI logs.
4. Deploy the digest-pinned application image using the production Helm values with recovery-region overrides.
5. Run internal database, API, workflow, SSE, audit, and observability validation.
6. Shift global traffic gradually and monitor error, latency, data, and capacity signals.

## Validation

- Only one writable database primary exists.
- DNS and certificates resolve to the recovery region from independent networks.
- API replicas, HPA, probes, PostgreSQL, audit history, authentication, workflows, metrics, and tracing meet steady state.
- The measured recovery point and time are within approved RPO and RTO or the exception is explicitly communicated.

## Rollback

Before production traffic is committed, revert global routing to the original region if it becomes healthy and remains the authoritative writer. After failover writes begin, do not fail back automatically. Reconcile data, establish a single source of truth, validate replication direction, and schedule a separate approved failback.

## Communication checklist

- Provider incident references and independent evidence
- Primary and recovery region status, traffic percentage, and writer identity
- RPO/RTO status and customer data-loss estimate
- DNS, certificate, database, secrets, and deployment milestones
- Executive, customer, support, security, legal, and regulatory messages
- Failback decision, residual regional risk, and post-incident review

