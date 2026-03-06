-- 001_init.sql: Core tables for agentic_workflows Postgres backend.
-- Applied automatically on first Docker Compose start (via /docker-entrypoint-initdb.d/).

CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT PRIMARY KEY,
    status              TEXT NOT NULL DEFAULT 'pending',
    user_input          TEXT,
    prior_context_json  TEXT,
    client_ip           TEXT,
    request_headers_json TEXT,
    result_json         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    missions_completed  INTEGER DEFAULT 0,
    tools_used_json     TEXT
);

CREATE TABLE IF NOT EXISTS graph_checkpoints (
    id          SERIAL PRIMARY KEY,
    run_id      TEXT NOT NULL,
    step        INTEGER NOT NULL,
    node_name   TEXT NOT NULL,
    state_json  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_graph_checkpoints_run_step
    ON graph_checkpoints(run_id, step);

CREATE TABLE IF NOT EXISTS memo_entries (
    id          SERIAL PRIMARY KEY,
    run_id      TEXT NOT NULL,
    namespace   TEXT NOT NULL,
    key         TEXT NOT NULL,
    value_json  TEXT NOT NULL,
    value_hash  TEXT NOT NULL,
    source_tool TEXT NOT NULL,
    step        INTEGER NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_memo_entries_run_key
    ON memo_entries(run_id, namespace, key);
