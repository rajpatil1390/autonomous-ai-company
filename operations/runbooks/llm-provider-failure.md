# LLM provider failure runbook

## Symptoms

- Provider-neutral timeout, rate-limit, or unavailable errors rise.
- `llm_requests_total` failures increase by provider/model, latency grows, or workflows fail across specialist agents.
- Deterministic tools continue succeeding while generated agent outputs stop.

## Diagnosis

Break down failures by agent, provider, model, status, region, and deployment revision using only low-cardinality labels. Check provider status, quota, rate limits, authentication validity, network egress, DNS, timeout propagation, cancellation, token counts, latency, and retry behavior. Confirm schema-correction retry is not being confused with provider retry.

## Dashboards

- Autonomous AI Company – LLM
- Autonomous AI Company – Agents
- Autonomous AI Company – Workflow
- Autonomous AI Company – Overview

## Metrics

- `autonomous_ai_company_llm_requests_total`
- `autonomous_ai_company_llm_latency_seconds_bucket`
- `autonomous_ai_company_llm_tokens_total`
- `autonomous_ai_company_agent_failures_total`
- `autonomous_ai_company_agent_retry_total`
- `autonomous_ai_company_workflow_failures_total`

## Logs

Inspect provider-neutral exception type and chained adapter cause, request ID, model, stop reason, token telemetry, and trace duration. Never log API keys, raw prompts, messages, generated text, or SDK response objects.

## Recovery

Respect provider rate limits and stop retry storms. Restore credentials or egress when they are the confirmed cause. If a separately approved provider or model failover exists, activate it through configuration and dependency composition; do not improvise provider-specific code during the incident. Communicate degraded workflow availability.

## Escalation

Declare SEV-1 when all workflows are unavailable and no approved fallback exists. Use SEV-2 for one provider/model or material latency degradation. Page AI platform and service owners, then provider support with sanitized request identifiers and timestamps.

## Rollback

Revert the responsible model, provider configuration, timeout, or release change. Do not weaken output validation or bypass deterministic-tool boundaries to restore traffic. Revoke and rotate exposed credentials through the approved security process.

## Verification

Run one workflow through each specialist, report, and CEO stage using the intended provider. Confirm valid GenerationResult telemetry, schema validation, cancellation, timeout propagation, normal latency, no retry amplification, audit events, and falling workflow error-budget burn.

