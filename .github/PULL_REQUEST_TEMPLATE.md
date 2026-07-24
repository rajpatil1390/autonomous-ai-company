# Summary

Describe the problem, solution, and deliberately unchanged behavior.

## Change type

- [ ] Feature
- [ ] Fix
- [ ] Refactor
- [ ] Documentation
- [ ] Infrastructure or operations
- [ ] Security

## Architecture

- [ ] Deterministic calculations remain in tools.
- [ ] Provider/database/framework details remain behind adapters.
- [ ] Dependency injection and partial-state ownership are preserved.
- [ ] Public schema, API, or deployment changes are documented.

## Security and privacy

- [ ] No secrets, credentials, production data, raw prompts, generated text, or
      sensitive high-cardinality labels are included.
- [ ] Authentication, authorization, audit, and retention impacts were reviewed.
- [ ] This change is safe to discuss publicly; vulnerabilities use the private
      reporting process.

## Verification

- [ ] `ruff check .`
- [ ] `ruff format --check .`
- [ ] Full pytest suite
- [ ] 100% application statement and branch coverage
- [ ] Package or relevant static infrastructure validation

List commands, results, skipped environment-dependent checks, and manual
verification. Never present an unavailable runtime as a successful check.

## Deployment and rollback

Describe configuration changes, compatibility, rollout, rollback, and
observability. Write `Not applicable` with a reason when appropriate.
