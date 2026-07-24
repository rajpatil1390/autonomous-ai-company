# Chaos rollback runbook

## Immediate stop

The rollback operator owns this procedure and must remain available for the entire experiment.

1. Patch the live ChaosEngine to `spec.engineState: stop` in `autonomous-ai-company`.
2. Confirm the experiment and helper jobs terminate and no new chaos injection occurs.
3. Remove `litmuschaos.io/chaos` from the explicitly targeted pod.
4. Confirm traffic-control, stress, and packet-loss processes are gone from the target.
5. Retain the ChaosResult and logs before removing temporary experiment resources.

Example commands are intentionally parameterized. Review the resolved variables before execution:

```bash
kubectl --namespace "${CHAOS_NAMESPACE}" patch chaosengine "${CHAOS_ENGINE}" \
  --type merge --patch '{"spec":{"engineState":"stop"}}'
kubectl --namespace "${CHAOS_NAMESPACE}" annotate pod "${TARGET_POD}" \
  litmuschaos.io/chaos-
kubectl --namespace "${CHAOS_NAMESPACE}" get chaosengine,chaosresult,jobs,pods
```

`CHAOS_NAMESPACE`, `CHAOS_ENGINE`, and `TARGET_POD` must be set from the approved change record. Never use an empty variable or a broad selector in rollback commands.

## Experiment-specific rollback

- Pod deletion: wait for the Deployment to restore the configured replica count; do not manually create replacement pods.
- CPU or memory pressure: verify the stress helper is gone. If a pod remains unhealthy after the injection ends, preserve diagnostics before allowing its controller to replace it.
- Network delay or database loss: verify the Litmus network helper removed its `tc`/netem rules. If impaired traffic remains, stop the helper, preserve its logs, and replace only the annotated API pod through the Deployment controller.
- PostgreSQL: restore the approved database route or service independently of Litmus, then verify connection health before admitting normal traffic.

## Rollback failure criteria

Escalate to incident response if the engine will not stop, helper jobs remain active, network rules persist, more pods become affected, the database does not recover, or service health does not improve within the approved recovery objective.

## Completion

Rollback is not complete until the engine is stopped, the target annotation is removed, the injected fault is absent, desired replicas are ready, and the recovery runbook has passed.

