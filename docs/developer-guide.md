# Developer guide

## Requirements

- Python 3.12
- Git for normal contribution workflows
- Docker only for container or real PostgreSQL integration verification
- A credential for the selected remote provider only; Ollama and test fakes do
  not require remote provider credentials

Unit and component tests use fakes and require no provider network access.

## Install

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
python -m pip install "ruff==0.15.20" "pytest-cov>=7,<8" "build>=1.3,<2"
```

Activate `.venv` using the command appropriate to the shell. Copy
`.env.example` to `.env`, set local values, and keep that file untracked.

## Run locally

```bash
uvicorn autonomous_ai_company.api.app:create_app --factory --reload
```

Open `http://localhost:8000/docs` for OpenAPI, or use the examples in
[api.md](api.md). Startup validates required provider configuration even when
tests later replace the graph dependency, so test fixtures set safe synthetic
environment values.

## Source layout

```text
src/autonomous_ai_company/
├── agents/          orchestration and output validation
├── api/             FastAPI routes, middleware, and SSE transport
├── audit/           audit contract implementations and PostgreSQL adapter
├── auth/            local JWT and password boundary
├── graph/           shared state, nodes, routing, and graph construction
├── llm/             provider protocol, adapters, factory, and result DTO
├── observability/   tracking, tracing, and metrics abstractions/adapters
├── prompts/         bounded, version-controlled prompt builders
├── schemas/         strict Pydantic domain and audit contracts
├── tools/           deterministic calculations
├── bootstrap.py     composition root
├── config.py        environment settings
└── exceptions.py    provider-neutral application errors
```

Infrastructure assets live at the repository root under purpose-specific
directories such as `k8s/`, `helm/`, `cloud/`, `monitoring/`, `performance/`,
`chaos/`, `dr/`, `operations/`, and `.github/workflows/`.

## Make a change

1. Start at the owning layer and preserve dependency direction.
2. Add or update strict schemas before relying on new cross-layer data.
3. Put calculations in deterministic tools, not prompts or agents.
4. Inject external behavior through a protocol and construct it in bootstrap.
5. Add boundary, failure, branch, concurrency, and security tests.
6. Update public or operational documentation in the same change.

### Adding an LLM provider

Implement the asynchronous `LLMProvider.generate` contract and return only an
immutable `GenerationResult`. Translate SDK errors into `LLMTimeoutError`,
`LLMRateLimitError`, or `LLMUnavailableError`. Register the lazy constructor in
`llm/provider_factory.py`; provider selection remains in `LLMRouter`, concrete
construction remains in bootstrap, and agents must remain unchanged. Mock the
SDK or HTTP client in tests so no provider network is required.

Provider variables and local Ollama commands are documented in
[environment.md](environment.md).

### Adding an agent

Follow the established specialist template: deterministic tool, bounded prompt,
strict output schema, injected provider/audit/observability, one validation
retry, thin graph node, and owned partial state field. Do not copy provider or
telemetry infrastructure into the agent.

### Changing graph topology

Keep node adapters unchanged when only sequencing changes. Put deterministic
routing policy in `graph/routing.py`, topology in `company_graph.py`, and
dependency construction in `graph_builder.py` or bootstrap.

## Quality gates

```bash
ruff check .
ruff format --check .
pytest --cov=autonomous_ai_company --cov-branch \
  --cov-report=term-missing --cov-report=xml:coverage.xml \
  --cov-fail-under=100
python -m build --wheel --sdist
```

The test suite enforces 100% application statement and branch coverage. High
coverage does not replace assertions about results, ordering, security,
cancellation, and error preservation.

## Test layers

- **Unit:** pure tools, schemas, prompts, adapters, and protocols.
- **Component integration:** real application components with only the external
  provider replaced by a deterministic fake.
- **API integration:** dependency overrides with fake compiled graphs.
- **Infrastructure static tests:** YAML, JSON, shell, workflow, chart, cloud,
  monitoring, security, performance, recovery, and operations contracts.
- **PostgreSQL integration:** testcontainers when Docker is available or an
  explicit isolated `POSTGRES_TEST_DSN`; otherwise honestly skipped.

## Security checklist

- Never commit `.env`, credentials, tokens, production data, raw prompts, or
  generated text.
- Use event allowlists rather than adding secret-name patterns.
- Keep labels low-cardinality and exclude user/workflow/request identifiers.
- Bound all untrusted content before it enters prompts or logs.
- Report vulnerabilities privately using [SECURITY_CONTACT.md](../SECURITY_CONTACT.md).
