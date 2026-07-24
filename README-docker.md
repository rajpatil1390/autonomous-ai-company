# Docker deployment guide

The container setup runs the FastAPI adapter and PostgreSQL audit storage as
separate services. Application behavior remains in the Python package; Docker
only packages the runtime and supplies deployment configuration.

## Prerequisites

- Docker Engine or Docker Desktop with Docker Compose v2
- An Anthropic API key and configured model name
- Three locally generated secrets: the Anthropic key, a JWT signing key, and a
  PostgreSQL password

## Configure the environment

Docker Compose reads substitutions from the shell or a project-root `.env`
file. The `.env` file is excluded from both Git and the Docker build context.
Create it with values appropriate for your environment:

```dotenv
ANTHROPIC_API_KEY=<your-provider-key>
MODEL_NAME=<your-supported-anthropic-model>
JWT_SECRET_KEY=<at-least-32-random-characters>
POSTGRES_PASSWORD=<a-strong-random-database-password>
```

Generate independent random values rather than copying the placeholders:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

The required secret variables deliberately have no defaults. Compose stops
before deployment when any is absent.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `ANTHROPIC_API_KEY` | Yes | None | Anthropic SDK credential |
| `MODEL_NAME` | Yes | None | Provider model selected at deployment |
| `JWT_SECRET_KEY` | Yes | None | JWT HMAC key; minimum 32 characters |
| `POSTGRES_PASSWORD` | Yes | None | PostgreSQL role password |
| `TEMPERATURE` | No | `0.2` | LLM sampling temperature |
| `MAX_TOKENS` | No | `4096` | Maximum generated tokens |
| `LOG_LEVEL` | No | `INFO` | Application log level |
| `JWT_ALGORITHM` | No | `HS256` | Allowlisted JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | `30` | Access-token lifetime |
| `POSTGRES_DATABASE` | No | `autonomous_ai_company` | Database name |
| `POSTGRES_USER` | No | `autonomous_ai_company` | Database role |
| `API_PORT` | No | `8000` | Host port mapped to FastAPI |
| `APP_WORKERS` | No | `2` | Production Uvicorn worker count |
| `POSTGRES_HOST_PORT` | No | `5432` | Development-only database host port |

## Build and run in production mode

Build the production stage and start both services:

```bash
docker compose build --pull
docker compose up -d
docker compose ps
```

The production API container runs as UID/GID `10001`, uses a read-only root
filesystem, drops Linux capabilities, and exposes only the API port. PostgreSQL
is reachable only through the internal Compose network.

Confirm health:

```bash
curl --fail http://localhost:8000/health
docker compose exec postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Stop without deleting audit data:

```bash
docker compose down
```

## Development mode

Layer the development override over the production definition:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

The override bind-mounts `src/` read-only, puts it on `PYTHONPATH`, enables
Uvicorn auto-reload, switches logs to debug, and exposes PostgreSQL on the host.
Edits made on the host trigger reloads without rebuilding the image.

Validate the merged configuration before starting it:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml config --quiet
```

## PostgreSQL initialization

On the first start of an empty `postgres_data` volume, the official PostgreSQL
entrypoint executes `src/autonomous_ai_company/audit/schema.sql`. It creates the
append-only `audit_events` table and its run and timestamp indexes.

Check the table:

```bash
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\\d audit_events"'
```

Initialization scripts run only for a new database volume. To intentionally
erase local audit data and initialize again, first back up anything important,
then run:

```bash
docker compose down -v
docker compose up -d
```

## Exercise the API

Health and version endpoints are public:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/version
```

The current application has the Phase C in-memory demo account `admin` with
password `admin123`. It is suitable only for local evaluation and must be
replaced by external identity management before internet-facing deployment.
Obtain a token:

```bash
TOKEN=$(curl --fail --silent --show-error \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' \
  http://localhost:8000/auth/login \
  | python -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
```

Create `workflow-request.json` containing explicit current data, historical
data, and the analytical series:

```json
{
  "dataset": [
    {
      "revenue": 100,
      "cost": 60,
      "customer_id": "c1",
      "segment": "Enterprise"
    }
  ],
  "previous_dataset": [
    {
      "revenue": 80,
      "cost": 50,
      "customer_id": "c1",
      "segment": "Enterprise"
    }
  ],
  "data_scientist_series": [10, 20, 30],
  "business_context": "Subscription company planning controlled growth.",
  "executive_question": "Which priority should be approved?"
}
```

Run the normal endpoint:

```bash
curl --fail --silent --show-error \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  --data @workflow-request.json \
  http://localhost:8000/workflow/run
```

Run the SSE endpoint with buffering disabled:

```bash
curl --no-buffer --fail --silent --show-error \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  --data @workflow-request.json \
  http://localhost:8000/workflow/stream
```

Both workflow commands invoke the configured Anthropic provider and may incur
provider usage charges.

## Troubleshooting

- **Compose reports a required variable is missing:** define it in `.env` or
  export it in the current shell. Do not put secrets in Compose files.
- **JWT login returns an internal error:** ensure `JWT_SECRET_KEY` contains at
  least 32 characters and restart the API service.
- **The API remains unhealthy:** inspect `docker compose logs api`; verify port
  `8000` is not already occupied or change `API_PORT`.
- **PostgreSQL remains unhealthy:** inspect `docker compose logs postgres` and
  ensure the configured volume is writable by the official image.
- **The audit table is missing after changing `schema.sql`:** initialization
  scripts do not rerun on an existing volume. Apply the SQL deliberately or
  recreate the disposable local volume after backing it up.
- **Source edits do not reload:** start with both Compose files and verify that
  `./src` is shared with Docker Desktop on Windows or macOS.
- **Workflow calls return 503:** verify the provider key, model availability,
  and outbound network access from the API container.
- **Port 5432 is already used:** set a different `POSTGRES_HOST_PORT` in
  development mode.
