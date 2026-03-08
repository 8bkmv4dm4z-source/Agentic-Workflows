-- 002_foundation.sql: pgvector extension and v2 foundation tables.
-- These tables are created empty -- no code writes to them yet.
-- They establish the schema for future semantic search / RAG features.
-- Updated 2026-03-08: vector(1536) → vector(384) to match BAAI/bge-small-en-v1.5 (384-dim).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS task_runs (
    id               SERIAL PRIMARY KEY,
    run_id           TEXT NOT NULL,
    task_description TEXT NOT NULL,
    result_summary   TEXT,
    tools_used       TEXT[],
    success          BOOLEAN DEFAULT FALSE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS file_chunks (
    id          SERIAL PRIMARY KEY,
    file_path   TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    content     TEXT NOT NULL,
    embedding   vector(384),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS solved_tasks (
    id                SERIAL PRIMARY KEY,
    task_description  TEXT NOT NULL,
    solution_summary  TEXT NOT NULL,
    embedding         vector(384),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Migration guard: if this DB already has vector(1536) columns from a prior run of this file,
-- alter them to vector(384). These columns are always NULL so the cast is safe.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'file_chunks' AND column_name = 'embedding'
          AND udt_name = 'vector'
    ) THEN
        ALTER TABLE file_chunks ALTER COLUMN embedding TYPE vector(384)
            USING NULL::vector(384);
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'solved_tasks' AND column_name = 'embedding'
          AND udt_name = 'vector'
    ) THEN
        ALTER TABLE solved_tasks ALTER COLUMN embedding TYPE vector(384)
            USING NULL::vector(384);
    END IF;
END $$;
