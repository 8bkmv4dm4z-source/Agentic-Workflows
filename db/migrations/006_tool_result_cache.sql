-- Migration 006: tool result cache for large-result summarization (Phase 8 BTLNK-02)
CREATE TABLE IF NOT EXISTS tool_result_cache (
    id          SERIAL PRIMARY KEY,
    tool_name   TEXT        NOT NULL,
    args_hash   TEXT        NOT NULL,  -- SHA-256 of JSON-serialized args (sort_keys=True)
    full_result TEXT        NOT NULL,  -- full tool result string
    summary     TEXT        NOT NULL,  -- first 200 chars of result
    result_len  INTEGER     NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tool_name, args_hash)
);

CREATE INDEX IF NOT EXISTS ix_tool_result_cache_expires
    ON tool_result_cache (expires_at);

CREATE INDEX IF NOT EXISTS ix_tool_result_cache_lookup
    ON tool_result_cache (tool_name, args_hash);
