CREATE TABLE IF NOT EXISTS audit_events (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL CHECK (
        event_type IN (
            'start',
            'tool_call',
            'llm_request',
            'llm_response',
            'error',
            'finish'
        )
    ),
    component TEXT NOT NULL,
    payload JSONB NOT NULL,
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS audit_events_run_id_idx
    ON audit_events (run_id);

CREATE INDEX IF NOT EXISTS audit_events_timestamp_idx
    ON audit_events (timestamp);
