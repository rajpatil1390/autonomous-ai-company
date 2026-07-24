# Node failure and cluster loss runbook

## Detection

- Nodes remain `NotReady`, workloads cannot schedule, control-plane access fails, or multiple availability zones lose capacity.
- API replicas, PostgreSQL connectivity, ingress, DNS, metrics, or persistent-volume attachments fall below steady state.
- The cluster cannot meet the documented service recovery objective through normal controller reconciliation.

Classify the event as a single-node failure, worker-pool failure, control-plane impairment, or total cluster loss before choosing recovery scope.

## Immediate response

1. Declare an incident and freeze deployments, chaos tests, load tests, and infrastructure changes.
2. Preserve cloud events, Kubernetes events, audit logs, node diagnostics, and volume state.
3. For one failed node, cordon and drain only when storage and disruption policy make that safe; never delete a node merely to clear an alert.
4. For cluster loss, protect DNS, database, backups, container images, configuration, and secrets from uncoordinated changes.
5. Confirm the latest validated database backup and immutable infrastructure revision.

## Recovery steps

### Node failure

1. Allow the managed node group and Kubernetes controllers to replace the failed node.
2. Confirm persistent volumes attach only once and pods reschedule across healthy zones.
3. Restore minimum API replicas before reopening normal traffic.

### Cluster loss

1. Provision a clean replacement cluster from the approved Terraform revision.
2. Configure identity, networking, ingress, storage classes, secrets integration, monitoring, and the Litmus-free production namespace.
3. Deploy the signed application image with the approved Helm values.
4. Restore PostgreSQL into an isolated target if the managed database did not survive.
5. Validate internally, then shift traffic gradually using the approved DNS or load-balancer procedure.

## Validation

- Desired nodes and API replicas are ready across failure domains.
- Probes, ingress, DNS, HPA, NetworkPolicy, persistent storage, metrics, tracing, and audit persistence operate normally.
- Authentication, workflow execution, SSE streaming, and audit ordering pass synthetic checks.
- No volume is attached to conflicting writers and no stale cluster still receives production traffic.

## Rollback

For node recovery, stop rescheduling changes and return to the prior healthy capacity plan. For cluster replacement, halt traffic shifting and return DNS or load-balancer weights to the last verified cluster if it is safe. Preserve the failed replacement for analysis; do not destroy the only recoverable cluster or volume.

## Communication checklist

- Failure classification, affected zones/nodes, and service impact
- Incident roles, infrastructure and database owners, and vendor case numbers
- RTO countdown, replacement-cluster milestones, and traffic-shift approvals
- Data recovery point and any suspected inconsistency
- Customer, executive, security, legal, and support updates
- Final topology, residual risk, cost impact, and post-incident actions

