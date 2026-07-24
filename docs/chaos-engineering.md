# Chaos engineering guide

## Scope

The committed ChaosEngine definitions test five bounded failure modes around the existing API deployment. They are infrastructure assets and do not modify application behavior, graph execution, persistence code, or business logic.

Every definition is inert by default:

- `spec.engineState` is `stop`;
- `spec.annotationCheck` is `"true"`;
- the selector is restricted to API pods in `autonomous-ai-company`;
- one of two API replicas is targeted through `PODS_AFFECTED_PERC: "50"`;
- every duration and destination is explicit; and
- evidence is retained with `jobCleanUpPolicy: retain`.

Applying a definition is not authorization to run it. Activation requires a separate approved change, one explicitly annotated target pod, a named rollback operator, and continuous observation.

## Prerequisites

- An approved environment and game-day window with no concurrent deployment, migration, incident, or heavy load test.
- Litmus Chaos Operator and the required `ChaosExperiment` resources installed from a reviewed, pinned release.
- A namespaced `litmus-chaos-runner` service account with only the permissions required by the selected experiment.
- Two healthy API replicas, functioning probes, Metrics Server, and a healthy HPA.
- Prometheus and Grafana access for application, Kubernetes, database, and resource signals.
- Access to Kubernetes events, Litmus results, experiment logs, application logs, and PostgreSQL health.
- Synthetic authentication credentials supplied out of band; credentials never belong in these assets.
- A verified database backup and database owner for PostgreSQL-related scenarios.
- Defined steady-state objectives, abort limits, recovery-time objective, communication channel, incident commander, and rollback operator.

Confirm the cluster runtime, socket path, network interface, destination DNS, and installed Litmus experiment definitions before activation. The committed PostgreSQL destination is the existing in-cluster service name. An environment using RDS or another external database requires a separately reviewed destination value for that run.

## Experiment catalog

| Definition | Litmus experiment | Fault | Maximum initial blast radius |
|---|---|---|---|
| `pod-delete.yaml` | `pod-delete` | Gracefully deletes one API pod | One of two API replicas for 30 seconds |
| `cpu-hog.yaml` | `pod-cpu-hog` | Consumes two CPU cores | One API pod for 60 seconds |
| `memory-hog.yaml` | `pod-memory-hog` | Consumes 1,800 MB | One API pod for 60 seconds |
| `network-delay.yaml` | `pod-network-latency` | Adds 500 ms ±100 ms to PostgreSQL egress | One API pod, PostgreSQL DNS and port 5432 only |
| `database-loss.yaml` | `pod-network-loss` | Drops PostgreSQL egress packets | One API pod, PostgreSQL DNS and port 5432 for 45 seconds |

The database scenario never deletes PostgreSQL resources. It creates a reversible loss of connectivity from one API pod.

## Opt-in execution

Use [the controlled workflow](../chaos/scenarios/workflow.md) for the full approval and evidence sequence. At a high level:

1. Record the steady state and confirm rollback authority.
2. Review the exact manifest and calculate its effective blast radius.
3. Annotate one chosen healthy API pod with `litmuschaos.io/chaos=true`.
4. Apply the definition while it remains stopped.
5. Inspect the live ChaosEngine and obtain a final go/no-go decision.
6. Explicitly activate only that live engine.
7. Observe continuously and stop on the first failure criterion.
8. Execute the rollback and recovery runbooks.

Never activate from GitHub Actions. The committed workflow parses, validates, and archives definitions only; it contains no `kubectl`, Litmus execution, cluster credentials, or production environment.

## Expected results and failure criteria

### API pod failure

Expected: the Service stays available, the Deployment recreates the pod, readiness protects traffic, and persisted data remains unchanged.

Fail: complete outage, more than one application pod affected, replacement never becomes ready, or any workflow/audit corruption.

### CPU saturation

Expected: latency rises only within the approved game-day limit, HPA adds capacity when metrics warrant it, and latency and replica count recover after the stress ends.

Fail: sustained unavailability, runaway scaling, node-wide impact, provider overload, or missed recovery objective.

### Memory pressure

Expected: the limited pod may be OOM-killed and recovered by Kubernetes while the other replica serves traffic; audit and workflow state remain consistent.

Fail: multiple pods or nodes affected, restart loop persists, data is inconsistent, or recovery exceeds the objective.

### PostgreSQL network delay

Expected: database operations respect bounded timeouts, audit failures remain isolated from primary failures, and unrelated API behavior remains responsive.

Fail: indefinite request hangs, primary exceptions are masked, network shaping affects any unapproved destination, or audit history mutates.

### PostgreSQL outage

Expected: database-dependent operations fail explicitly and gracefully, observability remains available, and writes resume in order after connectivity returns.

Fail: database mutation, silent audit loss, application-wide deadlock, impact outside the selected pod, or failed database recovery.

## Rollback

Follow [the rollback runbook](../chaos/scenarios/rollback.md). Stop the engine first, remove the opt-in pod annotation, verify Litmus helper processes and network rules are gone, preserve evidence, and allow Kubernetes controllers to restore the desired state.

Rollback is incomplete until the fault is absent and the recovery validation passes. If the engine or helper cannot be stopped, immediately enter incident response rather than improvising additional chaos commands.

## Recovery validation

Follow [the recovery runbook](../chaos/scenarios/recovery.md). Validate Kubernetes health, authenticated workflow execution, SSE completion, PostgreSQL connectivity, ordered append-only audit history, metrics collection, and stable behavior for the agreed observation period.

The prolonged database scenario has an additional [disaster runbook](../chaos/scenarios/disaster.md). Do not combine it with other chaos or load profiles.

## Observability

Prometheus provides time-series evidence for HTTP requests, workflow duration and failures, agent duration and failures, retries, LLM latency and tokens, audit events and failures, pod CPU/memory, HPA replicas, restarts, and probe health. Grafana overlays these signals to show fault onset, propagation, scaling, and recovery.

Record the test's UTC start, injection, stop, and recovery timestamps so dashboard evidence can be aligned without adding high-cardinality test labels to application metrics.

## Relationship to load testing

Load testing asks how the platform behaves under controlled demand. Chaos engineering asks how it behaves when a dependency or resource fails. Run a small, approved steady workload during a chaos game day only after each asset has passed independently. This reveals whether redundancy, timeouts, and autoscaling continue working under failure without confusing saturation with fault injection.

## Improving Kubernetes configuration

Results should drive measured changes rather than guesses:

- pod deletion validates replica count, readiness, termination grace, and the need for a PodDisruptionBudget;
- CPU and memory experiments tune requests, limits, HPA targets, scale-up policy, and stabilization windows;
- OOM behavior validates probe thresholds and restart recovery;
- network faults validate connection, request, and shutdown timeouts; and
- database loss validates connection-pool limits, retry boundaries, NetworkPolicy assumptions, and recovery procedures.

Repeat the same scenario after a configuration change and compare steady state, impact, and recovery time. Do not widen blast radius until the smaller experiment passes reliably.

## Evidence and review

Archive the exact manifest digest, approval, target pod UID, ChaosEngine, ChaosResult, experiment logs, Kubernetes events, dashboard snapshots, application/audit identifiers, failure observations, rollback steps, measured recovery time, and follow-up actions. Remove credentials and sensitive payloads before sharing evidence.

