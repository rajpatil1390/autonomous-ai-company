# High latency runbook

## Symptoms

- HTTP, workflow, agent, or LLM P95/P99 exceeds its objective.
- Active workflows or provider requests accumulate while throughput falls.
- Timeouts and retries rise without a complete outage.

## Diagnosis

Identify the first layer whose latency changed: ingress/API, graph workflow, specialist agent, LLM provider, audit database, or network. Compare request rate, concurrency, CPU throttling, memory pressure, HPA activity, PostgreSQL connections, provider/model latency, retries, and recent deployments. Confirm the load generator is not the bottleneck during a test.

## Dashboards

- Autonomous AI Company – Overview
- Autonomous AI Company – Workflow
- Autonomous AI Company – Agents
- Autonomous AI Company – LLM
- Autonomous AI Company – Audit

## Metrics

- `autonomous_ai_company_http_request_duration_seconds_bucket`
- `autonomous_ai_company_workflow_duration_seconds_bucket`
- `autonomous_ai_company_agent_duration_seconds_bucket`
- `autonomous_ai_company_llm_latency_seconds_bucket`
- `autonomous_ai_company_agent_retry_total`
- `autonomous_ai_company_workflow_active`

## Logs

Use trace IDs to correlate API, workflow, agent, provider, audit, and database spans. Inspect timeout types, retry decisions, connection-pool waits, throttling, OOM events, and provider response metadata. Do not log raw prompts or generated text.

## Recovery

Reduce or shed nonessential load through approved controls, restore healthy capacity within dependency quotas, and address the first saturated layer. Roll back a latency regression, recover PostgreSQL connectivity, or engage the provider as evidence requires. Avoid indiscriminate retries, which amplify queueing.

## Escalation

Page as SEV-1 when latency makes the service effectively unavailable or rapidly consumes the availability budget. Use SEV-2 for sustained SLO breach with partial service. Escalate to platform, database, AI-provider, or network owners according to the first degraded layer.

## Rollback

Revert the smallest confirmed configuration, deployment, model, or routing change. Restore previous HPA values only when the change caused instability and previous capacity is safe. Never mask latency by weakening thresholds during an incident.

## Verification

Confirm P50/P95/P99, error rate, retry rate, queue depth proxy, active workflows, provider latency, database health, and pod resources return to the pre-incident envelope under representative traffic. Verify error-budget burn has fallen below one.

