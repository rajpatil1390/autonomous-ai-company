# Contributing

Thank you for improving Autonomous AI Company. Contributions should preserve
the boundary between deterministic business calculations, agent reasoning,
workflow orchestration, transport adapters, and infrastructure.

## Before you begin

- Read the [Code of Conduct](CODE_OF_CONDUCT.md) and
  [security reporting policy](SECURITY_CONTACT.md).
- Review the [architecture](docs/architecture.md) and
  [developer guide](docs/developer-guide.md).
- Search existing issues before opening a new bug or feature request.
- Discuss broad architectural changes before implementing them.

## Development setup

Use Python 3.12:

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
python -m pip install "ruff==0.15.20" "pytest-cov>=7,<8" "build>=1.3,<2"
```

Copy `.env.example` to `.env` and replace its example values locally. Never
commit `.env`, credentials, tokens, customer data, raw prompts, or generated
model responses.

## Architecture rules

- Tools calculate; agents interpret and orchestrate.
- Provider SDK objects remain inside provider adapters.
- Agents depend on protocols for LLMs, audit, tracking, tracing, and metrics.
- Graph nodes return owned partial state updates and never construct services.
- API routes validate and adapt requests; they do not contain business logic.
- Infrastructure changes must not silently change application behavior.
- New telemetry must use low-cardinality labels and exclude sensitive content.

## Verification

Run the same quality gates used by CI:

```bash
ruff check .
ruff format --check .
pytest --cov=autonomous_ai_company --cov-branch --cov-fail-under=100
python -m build --wheel --sdist
```

Tests must be deterministic and make no unapproved network calls. Use fake
providers and isolated registries or temporary storage. Real PostgreSQL tests
must use an isolated testcontainer or the explicit `POSTGRES_TEST_DSN` fallback,
never production credentials.

## Pull requests

1. Keep the change focused and update documentation with behavior.
2. Add tests for normal, failure, boundary, and concurrency paths as relevant.
3. Explain architectural impact, security implications, and verification.
4. Use a conventional commit such as `feat(graph): add routing policy`.
5. Complete the pull-request template and respond to review feedback.

Maintainers may request that unrelated changes be split. A passing pipeline is
necessary but does not replace design, security, or operational review.
