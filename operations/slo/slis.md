# Service level indicators

## Principles

An SLI is the measured ratio or distribution used to evaluate an SLO. Metrics are prefixed with `autonomous_ai_company_` under the default namespace. Queries below are reference PromQL and must be evaluated over the same approved window with sufficient traffic.

## API availability SLI

Good events are HTTP responses whose `status` does not begin with `5`; total events are all HTTP responses.

```promql
1 - (
  sum(rate(autonomous_ai_company_http_requests_total{status=~"5.."}[30d]))
  /
  sum(rate(autonomous_ai_company_http_requests_total[30d]))
)
```

Limitation: no path label exists, so this is aggregate HTTP availability. Evaluate external `/health`, `/version`, and authenticated workflow probes alongside it.

## Workflow success SLI

The current provisional ratio is:

```promql
sum(rate(autonomous_ai_company_workflow_runs_total{workflow="company",status="success"}[30d]))
/
sum(rate(autonomous_ai_company_workflow_runs_total{workflow="company"}[30d]))
```

Limitation: this transport-level outcome can classify HTTP 4xx as success. Exact SLO enforcement requires a future valid-terminal-result signal or an external synthetic workflow check. Record this SLI as provisional.

## Authentication SLI

Use a synthetic client with known-valid credentials and calculate successful `200` logins divided by its attempts. Existing aggregate diagnostics are:

```promql
sum(rate(autonomous_ai_company_auth_login_total{status="success"}[30d]))
/
sum(rate(autonomous_ai_company_auth_login_total[30d]))
```

Limitation: the aggregate includes user-caused invalid credentials and must not replace the valid synthetic SLI.

## Audit persistence SLI

Good events are successful persisted audit events. Bad events are storage attempts counted by `audit_failures_total`.

```promql
sum(rate(autonomous_ai_company_audit_events_total{status="success"}[30d]))
/
(
  sum(rate(autonomous_ai_company_audit_events_total{status="success"}[30d]))
  +
  sum(rate(autonomous_ai_company_audit_failures_total[30d]))
)
```

Correlate this ratio with PostgreSQL health and append-only integrity checks; a missing instrumentation path must be treated as unknown, not success.

## LLM latency SLI

The diagnostic P95 by provider and model is:

```promql
histogram_quantile(
  0.95,
  sum by (le, provider, model) (
    rate(autonomous_ai_company_llm_latency_seconds_bucket[5m])
  )
)
```

The SLO evaluates the share completed below five seconds. Use the `le="5.0"` bucket divided by the histogram count when that bucket exists in the deployed registry. If bucket boundaries differ, update the query or record the SLI unavailable rather than estimating.

## Streaming reliability SLI

An external synthetic probe sends a valid authenticated request to `/workflow/stream` and records a good event only when the response contains `workflow_started` followed by exactly one terminal event within 60 seconds.

Current Prometheus metrics do not distinguish `/workflow/run` from `/workflow/stream` and do not count terminal SSE events. No exact PromQL is claimed. Use aggregate workflow duration, failures, and active-workflow metrics only for diagnosis.

## Data quality

- Treat zero total events as `no data`, never 100% success.
- Alert on missing scrapes and absent synthetic results separately.
- Keep one window, label policy, and inclusion rule across numerator and denominator.
- Do not add high-cardinality IDs or sensitive values to repair an SLI.
- Record query revisions and backfill limitations in the monthly review.

