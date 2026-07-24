# Controlled chaos workflow

## Objective

Run exactly one approved experiment against one explicitly annotated API pod while maintaining a measurable steady state. Never combine experiments during the first execution of a scenario.

## Preconditions

- Written change approval identifies the environment, owner, start time, maximum duration, and rollback decision-maker.
- The Litmus operator, required `ChaosExperiment`, and least-privilege `litmus-chaos-runner` service account already exist in `autonomous-ai-company`.
- At least two ready API replicas are serving traffic and the HPA reports healthy metrics.
- Grafana, Prometheus, Kubernetes events, application logs, audit storage, and database health are visible to the operators.
- A recent backup exists when the scenario can affect database connectivity.
- No deployment, migration, incident, or unrelated load test overlaps the window.

## Steady-state checks

Record a ten-minute baseline for health availability, workflow success rate, HTTP P95, active replicas, restarts, agent failures, audit failures, PostgreSQL connections, and provider errors. Run a small authenticated workflow and retain its run identifier for post-test audit verification.

## Opt-in execution procedure

1. Choose one manifest and confirm `spec.engineState: stop` and `spec.annotationCheck: "true"`.
2. Resolve one healthy API pod by the committed application and component labels.
3. Annotate only that pod with `litmuschaos.io/chaos=true` and record its name and UID.
4. Apply the stopped definition to the approved namespace.
5. Re-read the live ChaosEngine, selector, duration, destination, and blast-radius values.
6. With the rollback operator present, explicitly change only that live engine to `active`.
7. Observe the experiment continuously; do not start another experiment.
8. Stop immediately when a failure criterion is met.
9. Follow [rollback.md](rollback.md), then complete [recovery.md](recovery.md).

The GitHub workflow validates and archives definitions only. It never performs steps 2–9.

## Expected results

- Pod deletion: service stays available, Kubernetes restores two ready replicas, and retained data remains consistent.
- CPU saturation: latency remains inside the approved game-day limit, HPA reacts, and resource usage returns to baseline.
- Memory pressure: kubelet recovers an OOM-affected container or pod, unaffected requests continue, and workflows and audit events remain consistent.
- PostgreSQL delay: bounded database timeouts do not block unrelated request handling and audit failures do not replace primary errors.
- PostgreSQL loss: calls requiring persistent audit storage fail predictably, the API remains observable, and normal behavior returns after connectivity restoration.

## Failure criteria

Abort when any approved limit is crossed, including complete service unavailability, more than one application pod affected, unexpected namespace impact, persistent data inconsistency, uncontrolled restart loops, audit mutation or loss, HPA growth beyond the approved replica budget, database impact outside the target, or inability to stop the experiment.

## Evidence

Retain the approved manifest digest, live engine YAML, target pod UID, ChaosResult, experiment and helper logs, Kubernetes events, dashboard snapshots, workflow and audit identifiers, timestamps, rollback actions, recovery measurements, and the final go/no-go decision.

