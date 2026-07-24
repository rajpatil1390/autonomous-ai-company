# API unavailable runbook

## Symptoms

- External `/health` and `/version` probes fail or return 5xx.
- Ingress reports no healthy upstreams, API replicas are unavailable, or HTTP 5xx burn is critical.
- Authentication, workflow, streaming, and metrics requests fail together.

## Diagnosis

Confirm scope from an external probe, then inspect ingress, Service endpoints, ready replicas, pod events, probes, restarts, resource limits, recent deployment changes, node health, DNS, certificates, and dependent PostgreSQL/provider status. Distinguish total API loss from one endpoint or one zone.

## Dashboards

- Autonomous AI Company – Overview
- Autonomous AI Company – Workflow
- Kubernetes workload, ingress, node, and HPA dashboards supplied by the platform

## Metrics

- `autonomous_ai_company_http_requests_total{status=~"5.."}`
- `autonomous_ai_company_http_request_duration_seconds_bucket`
- `autonomous_ai_company_workflow_active`
- Kubernetes ready replicas, restarts, probe failures, CPU, memory, and ingress 5xx

## Logs

Inspect ingress and API logs around the first failed probe, Kubernetes events, container termination reasons, and OpenTelemetry exception traces. Never paste JWTs, passwords, prompts, generated text, or API keys into the incident channel.

## Recovery

Restore a known-good ingress and Service path, ensure at least two ready API replicas, and remove failing pods from traffic through readiness. If a deployment caused the outage, use the approved deployment rollback. If capacity is exhausted, scale within database and provider limits. Follow disaster recovery for cluster or region loss.

## Escalation

Declare SEV-1 when production is unavailable across healthy client locations or recovery is uncertain. Page platform and service owners immediately; add database, network, cloud, or security owners based on evidence. Engage executive and customer communications under the escalation policy.

## Rollback

Roll back only the identified change using the existing atomic Helm history or infrastructure change plan. Do not delete pods, volumes, clusters, or databases to clear symptoms. Stop rollback if health worsens and preserve evidence.

## Verification

Verify external health and version, valid login, workflow run, SSE terminal event, metrics scrape, audit persistence, two ready replicas, normal 5xx rate, and stable latency for the agreed observation period. Close only after the API availability burn stops increasing.

