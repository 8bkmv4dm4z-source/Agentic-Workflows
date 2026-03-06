# Phase 7: Production Persistence and CI - Context

**Gathered:** 2026-03-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace SQLite with Postgres (+ pgvector) for production persistence. Containerize the full stack
with Docker. Harden CI with Postgres service container, Docker build test, and coverage reporting.
Produce a WALKTHROUGH_PHASE7.md explaining the architecture. Create pgvector foundation tables
(empty, for v2 context management). Memo store also moves to Postgres. No context management
pipelines (chunking, embedding, context compiler) — those are v2 milestone work.

</domain>

<decisions>
## Implementation Decisions

### Checkpoint strategy
- Use LangGraph's first-party `langgraph-checkpoint-postgres` (AsyncPostgresSaver) — drop-in replacement for SQLiteCheckpointStore
- RunStore Postgres implementation uses `asyncpg` driver (native async, pairs with AsyncPostgresSaver)
- Both checkpoint_store and run_store swap to Postgres in production
- Single shared `asyncpg` connection pool created at startup, passed to both AsyncPostgresSaver and AsyncPostgresRunStore
- ENV-based switching: `DATABASE_URL` set → Postgres; absent → SQLite (dev/test)

### Docker & dev workflow
- Local dev: Postgres runs in Docker (`docker-compose up postgres`), Python/FastAPI runs locally
- Production/demo: `docker-compose up` runs everything (FastAPI + Postgres)
- Single-stage Dockerfile: `python:3.12-slim` base, simple and learnable
- Postgres image: `pgvector/pgvector:pg16` (pgvector pre-installed)
- Named Docker volume for Postgres data persistence across restarts
- `docker-compose down -v` explicitly wipes data when needed

### CI pipeline scope
- Add Postgres service container to GitHub Actions CI
- CI test matrix: run tests against both SQLite AND Postgres backends
- Add Docker image build test (build only, no push)
- Add pytest-cov with 80% coverage threshold to fail CI
- Keep ScriptedProvider — no live LLM credentials in CI

### Data persistence
- Raw SQL init scripts in `db/migrations/` directory — no Alembic
- docker-compose mounts scripts to `/docker-entrypoint-initdb.d/` for auto-execution
- Schema: runs table (RunStore) + AsyncPostgresSaver's own checkpoint tables + 3 foundation tables for v2 context management (task_runs, file_chunks with vector column, solved_tasks with vector column)
- pgvector extension enabled in init script (`CREATE EXTENSION vector`)
- Foundation tables are empty — no code writes to them yet (v2 delivers the pipelines)
- Data retention: keep indefinitely, no auto-expiry
- Memo store moves from SQLite to Postgres (all persistence unified)

### Deliverables
- WALKTHROUGH_PHASE7.md: full architecture walkthrough of Docker, Postgres, CI, and persistence layer — learning-driven (per project constraint and LRNG-01 pattern)

### Claude's Discretion
- asyncpg pool size and configuration
- Exact SQL schema column types and indexes
- Docker health check configuration
- Uvicorn worker count in Docker
- Postgres init script ordering
- Coverage report format (terminal vs HTML)
- Exact CI workflow matrix syntax

</decisions>

<specifics>
## Specific Ideas

- "I want as little changes from P6 to P7" (from Phase 6 context) — RunStore Protocol designed for clean swap
- "Docker is very new to me — advise through the process" — WALKTHROUGH should explain Docker concepts
- Context management research (context_management_research.md) drives the pgvector foundation tables
- "Context as compiled view over persistent state" — v2 vision documented, foundation laid in P7

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `RunStore Protocol` (storage/protocol.py, 33 lines): async methods save_run(), get_run(), list_runs(), update_run() — Postgres impl matches this interface
- `SQLiteRunStore` (storage/sqlite.py, 214 lines): reference implementation for AsyncPostgresRunStore
- `SQLiteCheckpointStore` (checkpoint_store.py, 126 lines): 18+ save() calls in graph.py — AsyncPostgresSaver must be compatible
- `FastAPI app` (api/app.py, 139 lines): lifespan handler creates stores, compiles graph — swap point for Postgres
- `.github/workflows/ci.yml` (38 lines): existing CI to extend with Postgres service + coverage
- `.env.example`: add DATABASE_URL, coverage env vars
- `conftest.py`: ScriptedProvider fixtures — extend with Postgres test fixtures

### Established Patterns
- Pydantic v2 with ConfigDict for all models
- ENV-based config via os.environ.get() with defaults
- anyio.to_thread.run_sync for async wrapping of sync calls (SQLite pattern — not needed for asyncpg)
- threading.Lock for SQLite thread safety (not needed for Postgres connection pool)

### Integration Points
- `api/app.py` lifespan: swap SQLiteRunStore → AsyncPostgresRunStore based on DATABASE_URL
- `graph.py __init__`: swap SQLiteCheckpointStore → AsyncPostgresSaver based on DATABASE_URL
- `pyproject.toml`: add asyncpg, langgraph-checkpoint-postgres, pytest-cov dependencies
- `Makefile`: add docker-up, docker-down, docker-build targets

</code_context>

<deferred>
## Deferred Ideas

- Context management pipelines (chunking, embedding, context compiler, solved-task lookup) — v2 milestone
- Authentication/authorization on API endpoints — post-v1
- Rate limiting middleware — post-v1
- Full sandbox for run_bash (seccomp, containers) — post-v1
- Async orchestrator rewrite — future refactor
- Multi-tenancy — out of scope (single-team tool)
- Project trajectory review / audit milestone — run /gsd:audit-milestone after Phase 7

</deferred>

---

*Phase: 07-production-persistence-and-ci*
*Context gathered: 2026-03-06*
