-- 004_mission_artifacts.sql: Cross-run artifact store for tool outputs.
-- Requires: 002_foundation.sql (pgvector extension must exist).
-- Phase 7.3: Hybrid Deterministic + Semantic Context System.

CREATE TABLE IF NOT EXISTS mission_artifacts (
    id          SERIAL PRIMARY KEY,
    run_id      TEXT NOT NULL,
    mission_id  TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    source_tool TEXT NOT NULL,
    -- SHA-256 of key for O(1) exact lookup
    key_hash    TEXT NOT NULL,
    -- Float32 embedding for semantic artifact search
    embedding   vector(384),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Unique constraint: one artifact per (run_id, mission_id, key)
CREATE UNIQUE INDEX IF NOT EXISTS uq_mission_artifacts_run_mission_key
    ON mission_artifacts(run_id, mission_id, key);

-- Key hash lookup for exact artifact retrieval
CREATE INDEX IF NOT EXISTS ix_mission_artifacts_key_hash
    ON mission_artifacts(key_hash);

-- HNSW index for semantic artifact search
CREATE INDEX IF NOT EXISTS ix_mission_artifacts_embedding_hnsw
    ON mission_artifacts USING hnsw(embedding vector_cosine_ops);
