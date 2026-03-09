-- Migration 005: sub_task_cursors table for chunked-read cursor persistence
-- Note: the canonical migrations directory is db/migrations/; this file mirrors
-- 005_sub_task_cursors.sql for the storage/migrations path referenced in plan 07.6-03.
CREATE TABLE IF NOT EXISTS sub_task_cursors (
    run_id       TEXT NOT NULL,
    plan_step_id TEXT NOT NULL DEFAULT '',
    mission_id   TEXT NOT NULL,
    tool_name    TEXT NOT NULL,
    key          TEXT NOT NULL,
    next_offset  INTEGER NOT NULL DEFAULT 0,
    total        INTEGER NOT NULL DEFAULT 0,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, mission_id, tool_name, key)
);
