# Recovery validation runbook

## Purpose

Prove that removing the fault restored service, workflow, persistence, and observability. A green health endpoint alone is insufficient.

## Kubernetes recovery

- The API Deployment has its desired replica count available and ready.
- No application or Litmus helper pod remains in a crash loop.
- Restart counts stop increasing after the expected recovery event.
- Readiness, liveness, and startup probes pass.
- HPA replicas and CPU/memory utilization return toward the recorded baseline within the approved stabilization window.
- No target pod retains `litmuschaos.io/chaos=true`.

## Application recovery

1. Verify `/health` and `/version` from outside the cluster routing path.
2. Authenticate with the approved synthetic test identity.
3. Execute one controlled workflow and one SSE workflow.
4. Confirm both produce valid terminal results without unexpected retries or duplicate agent execution.
5. Confirm latency and error rates return to the pre-test envelope.

## Data and audit recovery

- PostgreSQL accepts new connections and reports no unexpected recovery or corruption warnings.
- The pre-test and post-test audit runs are readable in timestamp order.
- Audit history remains append-only; no stored event changed or disappeared.
- The primary exception remains visible for any failed workflow and any audit failure is separately observable.
- No duplicate completion event, partial workflow state, or fabricated specialist output exists.

## Observability recovery

Prometheus resumes scraping every expected pod. Grafana shows the fault interval, recovery transition, and stable post-test period. Review HTTP, workflow, agent, LLM, audit, PostgreSQL, replica, restart, CPU, and memory signals together.

## Success criteria

Recovery succeeds only when every Kubernetes, application, data, audit, and observability check passes for the agreed observation period. Compare the measured recovery time with the approved recovery-time objective.

## Failure criteria

Open an incident and halt further chaos work if health flaps, error or latency signals remain elevated, replicas fail to stabilize, database consistency is uncertain, audit history differs from its pre-test snapshot, or the recovery objective is missed.

