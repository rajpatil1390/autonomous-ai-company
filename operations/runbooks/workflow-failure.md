# Workflow failure runbook

## Symptoms

- Workflow failure counters or 5xx responses rise, CEO results are absent, or SSE emits `workflow_failed`.
- Specialist branches complete inconsistently, ErrorSummary routing increases, or validation retries fail.
- Individual API health and authentication may remain normal.

## Diagnosis

Trace one run through Finance, Marketing, Data Scientist, Report, and CEO nodes. Identify deterministic tool, prompt, provider, schema validation, audit, routing, checkpoint, or cancellation failures. Verify parallel branch completion and partial-state ownership. Compare recent schema, prompt, model, and dependency changes without inspecting sensitive prompt content.

## Dashboards

- Autonomous AI Company – Workflow
- Autonomous AI Company – Agents
- Autonomous AI Company – LLM
- Autonomous AI Company – Audit
- Autonomous AI Company – Overview

## Metrics

- `autonomous_ai_company_workflow_runs_total`
- `autonomous_ai_company_workflow_failures_total`
- `autonomous_ai_company_workflow_duration_seconds_bucket`
- `autonomous_ai_company_workflow_active`
- `autonomous_ai_company_agent_failures_total`
- `autonomous_ai_company_agent_retry_total`
- `autonomous_ai_company_audit_failures_total`

## Logs

Use workflow traces, node/agent names, provider-neutral errors, validation error types, routing decision, and sanitized audit events. Do not log datasets containing sensitive data, raw prompts, generated text, JWTs, API keys, or unsupported audit metadata.

## Recovery

Resolve the failing boundary: restore deterministic input validity, provider availability, schema compatibility, prompt version, audit storage, or graph dependency. Allow ErrorSummary only for genuinely unavailable sections; never fabricate specialist output. Cancel stuck executions using normal async cancellation.

## Escalation

Declare SEV-1 when all valid workflows fail or return unsafe results. Use SEV-2 for one specialist or a substantial segment. Page service and workflow owners, adding finance/data/marketing, AI provider, database, or platform owners according to the failed boundary.

## Rollback

Revert the smallest confirmed prompt, schema, model, dependency, or release change. Preserve public schemas and audit history. Do not disable validation, correction bounds, audit allowlists, or dependency injection as an emergency shortcut.

## Verification

Run valid workflow and SSE requests, confirm all three parallel specialists complete, Report waits for the join, CEO handles full and allowed partial inputs, one correction retry remains bounded, audit events are ordered, no duplicate node execution occurs, and workflow burn returns below policy thresholds.

