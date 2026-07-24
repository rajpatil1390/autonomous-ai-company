# Operations guide

This guide connects the repository's deployment, observability, reliability,
recovery, and security assets. It does not replace environment-specific change
approval or the detailed runbooks.

## Operating model

Production is intended to run as immutable containers on Kubernetes, installed
through Helm and backed by PostgreSQL. Terraform defines an AWS reference
platform with VPC, EKS, ECR, RDS, IAM, and secret placeholders. GitHub Actions
defines CI, release, security, and manual validation workflows.

Before production use, replace the demonstration identity, review IAM and
network boundaries, configure actual secret-manager references, validate the
provider quota, rehearse rollback, and prove backup restoration.

## Deployment

- [Docker and Compose](../README-docker.md)
- [Production release pipeline](deployment.md)
- [Kubernetes manifests](../k8s/)
- [Helm chart](../helm/autonomous-ai-company/)
- [AWS and Terraform](../cloud/aws/README-aws.md)

Deployments use immutable image tags/digests, non-root containers, probes,
resource limits, rolling updates, and Helm atomic rollback contracts. Static
assets do not prove that a target cluster, account, or secret configuration is
correct; validate them in a controlled environment.

## Observability

All observability adapters are optional and selected by configuration:

- **Prometheus** measures rates, counts, durations, tokens, failures, retries,
  and active workflows using a private application-owned registry.
- **Grafana** consumes existing Prometheus metrics through provisioned
  dashboards; it does not change application behavior.
- **OpenTelemetry** correlates request, workflow, agent, audit, and MLflow spans
  while excluding sensitive content.
- **MLflow** tracks workflow/agent experiment parameters, metrics, tags, and
  approved artifacts through nested runs.

See [README-monitoring.md](../README-monitoring.md). Workflow-start and
audit-latency dashboard panels are explicitly marked unavailable until those
metrics are instrumented.

## SLO and on-call practice

Service objectives and measurement limitations are in
[operations/slo](../operations/slo/). Alertmanager routing and inhibition are
defined in [operations/alertmanager](../operations/alertmanager/), with empty
receivers until an approved deployment injects integrations.

Use the failure-specific [operational runbooks](../operations/runbooks/) and
[on-call templates](../operations/oncall/). Error-budget policy determines
release posture; exhausted budget prioritizes reliability, security, and
recovery changes over discretionary risk.

## Audit persistence

Audit events are append-only, validated, ordered, and deeply immutable.
PostgreSQL is optional; in-memory storage is the disabled-mode fallback and is
not durable across process restarts. Audit failures must not replace primary
application exceptions. Never add raw prompts or responses to audit payloads.

## Security operations

The [security workflow](../.github/workflows/security.yml) statically defines
dependency, source, filesystem, container, semantic, OSV, SBOM, and signature
verification checks. [SECURITY.md](../security/SECURITY.md) defines disclosure
policy. Release/CD uses GitHub OIDC rather than static AWS access keys.

Operational secrets belong in an approved secret manager. Kubernetes example
secrets and Terraform secret ARNs are templates, not secret values.

## Performance and capacity

[Performance assets](../performance/reports/README-performance.md) define k6
and Locust smoke, normal, peak, stress, and spike profiles. Thresholds are
acceptance goals, not measured benchmarks. Begin with smoke, retain reports,
correlate results with Grafana, and tune HPA only from repeated evidence.

## Chaos engineering

[Chaos assets](chaos-engineering.md) are opt-in definitions and must never run
automatically in production. Establish steady-state checks, approvals,
abort conditions, and rollback before pod, CPU, memory, network, or database
experiments. Use metrics and traces to verify recovery rather than assuming it.

## Disaster recovery

[Disaster recovery](disaster-recovery.md) defines RPO/RTO, daily logical backup
intent, retention, encryption adapters, suspended Kubernetes jobs, restore
safety, verification, and exercise cadence. A backup is not trusted until an
isolated restore succeeds. Restoration and destructive actions remain manual.

## Routine checklist

### Daily

- Review critical alerts, provider status, audit persistence, and synthetic
  health/authentication/streaming checks.
- Confirm the latest backup artifact validation status.

### Weekly

- Review error-budget burn, capacity trends, dependency findings, and open
  corrective actions.
- Sample a backup restore into an isolated database.

### Monthly or quarterly

- Reassess SLO measurement quality and dashboard gaps.
- Exercise incident, rollback, cluster recovery, and regional response plans
  according to the documented schedule.
- Rotate or validate credentials and review least-privilege access.

## Escalation

Follow [escalation-policy.md](../operations/oncall/escalation-policy.md). The
incident commander owns severity and coordination; hands-on responders own
bounded actions. Record UTC timelines without secrets or customer content.
