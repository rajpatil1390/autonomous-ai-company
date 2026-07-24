# Version 1.0 demo script

## Purpose

Demonstrate the production architecture with synthetic data in approximately
ten minutes. The demo makes one real provider call per agent path and may incur
provider charges.

## Preparation

1. Use Python 3.12 and install the project in a virtual environment.
2. Configure a local `.env` with a valid provider key/model and a random JWT
   signing key. Never display `.env` during the demo.
3. Start the API and confirm `/health` and `/version`.
4. Prepare `workflow-request.json` from the example in `docs/api.md`.
5. Optionally enable metrics and start the local monitoring Compose stack.

## Narrative

### 1. Architecture — 90 seconds

Show the README workflow diagram. Explain that tools calculate exact metrics,
agents interpret validated metrics, specialist branches run concurrently, and
Report/CEO synthesize without changing source values. Point out the provider,
audit, and observability protocols.

### 2. Public health and authentication — 60 seconds

```bash
curl http://localhost:8000/health
curl http://localhost:8000/version
curl --fail -H 'Content-Type: application/json' \
  --data '{"username":"admin","password":"admin123"}' \
  http://localhost:8000/auth/login
```

Copy the token into a local shell variable without printing it. State clearly
that the demo user is not intended for production.

### 3. Synchronous workflow — 2 minutes

```bash
curl --fail \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  --data @workflow-request.json \
  http://localhost:8000/workflow/run
```

Show the validated CEO fields. Explain that financial values remained Decimal
through deterministic tools and were serialized as strings in prompts.

### 4. Streaming workflow — 90 seconds

```bash
curl --no-buffer --fail \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  --data @workflow-request.json \
  http://localhost:8000/workflow/stream
```

Identify real start/node/terminal events. Do not promise a heartbeat if the run
finishes before 15 seconds. Explain disconnect cancellation and request-scoped
execution.

### 5. Audit and observability — 2 minutes

Show safe audit fields, metrics, traces, or nested MLflow runs available in the
configured environment. Verify that raw prompts, generated text, passwords,
JWTs, API keys, and user identifiers are absent. Mention optional null adapters.

### 6. Engineering quality — 60 seconds

Show the test and coverage command, infrastructure directories, SLOs, one
runbook, and the disaster-recovery restore safety controls. Distinguish static
asset validation from real environment verification.

## Close

Summarize the core claim: deterministic calculations and strict contracts make
LLM reasoning composable, while dependency injection lets graph topology,
providers, persistence, and observability evolve independently.

Stop the local services and clear the shell token after the demo.
