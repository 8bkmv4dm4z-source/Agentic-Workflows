-- 003_mission_contexts.sql: Persistent cross-run mission context store.
-- Requires: 002_foundation.sql (pgvector extension must exist).
-- Phase 7.3: Hybrid Deterministic + Semantic Context System.

CREATE TABLE IF NOT EXISTS mission_contexts (
    id              SERIAL PRIMARY KEY,
    run_id          TEXT NOT NULL,
    mission_id      TEXT NOT NULL,
    goal            TEXT NOT NULL,
    -- L0: SHA-256 of normalized goal text for exact cache hit
    goal_hash       TEXT NOT NULL,
    -- L1: 64-bit tool bitmask (TOOL_BITS encoding, fits 37 tools)
    tool_pattern    BIGINT NOT NULL DEFAULT 0,
    -- L2: BM25 full-text search via tsvector (auto-maintained via trigger)
    goal_tsvector   TSVECTOR,
    -- L3: Binary quantization of embedding (sign bit per dimension, 384 bits)
    embedding_bin   BIT(384),
    -- L4: Float32 cosine similarity via pgvector HNSW
    embedding       vector(384),
    status          TEXT NOT NULL DEFAULT 'completed',
    summary         TEXT,
    tools_used      TEXT[] NOT NULL DEFAULT '{}',
    key_results     JSONB NOT NULL DEFAULT '{}',
    artifacts       JSONB NOT NULL DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Unique constraint: one context record per (run_id, mission_id)
CREATE UNIQUE INDEX IF NOT EXISTS uq_mission_contexts_run_mission
    ON mission_contexts(run_id, mission_id);

-- L0: Exact hash lookup (primary short-circuit path)
CREATE INDEX IF NOT EXISTS ix_mission_contexts_goal_hash
    ON mission_contexts(goal_hash);

-- L1: Tool bitmask lookup (bitwise AND via index scan)
CREATE INDEX IF NOT EXISTS ix_mission_contexts_tool_pattern
    ON mission_contexts(tool_pattern);

-- L2: GIN index on tsvector for BM25 full-text search
CREATE INDEX IF NOT EXISTS ix_mission_contexts_tsvector
    ON mission_contexts USING gin(goal_tsvector);

-- L4: HNSW index for approximate nearest neighbor cosine similarity
-- Created on empty table — instant. For populated tables, use CONCURRENTLY.
CREATE INDEX IF NOT EXISTS ix_mission_contexts_embedding_hnsw
    ON mission_contexts USING hnsw(embedding vector_cosine_ops);

-- Trigger: auto-populate goal_tsvector on insert/update
CREATE OR REPLACE FUNCTION mission_contexts_tsvector_trigger()
RETURNS TRIGGER AS $$
BEGIN
    NEW.goal_tsvector := to_tsvector('english', NEW.goal);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trig_mission_contexts_tsvector ON mission_contexts;
CREATE TRIGGER trig_mission_contexts_tsvector
    BEFORE INSERT OR UPDATE OF goal ON mission_contexts
    FOR EACH ROW EXECUTE FUNCTION mission_contexts_tsvector_trigger();
