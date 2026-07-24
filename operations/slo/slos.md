# Service level objectives

## Policy

SLOs use rolling 30-day windows unless stated otherwise. They measure user-visible service behavior, not infrastructure uptime alone. Weekly review checks budget burn and data quality; monthly review closes the window; quarterly review reassesses targets and instrumentation.

| Service objective | Target | Measurement | Error budget per 30 days | Review cadence |
|---|---:|---|---:|---|
| API availability | 99.9% | Non-5xx HTTP responses divided by all measured HTTP responses | 0.1%, approximately 43m 49s unavailable | Weekly burn, monthly decision, quarterly target review |
| Workflow success rate | 99.0% | Successfully completed company workflows divided by attempted valid workflows | 1.0% of valid workflow attempts | Weekly burn, monthly decision, quarterly semantics review |
| Authentication reliability | 99.9% | Successful login using a valid synthetic identity divided by valid synthetic attempts | 0.1% of valid attempts | Daily synthetic check, weekly burn, monthly decision |
| Audit persistence | 99.99% | Persisted audit events divided by persistence attempts | 0.01% of audit attempts | Daily review, weekly burn, monthly integrity review |
| LLM latency | 95.0% below 5 seconds | Provider-reported generations completed within 5 seconds divided by completed generations | 5.0% of completed generations may exceed 5 seconds | Daily provider review, weekly burn, monthly target review |
| Streaming reliability | 99.0% | Authenticated SSE workflows that emit start and one terminal event within 60 seconds divided by valid stream attempts | 1.0% of valid stream attempts | Daily synthetic check, weekly burn, monthly decision |

## Measurement qualifications

API availability is currently an aggregate across HTTP paths because the exported HTTP metric deliberately has no path label. It is useful but cannot isolate individual endpoints.

The current workflow metric treats transport outcomes below HTTP 500 as successful, so it is a provisional infrastructure-completion indicator rather than a strict valid-CEO-output SLI. Do not use it alone as a release gate until valid workflow completion is distinguishable.

Authentication counters include invalid user credentials. The objective therefore uses a controlled valid synthetic identity; organic `401` responses are security and product signals, not service unavailability.

No dedicated stream-terminal metric exists. Streaming reliability requires an external synthetic SSE check that verifies `workflow_started` and exactly one of `workflow_completed` or `workflow_failed`. The aggregate workflow counter is diagnostic only for this objective.

## Exclusions

Exclude only approved maintenance windows or invalid measurement intervals documented before review. Never exclude provider failures, database failures, deployment regressions, capacity exhaustion, or incidents merely because another team or vendor contributed.

## Ownership

The service owner owns API, workflow, authentication, and streaming objectives. The platform/database owner owns audit persistence. The AI platform owner owns LLM latency. SRE owns measurement quality, error-budget accounting, review facilitation, and escalation when data is missing.

