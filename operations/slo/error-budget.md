# Error-budget policy

## Definition

An error budget is the allowed amount of unsuccessful service behavior implied by an SLO. For a target `T`, the budget fraction is `1 - T`. Budget consumed is `bad events / allowed bad events` over the same rolling 30-day window.

Examples:

- 99.9% API availability permits 0.1% failure, approximately 43 minutes 49 seconds of equivalent unavailability in 30 days.
- 99.0% workflow or streaming reliability permits 1% unsuccessful valid attempts.
- 99.99% audit persistence permits 0.01% failed persistence attempts.
- 95% LLM latency compliance permits 5% of completed generations above five seconds.

## Release policy

| Remaining budget | Operating policy |
|---:|---|
| More than 50% | Normal reviewed releases and reliability work |
| 25–50% | Increase review, reduce risky change size, prioritize active reliability risks |
| 1–25% | Freeze discretionary risk; ship reliability, security, and required recovery changes only |
| Exhausted | Stop normal releases; incident review and service-owner exception required |

Security fixes may proceed when delay creates greater risk, but they require an explicit rollback plan and incident commander or service-owner approval. Budget policy never justifies hiding failures or weakening an SLO.

## Burn rate

Burn rate compares observed bad-event rate with the allowed rate. A burn rate of `1` consumes exactly one 30-day budget per 30 days; `14.4` exhausts it in roughly two days.

Recommended future alert-rule policy:

- Page: 14.4× burn sustained across 5-minute and 1-hour windows.
- Page: 6× burn sustained across 30-minute and 6-hour windows.
- Ticket: 3× burn sustained across 2-hour and 1-day windows.
- Review: 1× burn over 3 days.

This repository does not create Prometheus alert rules in this step. Alert rules must be added separately and validated against real traffic before paging.

## Decision process

SRE publishes budget state weekly. Service, platform, database, security, and AI-provider owners review contributing events. The service owner decides release posture using remaining budget, current burn, incident severity, rollback readiness, and business risk. Every exception records owner, scope, expiration, mitigation, and verification.

## Reset and review

Rolling windows do not provide a calendar reset that erases incidents. Review monthly, update targets quarterly, and revisit the policy after material architecture changes, major incidents, or persistent missing data.

