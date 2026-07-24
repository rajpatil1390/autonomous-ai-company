# API reference

The FastAPI application exposes a small transport surface over the compiled
company graph. Interactive OpenAPI documentation is available at `/docs` and
the schema at `/openapi.json` when the application is running.

## Base conventions

- JSON requests use `Content-Type: application/json`.
- Protected routes use `Authorization: Bearer <token>`.
- Unknown request fields and invalid strict types are rejected.
- `business_context` is bounded to 4,000 characters.
- `executive_question` is optional and bounded to 1,000 characters.
- Workflow requests must supply current data, previous data, and the analytics
  series; the API never derives missing values.

## Public endpoints

### `GET /health`

Process liveness response:

```json
{"status":"ok"}
```

### `GET /version`

```json
{
  "application": "Autonomous AI Company",
  "version": "1.0.0"
}
```

### `POST /auth/login`

For local demonstration, the application contains one bcrypt-hashed demo
account: username `admin`, password `admin123`. Do not expose this identity on
the public internet; replace it with an external identity provider.

Request:

```json
{
  "username": "admin",
  "password": "admin123"
}
```

Response:

```json
{
  "access_token": "<JWT returned by the local application>",
  "token_type": "bearer"
}
```

Invalid credentials return `401` with a `WWW-Authenticate: Bearer` header.

## Workflow request

Both workflow endpoints accept this strict model:

```json
{
  "dataset": [
    {
      "revenue": "100.00",
      "cost": "60.00",
      "customer_id": "customer-1",
      "segment": "Enterprise"
    }
  ],
  "previous_dataset": [
    {
      "revenue": "80.00",
      "cost": "50.00",
      "customer_id": "customer-1",
      "segment": "Enterprise"
    }
  ],
  "data_scientist_series": [10, 20, 30],
  "business_context": "Subscription business evaluating controlled growth.",
  "executive_question": "Which priority should be approved first?"
}
```

Dataset rows are shared workflow mappings. Tool-specific validation determines
required columns and valid values. Financial decimal strings preserve exact
precision through deterministic calculation and prompt serialization.

## `POST /workflow/run`

Requires a bearer token. The endpoint invokes the asynchronous graph and
returns a validated `CEOAgentOutput`:

```json
{
  "executive_summary": "Validated executive synthesis.",
  "business_health": "stable",
  "strategic_priorities": ["Protect margin", "Improve retention"],
  "key_risks": ["Provider concentration"],
  "final_recommendation": "Sequence growth after retention controls.",
  "confidence_score": 0.9
}
```

Allowed `business_health` values are `critical`, `concerning`, `stable`, and
`strong`. The response contains reasoning, not external side effects.

## `POST /workflow/stream`

Requires the same bearer token and request body. The response content type is
`text/event-stream`. Each event carries `run_id`, an aware UTC `timestamp`,
`event_type`, and JSON-safe `payload`.

Event types:

- `workflow_started`
- `node_started`
- `node_completed`
- `heartbeat`
- `workflow_completed`
- `workflow_failed`

The graph executes within the request. Client disconnect cancels execution; no
global workflow registry, event broker, or background queue is implied.

Example:

```text
event: workflow_started
data: {"run_id":"...","timestamp":"...Z","event_type":"workflow_started","payload":{}}
```

## Optional `GET /metrics`

The endpoint exists only when `METRICS_ENABLED=true`. It is unauthenticated so
Prometheus can scrape it; secure it through network policy or ingress controls.
It exposes the application-owned registry rather than the global Prometheus
registry.

## Error responses

| Status | Meaning |
| ---: | --- |
| `400` | Deterministic dataset or metric input is invalid. |
| `401` | Bearer credentials are absent, malformed, expired, or invalid. |
| `422` | Request-schema validation failed. |
| `500` | Unexpected application failure; internal details are not exposed. |
| `503` | A provider-neutral LLM failure reached the API boundary. |

LLM error responses do not expose provider internals. Unexpected errors use a
generic response while traces and safe audit telemetry retain diagnostic
context.

## Command-line example

```bash
TOKEN=$(curl --fail --silent \
  -H 'Content-Type: application/json' \
  --data '{"username":"admin","password":"admin123"}' \
  http://localhost:8000/auth/login \
  | python -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

curl --fail \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  --data @workflow-request.json \
  http://localhost:8000/workflow/run
```

Invoking a workflow uses the configured provider and may incur provider costs.
