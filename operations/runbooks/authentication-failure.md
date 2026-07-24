# Authentication failure runbook

## Symptoms

- Valid synthetic login fails, `auth_failures_total` rises, or protected endpoints return unexpected 401 responses.
- JWT verification reports expiration, signature, algorithm, or malformed-token errors across unrelated users.
- Public health/version remain available while workflow endpoints are inaccessible.

## Diagnosis

Separate expected invalid-credential traffic from failures using the controlled synthetic identity. Check JWT secret availability, algorithm and expiration settings, clock skew, secret rotation timing, pod configuration consistency, bcrypt verification health, recent deployments, and whether only one replica or all replicas fail.

## Dashboards

- Autonomous AI Company – Overview
- Authentication PromQL panel or query view; no dedicated authentication dashboard currently exists
- Kubernetes configuration, secret delivery, and pod restart dashboards

## Metrics

- `autonomous_ai_company_auth_login_total{status="success"}`
- `autonomous_ai_company_auth_login_total{status="failure"}`
- `autonomous_ai_company_auth_failures_total`
- `autonomous_ai_company_http_requests_total{status="401"}` as aggregate diagnostic only

## Logs

Inspect sanitized authentication failure types, secret-mount/configuration errors, pod startup logs, and trace exceptions. Never log submitted passwords, JWTs, secret values, or full Authorization headers. Repeated invalid usernames are a security signal and may require abuse response rather than reliability rollback.

## Recovery

Restore consistent secret and JWT configuration across replicas. Complete an approved dual-key or coordinated rotation when applicable, correct clock synchronization, and replace only pods with stale configuration. If compromise is suspected, follow security incident response before issuing new trust.

## Escalation

Declare SEV-1 when all valid production identities are blocked or signing trust is compromised. Use SEV-2 for material partial failure. Page service, platform, and security owners; involve customer support when users are affected.

## Rollback

Roll back the responsible secret/configuration or deployment change through the approved rotation procedure. Do not restore a known-compromised key. Avoid ad hoc test bypasses or disabling authentication.

## Verification

Verify public endpoints remain public, valid login returns a bearer token, invalid login remains 401, expired/malformed/invalid-signature tokens remain rejected, protected workflow and SSE requests succeed, replicas share the intended configuration, and synthetic authentication burn returns to normal.

