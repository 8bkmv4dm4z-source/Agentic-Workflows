-- 002_foundation.sql: pgvector extension and v2 foundation tables.
-- These tables are created empty -- no code writes to them yet.
-- They establish the schema for future semantic search / RAG features.

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
    embedding   vector(1536),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS solved_tasks (
    id                SERIAL PRIMARY KEY,
    task_description  TEXT NOT NULL,
    solution_summary  TEXT NOT NULL,
    embedding         vector(1536),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
