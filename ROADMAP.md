* [ ] 

# Roadmap

The roadmap communicates direction, not a delivery promise. Priorities may
change after security reviews, SLO performance, user research, and operational
evidence. Released behavior is documented in [CHANGELOG.md](CHANGELOG.md).

## Version 1.0 — Production foundation

- Deterministic specialist tools and five validated agents.
- Parallel LangGraph specialists with conditional degradation handling.
- FastAPI, JWT demonstration authentication, SSE, and optional persistence.
- Audit, metrics, traces, MLflow, dashboards, SLOs, and operational runbooks.
- Container, Kubernetes, Helm, Terraform/AWS, CI/CD, security, performance,
  chaos, and disaster-recovery assets.

## Version 1.1 — Identity and reliability

- Replace the demonstration user with OpenID Connect and external identity.
- Add authorization roles at the API boundary without changing agents.
- Instrument exact valid workflow completions, SSE reliability, workflow
  starts, and audit persistence latency.
- Add reviewed Prometheus burn-rate alert rules and real Alertmanager receivers
  through secret-managed deployment configuration.
- Add durable LangGraph checkpoint storage and resume/replay operations.

## Version 1.2 — Evaluation and provider breadth

- Add provider adapters through the existing `LLMProvider` contract.
- Establish offline evaluation datasets and quality gates without logging raw
  sensitive prompts.
- Add cost policy, model selection policy, and provider failover routing.
- Connect approved model-registry workflows behind tracking interfaces.

## Version 2.0 — Governed autonomous operations

- Human approval boundaries for consequential external actions.
- Durable workflow scheduling and background execution.
- Multi-region recovery proven against documented RTO and RPO targets.
- Tenant isolation, policy-based authorization, and compliance evidence.

## Explicitly not promised

Dates, cloud-provider commitments, autonomous write actions, and production
performance figures are intentionally absent until validated by evidence and
approved governance.
