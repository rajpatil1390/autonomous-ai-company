# Environment and LLM provider configuration

Runtime configuration is loaded from environment variables or a local `.env`.
Copy `.env.example` to `.env`, keep `.env` out of Git, and configure exactly one
provider. Shared agents, LangGraph topology, FastAPI routes, audit, and
observability do not change when the selected provider changes.

## Shared generation settings

```dotenv
LLM_PROVIDER=anthropic
TEMPERATURE=0.2
MAX_TOKENS=4096
LOG_LEVEL=INFO
```

`LLM_PROVIDER` accepts `anthropic`, `openai`, `grok`, `ollama`, or `fake`.
Unknown values fail configuration validation. `TEMPERATURE` and `MAX_TOKENS`
provide common defaults; an agent may pass a bounded per-request override.

## Anthropic

```dotenv
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=replace-with-your-key
MODEL_ANTHROPIC=replace-with-a-model-available-to-your-account
```

`MODEL_NAME` remains a backward-compatible alias for `MODEL_ANTHROPIC`, but new
deployments should use the explicit variable.

## OpenAI

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=replace-with-your-key
MODEL_OPENAI=replace-with-a-model-available-to-your-account
```

The official asynchronous OpenAI SDK is isolated inside `openai_client.py`.

## xAI Grok

```dotenv
LLM_PROVIDER=grok
XAI_API_KEY=replace-with-your-key
MODEL_GROK=replace-with-a-grok-model-available-to-your-account
```

xAI exposes an OpenAI-compatible endpoint. `GrokClient` reuses the shared
OpenAI-compatible adapter with `https://api.x.ai/v1`, so request validation,
telemetry reduction, cancellation, and error translation are not duplicated.

## Ollama

Install Ollama for the operating system, then pull a model and start its local
service. One example is:

```powershell
ollama pull llama3.2
ollama serve
```

Configure the application:

```dotenv
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
MODEL_OLLAMA=llama3.2
```

No provider key is required. The model must already exist in the Ollama service.
Ollama is useful for learning, offline development after model download, and
privacy-sensitive experiments, but capability, speed, and memory requirements
depend on the selected model and hardware.

## Fake provider

`LLM_PROVIDER=fake` is reserved for tests. A fake must be explicitly injected
into `build_provider_factories`; bootstrap never fabricates schema responses or
stores a global test double. This keeps tests deterministic without creating a
production bypass.

## Switching safely

1. Stop Uvicorn.
2. Set `LLM_PROVIDER`.
3. Set the matching model and credential variables.
4. Leave unused secrets unset or commented.
5. Restart Uvicorn so cached settings are rebuilt.
6. Run `/health`, authenticate, and make one controlled workflow request.

Never commit `.env`, log API keys, or place credentials in prompts. Provider
responses are reduced to immutable `GenerationResult` objects; SDK response
objects never cross into agents or graph state.
