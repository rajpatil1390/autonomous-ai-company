# Graph Report - Autonomous-AI-Company  (2026-07-15)

## Corpus Check
- 36 files · ~12,731 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 440 nodes · 773 edges · 30 communities (28 shown, 2 thin omitted)
- Extraction: 75% EXTRACTED · 25% INFERRED · 0% AMBIGUOUS · INFERRED: 193 edges (avg confidence: 0.74)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- test_finance_tools.py
- ClaudeClient
- FinanceAgent
- LLMRouter
- Settings
- test_audit_schema.py
- build_finance_prompt
- AuditEvent
- AuditLogger
- audit_logger.py
- _AgentOutputModel
- InMemoryAuditStorage
- test_schemas.py
- audit.py
- AuditStorage
- AuditEventType
- autonomous-ai-company
- Codex Master Prompt — Autonomous AI Company (0 → 100 Build)
- .get_events

## God Nodes (most connected - your core abstractions)
1. `AuditLogger` - 36 edges
2. `ClaudeClient` - 25 edges
3. `AuditEvent` - 22 edges
4. `FinanceAgent` - 19 edges
5. `LLMRouter` - 19 edges
6. `Settings` - 18 edges
7. `total_revenue()` - 17 edges
8. `InMemoryAuditStorage` - 15 edges
9. `LLMProvider` - 15 edges
10. `build_finance_prompt()` - 15 edges

## Surprising Connections (you probably didn't know these)
- `test_build_finance_agent_constructs_each_dependency_exactly_once()` --indirect_call--> `FinanceAgent`  [INFERRED]
  tests/unit/test_bootstrap.py → src/autonomous_ai_company/agents/finance_agent.py
- `test_build_finance_agent_creates_the_correct_shared_dependency_graph()` --indirect_call--> `FinanceAgent`  [INFERRED]
  tests/unit/test_bootstrap.py → src/autonomous_ai_company/agents/finance_agent.py
- `test_logger_translates_storage_failures_with_chained_causes()` --indirect_call--> `AuditStorage`  [INFERRED]
  tests/unit/test_audit_logger.py → src/autonomous_ai_company/audit/audit_logger.py
- `FakeLLMProvider` --uses--> `InMemoryAuditStorage`  [INFERRED]
  tests/integration/test_finance_pipeline.py → src/autonomous_ai_company/audit/audit_logger.py
- `test_real_finance_pipeline_with_only_llm_provider_replaced()` --indirect_call--> `InMemoryAuditStorage`  [INFERRED]
  tests/integration/test_finance_pipeline.py → src/autonomous_ai_company/audit/audit_logger.py

## Import Cycles
- None detected.

## Communities (30 total, 2 thin omitted)

### Community 0 - "test_finance_tools.py"
Cohesion: 0.06
Nodes (68): InvalidDatasetError, Signal that supplied business data violates its domain contract., Signal that valid data cannot produce a mathematically defined metric., UndefinedMetricError, average_order_value(), calculate_kpis(), FinanceKPIs, profit_margin() (+60 more)

### Community 1 - "ClaudeClient"
Cohesion: 0.06
Nodes (51): LogCaptureFixture, ApplicationError, LLMError, LLMRateLimitError, LLMTimeoutError, LLMUnavailableError, Exception, Define provider-neutral failures exposed by application boundaries.  Stable exce (+43 more)

### Community 2 - "FinanceAgent"
Cohesion: 0.07
Nodes (40): _build_error_correction_prompt(), FinanceAgent, FinanceAgentValidationError, FinancialDataset, Orchestrate deterministic finance analysis and validated LLM reasoning.  The age, Preserve the Finance Agent's public validation exception name., Ask for schema correction without changing the original analysis task.      The, Coordinate finance tools, prompting, generation, validation, and audit.      Dep (+32 more)

### Community 3 - "LLMRouter"
Cohesion: 0.09
Nodes (24): ProviderFactory, LLMRouter, Expose a provider-neutral boundary for text generation.  Centralizing provider s, Forward a generation request without changing results or errors.          The ro, Select one configured provider and forward generation requests to it.      The r, Resolve and construct the requested provider exactly once.          Args:, Return the configured provider through its abstract contract.          Exposing, Unit tests for centralized provider selection and request forwarding. (+16 more)

### Community 4 - "Settings"
Cohesion: 0.07
Nodes (39): BaseSettings, Assemble concrete application dependencies in one composition root.  Keeping con, get_settings(), Centralize validated runtime configuration at the application boundary.  Keeping, Describe and validate configuration before the application uses it.      Requiri, Return one validated settings object for consistent process-wide use.      Confi, Settings, ConfigurationError (+31 more)

### Community 5 - "test_audit_schema.py"
Cohesion: 0.12
Nodes (23): Unit tests for validated provider-independent audit events., Enum and JSON fields should reject values outside their contracts., All nested numeric values must remain portable strict JSON., Metadata is optional while the core event envelope remains required., Return isolated valid input for schema tests., Audit history must reject schema drift and post-validation mutation., A validated event should retain every field in JSON-compatible form., Every logger lifecycle method should have a valid schema category. (+15 more)

### Community 6 - "build_finance_prompt"
Cohesion: 0.09
Nodes (30): KPIValue, build_finance_prompt(), Build the version-controlled reasoning instructions for the Finance Agent.  Prom, Return a readable Finance Agent prompt from deterministic inputs.      This func, extract_kpi_json(), Exception, Unit tests for the version-controlled Finance Agent prompt., Only Decimal values should become strings at the JSON boundary. (+22 more)

### Community 7 - "AuditEvent"
Cohesion: 0.15
Nodes (11): Sanitize and append one event atomically in invocation order., Record that a component began work for a workflow run., Record sanitized facts about a deterministic tool invocation., Record safe LLM request metadata while redacting raw prompts., Record safe response metadata without coupling to an LLM provider., Record sanitized error facts without swallowing the original error., Record that a component completed work for a workflow run., Append atomically so concurrent writers cannot corrupt ordering. (+3 more)

### Community 8 - "AuditLogger"
Cohesion: 0.15
Nodes (19): AuditLogger, Create, sanitize, validate, and store ordered lifecycle events.      Centralizin, AuditError, Signal that an audit event could not be validated, stored, or read., Unit tests for sanitized, thread-safe audit logging., Sanitization should reject keys that cannot form stable JSON objects., An explicitly supplied invalid container must not become an empty event., Invalid safe values should fail loudly instead of being coerced. (+11 more)

### Community 9 - "audit_logger.py"
Cohesion: 0.17
Nodes (15): _is_sensitive_key(), _looks_like_credential(), _normalized_key(), datetime, JsonValue, Record sanitized audit events behind a replaceable storage interface.  Phase A k, Recognize common credential formats even under an innocuous field name., Recursively convert safe containers and redact credential values. (+7 more)

### Community 10 - "_AgentOutputModel"
Cohesion: 0.21
Nodes (12): _AgentOutputModel, CEOAgentOutput, DataScientistAgentOutput, MarketingAgentOutput, BaseModel, Define provider-independent contracts for validated agent responses.  These sche, Define the assembled report content before any file is written.      Separating, Apply strict validation consistently across every agent boundary.      A shared (+4 more)

### Community 11 - "InMemoryAuditStorage"
Cohesion: 0.18
Nodes (10): InMemoryAuditStorage, Initialize the logger with replaceable storage and clock dependencies., Store ordered events safely for Phase A tests and local execution., Initialize isolated event state and its synchronization lock., build_finance_agent(), Return one fully configured Finance Agent dependency graph.      Every runtime c, Callers should receive a copy rather than mutable internal storage., test_in_memory_storage_returns_immutable_snapshot() (+2 more)

### Community 12 - "test_schemas.py"
Cohesion: 0.24
Nodes (10): BaseModel, Tests for all provider-independent agent output contracts., Incomplete agent responses should fail instead of being guessed., Strict schemas should reject malformed types returned by an LLM., Generated JSON schemas should explain every field to callers., Every valid agent contract should round-trip through JSON., test_agent_output_accepts_valid_data_and_serializes_to_json(), test_agent_output_rejects_invalid_field_type() (+2 more)

### Community 13 - "audit.py"
Cohesion: 0.22
Nodes (7): _ensure_finite_json(), datetime, JsonValue, Define provider-independent contracts for immutable audit events.  Audit data is, Reject non-finite floats recursively so events remain valid JSON., Reject naive or non-UTC timestamps to preserve global ordering., Ensure nested payload and metadata can serialize without JSON gaps.

### Community 14 - "AuditStorage"
Cohesion: 0.22
Nodes (7): AuditStorage, Protocol, Define the persistence capability required by ``AuditLogger``.      PostgreSQL c, Persist one already validated audit event., Return an ordered, immutable view of persisted events., AuditLogger should depend on storage behavior rather than memory details., test_logger_uses_injected_storage_interface()

### Community 15 - "AuditEventType"
Cohesion: 0.29
Nodes (7): AuditEventType, Name the lifecycle events that every audited component may emit., StrEnum, incrementing_clock(), Return a deterministic clock with one timestamp for each event method., Lifecycle methods should preserve invocation order and validated times., test_logger_records_every_event_type_in_order_with_utc_timestamps()

### Community 28 - "Codex Master Prompt — Autonomous AI Company (0 → 100 Build)"
Cohesion: 0.50
Nodes (3): A note on using this well, Codex Master Prompt — Autonomous AI Company (0 → 100 Build), How to use this

## Knowledge Gaps
- **3 isolated node(s):** `autonomous-ai-company`, `How to use this`, `A note on using this well`
  These have ≤1 connection - possible missing edges or undocumented components.
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AuditLogger` connect `AuditLogger` to `FinanceAgent`, `Settings`, `AuditEvent`, `audit_logger.py`, `InMemoryAuditStorage`, `AuditStorage`, `AuditEventType`, `.get_events`?**
  _High betweenness centrality (0.195) - this node is a cross-community bridge._
- **Why does `build_finance_prompt()` connect `build_finance_prompt` to `FinanceAgent`?**
  _High betweenness centrality (0.125) - this node is a cross-community bridge._
- **Why does `AuditEventType` connect `AuditEventType` to `FinanceAgent`, `test_audit_schema.py`, `AuditEvent`, `AuditLogger`, `InMemoryAuditStorage`, `audit.py`, `AuditStorage`?**
  _High betweenness centrality (0.120) - this node is a cross-community bridge._
- **Are the 24 inferred relationships involving `AuditLogger` (e.g. with `FinanceAgent` and `FinanceAgentValidationError`) actually correct?**
  _`AuditLogger` has 24 INFERRED edges - model-reasoned connections that need verification._
- **Are the 21 inferred relationships involving `ClaudeClient` (e.g. with `build_finance_agent()` and `Settings`) actually correct?**
  _`ClaudeClient` has 21 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `AuditEvent` (e.g. with `AuditLogger` and `AuditStorage`) actually correct?**
  _`AuditEvent` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `FinanceAgent` (e.g. with `AuditLogger` and `AgentOutputValidationError`) actually correct?**
  _`FinanceAgent` has 14 INFERRED edges - model-reasoned connections that need verification._