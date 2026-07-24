# Troubleshooting

Start with the smallest failing boundary: request validation, configuration,
provider, graph, audit storage, or deployment. Preserve original exceptions and
collect safe identifiers, timestamps, metric labels, and trace context—never
copy credentials, raw prompts, generated text, or customer data.

## Application will not start

**Symptoms:** Uvicorn exits, `/health` is unavailable, or configuration errors
appear immediately.

**Checks:**

1. Use Python 3.12.
2. Confirm `ANTHROPIC_API_KEY`, `MODEL_NAME`, `TEMPERATURE`, `MAX_TOKENS`, and
   `LOG_LEVEL` are present.
3. If PostgreSQL is enabled, supply all five PostgreSQL settings.
4. If MLflow is enabled, set `MLFLOW_TRACKING_URI`.
5. If OTLP tracing is enabled, set `OTEL_OTLP_ENDPOINT`.
6. Ensure `JWT_SECRET_KEY` is at least 32 characters before login.

Do not print secret values while checking their presence.

## Login returns `401`

- For local demonstration, use the documented demo credentials exactly.
- Confirm the token is passed as `Authorization: Bearer <token>`.
- Obtain a new token if it expired or the signing key changed.
- Check clock synchronization between token issuer and API host.
- Production systems should diagnose the external identity provider, not depend
  on the demo account.

## Workflow returns `400` or `422`

- `422` means the strict HTTP request model rejected a missing, extra, or
  incorrectly typed field.
- `400` means deterministic tools rejected dataset content or an undefined
  metric.
- Supply `dataset`, `previous_dataset`, and `data_scientist_series` explicitly.
- Verify required finance and marketing columns, non-negative financial values,
  and bounded context/question lengths.

Use the OpenAPI schema at `/openapi.json` and the request in [api.md](api.md).

## Workflow returns `503`

The provider-neutral LLM boundary failed. Check provider availability, model
name, credential validity, timeout, outbound DNS/TLS, quota, and rate limits.
Review safe LLM latency/request metrics and trace exception events. Do not add
automatic retries to `ClaudeClient`; agents intentionally own one validation
correction retry, while provider operational retries require a separately
reviewed policy.

## Workflow returns `500`

Use the run ID, UTC timestamp, trace, safe audit events, and server logs to
locate the primary exception. The HTTP response intentionally hides internals.
If audit logging also failed, confirm the primary exception remains visible and
inspect its chained audit failure without recursively logging the backend.

## SSE stream stops or buffers

- Use a client that disables response buffering, such as `curl --no-buffer`.
- Confirm proxies disable buffering and permit long-lived HTTP responses.
- Expect heartbeats approximately every 15 seconds while waiting.
- A client disconnect cancels the request-scoped graph by design.
- There is no background workflow registry; reconnecting starts a new request.

Follow [workflow-failure.md](../operations/runbooks/workflow-failure.md) when
the terminal event is `workflow_failed`.

## `/metrics` returns `404`

This is expected when `METRICS_ENABLED=false`. Enable metrics before creating
the application, then restart it. Confirm Prometheus scrapes `/metrics` and the
namespace is `autonomous_ai_company`. Do not expose metrics publicly without
network controls.

## PostgreSQL audit failures

- Confirm the database is reachable and `audit_events` was initialized from
  `schema.sql`.
- Check credentials through secret presence and connection errors without
  printing passwords.
- Inspect connection limits, storage, locks, TLS, and network policy.
- Remember that initialization scripts do not rerun for an existing Compose
  volume.

Use [database-unavailable.md](../operations/runbooks/database-unavailable.md).
Audit failure must not mask a workflow's primary exception.

## No MLflow runs or traces

- MLflow: set `MLFLOW_ENABLED=true` and a valid tracking URI.
- Tracing: set `OTEL_ENABLED=true`; use `console` or configure the `otlp`
  endpoint.
- Confirm the deployment injected the intended settings before composition.
- Null adapters deliberately produce no external telemetry when disabled.

## Grafana panels show no data

- Confirm the API metrics endpoint is enabled and Prometheus target is healthy.
- Use the default namespace/subsystem expected by supplied dashboards.
- Generate traffic and choose a time range containing it.
- Workflow Starts and Audit Latency panels are intentionally informational
  placeholders because those metrics do not exist yet.

## Kubernetes pods are not ready

- Inspect startup, readiness, and liveness probe failures separately.
- Confirm secret and ConfigMap references exist in the namespace.
- Check image pull authorization, non-root filesystem permissions, resource
  pressure, provider egress, and PostgreSQL reachability.
- Use `helm upgrade --install --atomic --wait`; failed releases should roll back
  according to [deployment.md](deployment.md).

## Tests fail

Run:

```bash
ruff check .
ruff format --check .
pytest -x -vv
coverage report
```

The real PostgreSQL test may skip when neither Docker nor `POSTGRES_TEST_DSN` is
available. A skip must not be reported as successful PostgreSQL verification.

## Getting additional help

For operational impact, choose the matching runbook under
`operations/runbooks/` and follow the escalation policy. For a reproducible
non-security defect, use the bug template. Report vulnerabilities privately
through [SECURITY_CONTACT.md](../SECURITY_CONTACT.md).
