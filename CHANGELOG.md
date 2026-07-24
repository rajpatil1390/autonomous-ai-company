# Changelog

All notable changes to Autonomous AI Company are documented here. The project
uses [Semantic Versioning](https://semver.org/) and follows the structure of
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.0] - 2026-07-15

### Added

- Deterministic finance, marketing, and data-science calculation tools using
  `Decimal` where financial precision matters.
- Five validated specialist and executive agents with bounded prompts,
  provider-neutral generation results, one correction retry, and safe audit
  telemetry.
- Asynchronous LangGraph orchestration with parallel specialists, a
  deterministic join, conditional error-summary routing, and optional
  checkpoint injection.
- FastAPI health, version, authenticated workflow, SSE workflow, and optional
  Prometheus endpoints.
- JWT authentication for local demonstration, PostgreSQL audit persistence,
  MLflow tracking, OpenTelemetry tracing, and Prometheus metrics behind
  injected interfaces.
- Docker, Kubernetes, Helm, Terraform/AWS, continuous integration, release,
  security, performance, chaos, disaster-recovery, monitoring, and SRE assets.
- Production-facing architecture, API, deployment, development, operations,
  troubleshooting, contribution, security, and governance documentation.

### Security

- Secret-bearing settings use environment variables and validated secret
  types.
- Audit records use event-specific allowlists, deep immutability, and exclude
  raw prompts and generated text by default.
- Release and security workflows define OIDC, image scanning, SBOM generation,
  and keyless signature verification contracts.

### Known limitations

- The built-in `admin` account is for local demonstration only; production
  deployments require an external identity provider.
- MLflow, tracing, metrics, PostgreSQL persistence, and checkpointing are
  optional and disabled unless configured.
- Published load profiles and thresholds are test definitions, not measured
  production benchmark results.
- Dedicated workflow-start, audit-latency, and exact SSE reliability metrics
  are not yet instrumented.
