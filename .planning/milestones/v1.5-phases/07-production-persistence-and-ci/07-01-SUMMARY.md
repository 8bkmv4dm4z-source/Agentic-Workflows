---
phase: 07-production-persistence-and-ci
plan: 01
subsystem: database
tags: [postgres, psycopg, connection-pool, protocol, migration, store-factory]

# Dependency graph
requires:
  - phase: 06-fastapi-service-layer
    provides: SQLiteRunStore, SQLiteCheckpointStore, SQLiteMemoStore, RunStore Protocol, app.py lifespan
provides:
  - CheckpointStore Protocol for structural subtyping
  - MemoStore Protocol for structural subtyping
  - PostgresCheckpointStore implementation
  - PostgresMemoStore implementation
  - PostgresRunStore implementation
  - SQL migration scripts for Postgres schema
  - ENV-based store factory in app.py lifespan
affects: [07-02, 07-03, docker, ci]

# Tech tracking
tech-stack:
  added: [psycopg, psycopg_pool, psycopg-binary, pytest-cov]
  patterns: [protocol-based store abstraction, env-based backend selection, sync connection pool, lazy imports for optional backends]

key-files:
  created:
    - src/agentic_workflows/storage/checkpoint_protocol.py
    - src/agentic_workflows/storage/memo_protocol.py
    - src/agentic_workflows/orchestration/langgraph/checkpoint_postgres.py
    - src/agentic_workflows/orchestration/langgraph/memo_postgres.py
    - src/agentic_workflows/storage/postgres.py
    - db/migrations/001_init.sql
    - db/migrations/002_foundation.sql
  modified:
    - src/agentic_workflows/api/app.py
    - pyproject.toml
    - .env.example

key-decisions:
  - "psycopg[binary] + psycopg_pool instead of asyncpg per RESEARCH.md -- AsyncPostgresSaver API incompatible with project's CheckpointStore interface"
  - "Sync ConnectionPool shared across all 3 stores -- CheckpointStore and MemoStore are called synchronously from graph nodes"
  - "Lazy imports for Postgres/SQLite stores in app.py -- avoids import errors when psycopg not installed for SQLite-only dev"
  - "autocommit=True and prepare_threshold=0 in pool kwargs per RESEARCH.md pitfall findings"

patterns-established:
  - "Protocol-based store abstraction: CheckpointStore and MemoStore Protocols enable SQLite/Postgres interchangeability"
  - "ENV-based backend selection: DATABASE_URL presence determines Postgres vs SQLite stores at startup"
  - "Lazy conditional imports: backend-specific imports inside if/else to support optional dependencies"

requirements-completed: [PROD-03]

# Metrics
duration: 5min
completed: 2026-03-06
---

# Phase 7 Plan 01: Postgres Persistence Layer Summary

**Postgres store implementations (checkpoint, memo, run) with Protocol abstractions, SQL migrations, and ENV-based store factory in FastAPI lifespan**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-06T15:12:01Z
- **Completed:** 2026-03-06T15:17:01Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments
- Created CheckpointStore and MemoStore Protocols for structural subtyping, enabling SQLite/Postgres interchangeability
- Implemented PostgresCheckpointStore, PostgresMemoStore, and PostgresRunStore mirroring their SQLite counterparts exactly
- Wired ENV-based store factory in app.py: DATABASE_URL selects Postgres, absence keeps SQLite
- Created SQL migration scripts for all 3 core tables plus pgvector foundation tables
- Added psycopg[binary] and psycopg_pool to project dependencies

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Protocol abstractions and all three Postgres store implementations** - `6ee6cea` (feat)
2. **Task 2: Wire store factory in app.py lifespan, update dependencies and config** - `3734881` (feat)

## Files Created/Modified
- `src/agentic_workflows/storage/checkpoint_protocol.py` - CheckpointStore Protocol with 5 methods matching SQLiteCheckpointStore
- `src/agentic_workflows/storage/memo_protocol.py` - MemoStore Protocol with 6 methods matching SQLiteMemoStore
- `src/agentic_workflows/orchestration/langgraph/checkpoint_postgres.py` - PostgresCheckpointStore using psycopg ConnectionPool
- `src/agentic_workflows/orchestration/langgraph/memo_postgres.py` - PostgresMemoStore using psycopg ConnectionPool
- `src/agentic_workflows/storage/postgres.py` - PostgresRunStore with anyio thread wrapping
- `db/migrations/001_init.sql` - Core tables: runs, graph_checkpoints, memo_entries
- `db/migrations/002_foundation.sql` - pgvector extension + v2 foundation tables (empty)
- `src/agentic_workflows/api/app.py` - Store factory in lifespan, DATABASE_URL branching
- `pyproject.toml` - Added psycopg[binary], psycopg_pool, pytest-cov
- `.env.example` - Added DATABASE_URL section with documentation

## Decisions Made
- Used psycopg[binary] + psycopg_pool instead of asyncpg: RESEARCH.md found AsyncPostgresSaver API (aput/aget/alist) is incompatible with project's CheckpointStore API (save/load_latest/list_checkpoints). Custom implementations mirror SQLite APIs exactly.
- Sync ConnectionPool shared across all 3 Postgres stores: CheckpointStore and MemoStore are called synchronously from graph nodes (~30 save() calls per run), so async pool would add complexity without benefit.
- Lazy imports in app.py lifespan: Postgres store imports only occur when DATABASE_URL is set, allowing SQLite-only dev environments without psycopg installed.
- autocommit=True and prepare_threshold=0 in pool kwargs: per RESEARCH.md findings, autocommit is needed for DDL/DML to persist, and prepare_threshold=0 prevents DuplicatePreparedStatement errors.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. DATABASE_URL in .env.example is commented out by default.

## Next Phase Readiness
- Postgres stores ready for Docker Compose integration (Plan 02)
- SQL migrations ready for /docker-entrypoint-initdb.d/ mounting
- Protocol abstractions enable unit testing with either backend
- Pre-existing ruff UP035 warning in app.py (AsyncIterator import from typing instead of collections.abc) -- not caused by this plan, logged for future cleanup

## Self-Check: PASSED

All 8 created files verified on disk. Both task commits (6ee6cea, 3734881) verified in git log.

---
*Phase: 07-production-persistence-and-ci*
*Completed: 2026-03-06*
