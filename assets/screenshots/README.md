# Screenshot capture guide

The repository intentionally contains documentation rather than fabricated UI
captures. Capture screenshots only from a real local v1.0 environment using
synthetic data.

## Required captures

| Filename | View | Acceptance criteria |
| --- | --- | --- |
| `openapi.png` | FastAPI `/docs` | Health, version, auth, workflow, and stream routes visible |
| `workflow-result.png` | Formatted CEO response | Synthetic content; no token or request headers |
| `streaming.png` | SSE client | Start, node lifecycle, heartbeat if observed, and terminal event |
| `grafana-overview.png` | Overview dashboard | Synthetic traffic and visible time range |
| `mlflow-workflow.png` | Nested MLflow run | Workflow and agent hierarchy without raw prompts |

## Redaction and quality

- Use only synthetic datasets and local accounts.
- Remove Authorization headers, JWTs, cookies, API keys, passwords, hostnames,
  user identifiers, workflow/request IDs, and local filesystem usernames.
- Do not show raw prompts or generated provider responses outside validated
  application output.
- Capture at readable resolution with the relevant title and time range.
- Review image metadata and the visible browser/terminal chrome before commit.

After real captures are approved, add them using the exact filenames above and
replace the README screenshot note with rendered images in a separate change.
