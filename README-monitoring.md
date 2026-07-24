# Autonomous AI Company Monitoring

This stack runs Prometheus and Grafana as infrastructure alongside an already
running Autonomous AI Company API. It does not modify or start the application.
Grafana reads time-series data from Prometheus, and Prometheus scrapes the
existing unauthenticated `GET /metrics` endpoint.

## Prerequisites

- Run the API on host port `8000` with `METRICS_ENABLED=true`.
- Keep `METRICS_NAMESPACE=autonomous_ai_company` and
  `METRICS_SUBSYSTEM` empty for the supplied dashboard queries.
- Install Docker with Compose support only when running the stack. Static tests
  do not require Docker, a Prometheus server, Grafana, or network access.

The Prometheus container reaches the host API through
`host.docker.internal:8000`. The Compose `host-gateway` mapping provides the
same hostname on supported Linux Docker installations.

## Start and stop monitoring

Set a non-default Grafana administrator password, then start the two monitoring
services:

```powershell
$env:GRAFANA_ADMIN_PASSWORD = "replace-with-a-strong-password"
docker compose -f docker-compose.monitoring.yml up -d
```

Open:

- Grafana: <http://localhost:3000>
- Prometheus: <http://localhost:9090>
- Prometheus target health: <http://localhost:9090/targets>

Stop the services without deleting retained dashboards and time-series data:

```powershell
docker compose -f docker-compose.monitoring.yml down
```

Add `--volumes` only when the monitoring history should be deleted.

## Automatic provisioning

Grafana loads the default Prometheus datasource from
`monitoring/grafana/provisioning/datasources/datasource.yaml`. Its stable UID is
`prometheus`, which is referenced by every dashboard target.

The dashboard provider watches `/var/lib/grafana/dashboards`, populated by the
read-only dashboard bind mount. Dashboard files are refreshed every 30 seconds,
so no manual import or Grafana UI configuration is required.

Prometheus uses `monitoring/prometheus/prometheus.yml`, scrapes `/metrics` every
15 seconds, and stores data in the `prometheus_data` volume for 15 days.

## Implemented metrics

The supplied dashboards use the default `autonomous_ai_company_` prefix and the
following application metrics:

- HTTP: `http_requests_total`, `http_request_duration_seconds`
- Workflow: `workflow_runs_total`, `workflow_success_total`,
  `workflow_failures_total`, `workflow_duration_seconds`, `workflow_active`
- Agents: `agent_runs_total`, `agent_duration_seconds`, `agent_retry_total`,
  `agent_failures_total`
- LLM: `llm_requests_total`, `llm_latency_seconds`, `llm_tokens_total`
- Audit: `audit_events_total`, `audit_failures_total`
- Authentication: `auth_login_total`, `auth_failures_total`

Prometheus automatically exposes `_bucket`, `_sum`, and `_count` series for the
duration histograms. The P95 and average-duration panels use only those exported
histogram series.

## Placeholder panels

Two panels are deliberately labeled **Metric Unavailable (Not Yet
Instrumented)** and have no PromQL target:

- **Workflow Starts** needs a dedicated counter incremented when workflow
  execution begins, such as `workflow_starts_total`. The existing
  `workflow_runs_total` records completed outcomes and is not used as a proxy.
- **Audit Latency** needs a dedicated audit persistence duration histogram,
  such as `audit_event_duration_seconds`. Audit event counts are not converted
  into latency estimates.

These placeholders avoid fabricated values and will remain empty until future
application instrumentation exports the corresponding measurements.

## Add a dashboard

1. Create a dashboard in Grafana using the provisioned Prometheus datasource.
2. Export it as JSON with a unique `uid` and title.
3. Store the JSON in `monitoring/grafana/dashboards/`.
4. Run `pytest tests/monitoring/test_dashboards.py` to validate it.

Provisioning discovers the new file automatically; restart is normally not
required because the provider checks for updates every 30 seconds.

## Add a metric

Adding a metric is a separate application change. Define a low-cardinality
metric through the existing metrics abstraction, test its exported name, and
then add PromQL panels that reference that name. Prometheus will ingest newly
exported series during its next scrape without changes to Grafana provisioning.

## Production notes and troubleshooting

- Both UIs bind to localhost by default. Put authenticated ingress or a secure
  tunnel in front of them before exposing them remotely.
- The Grafana admin password has no hardcoded default and is required by
  Compose variable interpolation.
- If the Prometheus target is down, confirm the API is reachable on host port
  `8000`, metrics are enabled, and `/metrics` returns HTTP 200.
- If panels show no data, confirm the namespace is
  `autonomous_ai_company`, the subsystem is empty, and select a time range that
  includes application activity.
- If Grafana cannot reach Prometheus, check both service health checks and the
  `http://prometheus:9090` provisioned datasource URL.

Grafana dashboards remain infrastructure assets: the same JSON and provisioning
files can later be mounted through Kubernetes ConfigMaps without changing any
agent, workflow, or API code.
