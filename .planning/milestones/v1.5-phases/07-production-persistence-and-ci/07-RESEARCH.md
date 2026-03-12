# Phase 7: Production Persistence and CI - Research

**Researched:** 2026-03-06
**Domain:** Postgres persistence, Docker containerization, CI pipeline
**Confidence:** HIGH

## Summary

Phase 7 replaces three SQLite-based stores (CheckpointStore, RunStore, MemoStore) with Postgres equivalents, containerizes the full stack via Docker Compose, and hardens the CI pipeline with Postgres service containers and coverage enforcement. The core challenge is that the project uses a **custom** `SQLiteCheckpointStore` (30 synchronous `save()` calls across graph.py) that has a fundamentally different API from LangGraph's `AsyncPostgresSaver`. The correct approach is to build Postgres implementations of the project's own store interfaces using `psycopg` (Psycopg 3), not to adopt LangGraph's checkpointer directly. RunStore already has a `Protocol` abstraction, while CheckpointStore and MemoStore need one.

A second critical finding: `langgraph-checkpoint-postgres` uses **psycopg** (Psycopg 3) as its driver, NOT `asyncpg`. The CONTEXT.md mentions asyncpg but the correct driver is `psycopg[binary]` with `psycopg_pool` for connection pooling, which aligns with the LangGraph ecosystem and avoids mixing two different Postgres drivers.

**Primary recommendation:** Use `psycopg[binary]` + `psycopg_pool` for all Postgres stores (not asyncpg). Create Protocol abstractions for CheckpointStore and MemoStore. Build Postgres implementations matching existing sync APIs. ENV-switch at the app lifespan level.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Use LangGraph's first-party `langgraph-checkpoint-postgres` (AsyncPostgresSaver) -- drop-in replacement for SQLiteCheckpointStore
- RunStore Postgres implementation uses `asyncpg` driver (native async, pairs with AsyncPostgresSaver)
- Both checkpoint_store and run_store swap to Postgres in production
- Single shared `asyncpg` connection pool created at startup, passed to both AsyncPostgresSaver and AsyncPostgresRunStore
- ENV-based switching: `DATABASE_URL` set -> Postgres; absent -> SQLite (dev/test)
- Local dev: Postgres runs in Docker (`docker-compose up postgres`), Python/FastAPI runs locally
- Production/demo: `docker-compose up` runs everything (FastAPI + Postgres)
- Single-stage Dockerfile: `python:3.12-slim` base, simple and learnable
- Postgres image: `pgvector/pgvector:pg16` (pgvector pre-installed)
- Named Docker volume for Postgres data persistence across restarts
- `docker-compose down -v` explicitly wipes data when needed
- Add Postgres service container to GitHub Actions CI
- CI test matrix: run tests against both SQLite AND Postgres backends
- Add Docker image build test (build only, no push)
- Add pytest-cov with 80% coverage threshold to fail CI
- Keep ScriptedProvider -- no live LLM credentials in CI
- Raw SQL init scripts in `db/migrations/` directory -- no Alembic
- docker-compose mounts scripts to `/docker-entrypoint-initdb.d/` for auto-execution
- Schema: runs table (RunStore) + checkpoint tables + 3 foundation tables for v2 context management (task_runs, file_chunks with vector column, solved_tasks with vector column)
- pgvector extension enabled in init script (`CREATE EXTENSION vector`)
- Foundation tables are empty -- no code writes to them yet
- Data retention: keep indefinitely, no auto-expiry
- Memo store moves from SQLite to Postgres (all persistence unified)
- WALKTHROUGH_PHASE7.md: full architecture walkthrough

### Claude's Discretion
- asyncpg pool size and configuration
- Exact SQL schema column types and indexes
- Docker health check configuration
- Uvicorn worker count in Docker
- Postgres init script ordering
- Coverage report format (terminal vs HTML)
- Exact CI workflow matrix syntax

### Deferred Ideas (OUT OF SCOPE)
- Context management pipelines (chunking, embedding, context compiler, solved-task lookup) -- v2 milestone
- Authentication/authorization on API endpoints -- post-v1
- Rate limiting middleware -- post-v1
- Full sandbox for run_bash (seccomp, containers) -- post-v1
- Async orchestrator rewrite -- future refactor
- Multi-tenancy -- out of scope (single-team tool)
- Project trajectory review / audit milestone -- run /gsd:audit-milestone after Phase 7
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PROD-03 | AsyncPostgresSaver replaces the SQLite checkpointer for production use (SQLite retained for dev/test only) | Postgres implementations of CheckpointStore, RunStore, and MemoStore using psycopg; ENV-based switching at lifespan; Protocol abstractions for all three stores |
| PROD-04 | Dockerfile and docker-compose.yml allow the full system (API + Postgres) to be started with a single `docker-compose up` | Single-stage Dockerfile with python:3.12-slim; docker-compose with pgvector/pgvector:pg16; health checks; named volume; init scripts in db/migrations/ |
| PROD-05 | GitHub Actions CI pipeline runs ruff check, mypy, and pytest on every push, using ScriptedProvider (no live LLM calls in CI) | Extend existing ci.yml with Postgres service container, test matrix (SQLite + Postgres), Docker build test, pytest-cov with 80% threshold |
</phase_requirements>

## CRITICAL: Driver Mismatch Finding

**CONTEXT.md says:** "RunStore Postgres implementation uses `asyncpg` driver" and "Single shared `asyncpg` connection pool"

**Reality:** `langgraph-checkpoint-postgres` v3.0.4 uses `psycopg` (Psycopg 3), NOT `asyncpg`. These are two completely different PostgreSQL drivers with incompatible APIs.

**CONTEXT.md says:** "Use LangGraph's first-party `langgraph-checkpoint-postgres` (AsyncPostgresSaver) -- drop-in replacement for SQLiteCheckpointStore"

**Reality:** `AsyncPostgresSaver` has API `aput(config, checkpoint, metadata, new_versions)` / `aget(config)` / `alist(config)`. The project's `SQLiteCheckpointStore` has API `save(run_id, step, node_name, state)` / `load_latest(run_id)` / `list_checkpoints(run_id)`. These are NOT compatible -- AsyncPostgresSaver is NOT a drop-in replacement.

**Recommended resolution:** The user's intent (minimal changes from P6 to P7) is best served by:
1. Using `psycopg[binary]` + `psycopg_pool` as the single Postgres driver (aligns with LangGraph ecosystem)
2. Building `PostgresCheckpointStore`, `PostgresRunStore`, and `PostgresMemoStore` that implement the same interfaces as their SQLite counterparts
3. NOT using `AsyncPostgresSaver` directly, since it would require rewriting all 30 `checkpoint_store.save()` calls and the entire checkpoint API
4. This achieves the user's goal ("as little changes from P6 to P7") while using the correct driver

**Confidence:** HIGH -- verified by reading the actual source code of both `SQLiteCheckpointStore` (126 lines in project) and `AsyncPostgresSaver` (from langgraph-checkpoint-postgres GitHub source).

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| psycopg[binary] | >=3.2 | Postgres driver (sync + async) | Used by langgraph-checkpoint-postgres; native async support; Psycopg 3 is the modern successor |
| psycopg_pool | >=3.2 | Connection pooling | AsyncConnectionPool for production; eliminates need for PgBouncer |
| pytest-cov | >=6.0 | Coverage reporting + threshold enforcement | Standard pytest coverage plugin |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| langgraph-checkpoint-postgres | >=3.0.4 | NOT used directly, but installing it pulls in psycopg | Only if future phases adopt LangGraph's built-in checkpointer |
| docker (runtime) | >=24.0 | Container runtime | Development and production deployment |
| docker-compose | >=2.20 | Multi-container orchestration | `docker-compose up` for full stack |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| psycopg | asyncpg | asyncpg is faster for raw throughput but incompatible with langgraph-checkpoint-postgres; mixing two PG drivers adds complexity |
| psycopg_pool | PgBouncer | External process vs in-process pooling; psycopg_pool is simpler for single-app deployment |
| Raw SQL migrations | Alembic | Alembic adds complexity; user explicitly chose raw SQL in db/migrations/ |
| Multi-stage Dockerfile | Single-stage | User explicitly chose single-stage for simplicity and learning |

**Installation:**
```bash
pip install "psycopg[binary]>=3.2" "psycopg_pool>=3.2" "pytest-cov>=6.0"
```

**pyproject.toml additions:**
```toml
# In [project] dependencies:
"psycopg[binary]>=3.2",
"psycopg_pool>=3.2",

# In [project.optional-dependencies] dev:
"pytest-cov>=6.0",
```

## Architecture Patterns

### Recommended Project Structure
```
src/agentic_workflows/
  storage/
    __init__.py
    protocol.py            # RunStore Protocol (exists, 33 lines)
    checkpoint_protocol.py # NEW: CheckpointStore Protocol
    memo_protocol.py       # NEW: MemoStore Protocol
    sqlite.py              # SQLiteRunStore (exists, 214 lines)
    postgres.py            # NEW: PostgresRunStore
  orchestration/langgraph/
    checkpoint_store.py    # SQLiteCheckpointStore (exists, 126 lines)
    checkpoint_postgres.py # NEW: PostgresCheckpointStore
    memo_store.py          # SQLiteMemoStore (exists, 264 lines)
    memo_postgres.py       # NEW: PostgresMemoStore
  api/
    app.py                 # Lifespan: ENV-based store selection (modify)

db/
  migrations/
    001_init.sql           # runs table, checkpoint table, memo table
    002_pgvector.sql       # CREATE EXTENSION vector; foundation tables

docker-compose.yml         # NEW: Postgres + FastAPI services
Dockerfile                 # NEW: python:3.12-slim based
.dockerignore              # NEW: exclude .venv, .git, .tmp, etc.
```

### Pattern 1: ENV-Based Store Factory
**What:** Single factory function that returns SQLite or Postgres stores based on `DATABASE_URL`
**When to use:** At app lifespan startup (app.py)
**Example:**
```python
# Source: project convention from CONTEXT.md
import os

async def create_stores():
    """Create storage backends based on environment."""
    db_url = os.environ.get("DATABASE_URL")

    if db_url:
        # Production: Postgres
        from psycopg_pool import AsyncConnectionPool
        pool = AsyncConnectionPool(
            conninfo=db_url,
            min_size=2,
            max_size=10,
            open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0},
        )
        await pool.open(wait=True)

        from agentic_workflows.storage.postgres import PostgresRunStore
        from agentic_workflows.orchestration.langgraph.checkpoint_postgres import PostgresCheckpointStore
        from agentic_workflows.orchestration.langgraph.memo_postgres import PostgresMemoStore

        run_store = PostgresRunStore(pool)
        checkpoint_store = PostgresCheckpointStore(pool)
        memo_store = PostgresMemoStore(pool)
        return run_store, checkpoint_store, memo_store, pool
    else:
        # Dev/test: SQLite
        from agentic_workflows.storage.sqlite import SQLiteRunStore
        from agentic_workflows.orchestration.langgraph.checkpoint_store import SQLiteCheckpointStore
        from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore

        return SQLiteRunStore(), SQLiteCheckpointStore(), SQLiteMemoStore(), None
```

### Pattern 2: Protocol Abstractions for CheckpointStore
**What:** Define a Protocol for CheckpointStore so both SQLite and Postgres implementations are interchangeable
**When to use:** CheckpointStore and MemoStore need Protocols (RunStore already has one)
**Example:**
```python
# Source: Follows existing RunStore Protocol pattern in storage/protocol.py
from typing import Any, Protocol, runtime_checkable
from agentic_workflows.orchestration.langgraph.state_schema import RunState

@runtime_checkable
class CheckpointStore(Protocol):
    def save(self, *, run_id: str, step: int, node_name: str, state: RunState) -> None: ...
    def load_latest(self, run_id: str) -> RunState | None: ...
    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]: ...
    def list_runs(self, limit: int = 10) -> list[dict[str, Any]]: ...
    def load_latest_run(self) -> RunState | None: ...
```

### Pattern 3: Sync Postgres Wrapper (for CheckpointStore)
**What:** The custom CheckpointStore is called synchronously from graph nodes (30 sync calls). Postgres implementation must also be sync.
**When to use:** For CheckpointStore and MemoStore which are called from sync graph node functions
**Example:**
```python
# Source: psycopg docs - sync connection from pool
from psycopg_pool import ConnectionPool  # NOTE: sync pool, not async

class PostgresCheckpointStore:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def save(self, *, run_id: str, step: int, node_name: str, state: RunState) -> None:
        state_json = json.dumps(state, sort_keys=True, default=str)
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO graph_checkpoints (run_id, step, node_name, state_json, created_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (run_id, step, node_name, state_json, utc_now_iso()),
            )
```

**IMPORTANT architectural decision:** Since `checkpoint_store.save()` and `memo_store` methods are called synchronously from graph node functions (which run in a sync thread via `anyio.to_thread.run_sync`), the Postgres CheckpointStore and MemoStore should use `psycopg`'s **synchronous** `ConnectionPool` (not `AsyncConnectionPool`). Only the `RunStore` uses async (it's called from async FastAPI route handlers).

This means: **two pools** -- one sync (`ConnectionPool`) for CheckpointStore + MemoStore, one async (`AsyncConnectionPool`) for RunStore. OR, use a single sync pool with `anyio.to_thread.run_sync` wrapping in RunStore (matching current SQLite pattern).

**Recommended:** Single sync `ConnectionPool` for all three stores. RunStore already wraps sync calls with `anyio.to_thread.run_sync` (the SQLite pattern). Keep that pattern for Postgres.

### Pattern 4: Docker Compose with Health Checks
**What:** Postgres container with health check, FastAPI depends_on with condition
**When to use:** docker-compose.yml
**Example:**
```yaml
# Source: Docker docs, pgvector Docker Hub
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: agentic
      POSTGRES_PASSWORD: agentic
      POSTGRES_DB: agentic_workflows
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./db/migrations:/docker-entrypoint-initdb.d
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "agentic"]
      interval: 5s
      timeout: 5s
      retries: 5

  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://agentic:agentic@postgres:5432/agentic_workflows
      P1_PROVIDER: ${P1_PROVIDER:-scripted}
    depends_on:
      postgres:
        condition: service_healthy
    env_file:
      - .env

volumes:
  pgdata:
```

### Anti-Patterns to Avoid
- **Using AsyncPostgresSaver for the custom checkpoint store:** APIs are incompatible; would require rewriting 30+ call sites and the entire checkpoint interface
- **Mixing asyncpg and psycopg drivers:** Two different PG drivers increases dependency weight and connection management complexity
- **Opening AsyncConnectionPool in constructor:** Deprecated pattern; must use `open=False` then `await pool.open()` explicitly
- **Running `CREATE EXTENSION vector` in .sql init file:** Known Docker issue; use .sh script instead for reliability
- **Forgetting `prepare_threshold=0` in psycopg connection kwargs:** Causes `DuplicatePreparedStatement` errors under connection pooling
- **Creating pool per-request:** Pool must be application-scoped (lifespan), not request-scoped

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Connection pooling | Custom pool manager | psycopg_pool ConnectionPool | Handles min/max size, health checks, connection recycling, idle timeout |
| SQL injection prevention | String formatting | psycopg parameterized queries (%s placeholders) | Automatic escaping and type handling |
| Docker health checks | Custom readiness scripts | pg_isready built-in command | Standard PostgreSQL tool, handles connection testing reliably |
| Coverage enforcement | Custom coverage scripts | pytest-cov --cov-fail-under | Integrates with pytest, configurable in pyproject.toml |
| pgvector setup | Manual extension compilation | pgvector/pgvector:pg16 image | Extension pre-compiled and installed |

**Key insight:** The project's existing `SQLiteCheckpointStore` / `SQLiteMemoStore` / `SQLiteRunStore` are already well-designed with clean interfaces. The Postgres implementations should mirror them exactly, making the swap trivial at the factory/lifespan level.

## Common Pitfalls

### Pitfall 1: Sync vs Async Store Mismatch
**What goes wrong:** Attempting to use async Postgres calls from synchronous graph node functions causes "cannot use async within sync" errors or event loop conflicts.
**Why it happens:** graph.py nodes run synchronously (they're wrapped by `_sequential_node`). The LangGraph compiled graph runs them in a sync context. Even when the API layer uses `anyio.to_thread.run_sync` to run the graph, inside the thread the code is synchronous.
**How to avoid:** Use psycopg's sync `ConnectionPool` for CheckpointStore and MemoStore. Only RunStore needs async (and it already wraps sync calls with `anyio.to_thread.run_sync`).
**Warning signs:** `RuntimeError: cannot use await outside async function` or `RuntimeError: This event loop is already running`

### Pitfall 2: Prepared Statement Conflicts
**What goes wrong:** `psycopg.errors.DuplicatePreparedStatement: prepared statement "_pg3_0" already exists`
**Why it happens:** psycopg caches prepared statements per connection. When connections are reused from a pool, stale prepared statements can conflict.
**How to avoid:** Set `prepare_threshold=0` in connection kwargs to disable prepared statement caching. This is required by both the langgraph-checkpoint-postgres docs and multiple GitHub issues.
**Warning signs:** Intermittent SQL errors under concurrent requests.

### Pitfall 3: Pool Lifecycle Mismatch
**What goes wrong:** "the pool 'pool-1' is already closed" errors during request handling.
**Why it happens:** Pool created in a local scope (e.g., inside a function) exits its context manager before the application finishes using it.
**How to avoid:** Create pool at application startup (FastAPI lifespan), close at shutdown. Store on `app.state`.
**Warning signs:** Errors that appear after the first request but not during startup.

### Pitfall 4: Docker Init Script Ordering
**What goes wrong:** Tables reference pgvector `vector` type before the extension is created. Or init scripts run in wrong order.
**Why it happens:** `/docker-entrypoint-initdb.d/` scripts execute in alphabetical order. If the extension creation script sorts after the table creation script, it fails.
**How to avoid:** Number scripts explicitly: `001_init.sql` (extension + base tables), `002_foundation.sql` (v2 tables with vector columns). Use `.sh` script for `CREATE EXTENSION` for reliability.
**Warning signs:** `type "vector" does not exist` errors on first container start.

### Pitfall 5: Docker Init Scripts Only Run on Empty Database
**What goes wrong:** After modifying SQL init scripts, restarting the container does not apply changes.
**Why it happens:** PostgreSQL Docker image only runs `/docker-entrypoint-initdb.d/` scripts when the data directory is empty (first start only).
**How to avoid:** Use `docker-compose down -v` to wipe the named volume before restarting with schema changes. Document this clearly.
**Warning signs:** Schema changes not appearing after container restart.

### Pitfall 6: Coverage Threshold with Postgres Tests
**What goes wrong:** Tests requiring Postgres fail in environments without Postgres, breaking coverage calculation.
**Why it happens:** Postgres-specific tests can't run in SQLite-only environments.
**How to avoid:** Mark Postgres tests with `@pytest.mark.postgres` and skip when `DATABASE_URL` is not set. CI matrix handles both backends.
**Warning signs:** Tests passing locally (with Postgres) but failing in CI or on other developer machines.

### Pitfall 7: autocommit=True Required for psycopg
**What goes wrong:** Checkpoint data not persisted; tables not created by setup().
**Why it happens:** psycopg defaults to transaction mode. Without autocommit, DDL and DML may not commit.
**How to avoid:** Always pass `autocommit=True` in connection kwargs. This is documented by langgraph-checkpoint-postgres and psycopg docs.
**Warning signs:** Data visible in same connection but not in others; setup() appears to succeed but tables don't exist.

## Code Examples

### PostgresCheckpointStore Implementation
```python
# Source: mirrors SQLiteCheckpointStore (checkpoint_store.py, 126 lines)
import json
from typing import Any
from psycopg_pool import ConnectionPool
from agentic_workflows.orchestration.langgraph.state_schema import RunState, utc_now_iso

class PostgresCheckpointStore:
    """Postgres implementation matching SQLiteCheckpointStore API."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def save(self, *, run_id: str, step: int, node_name: str, state: RunState) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO graph_checkpoints (run_id, step, node_name, state_json, created_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (run_id, step, node_name, json.dumps(state, sort_keys=True, default=str), utc_now_iso()),
            )

    def load_latest(self, run_id: str) -> RunState | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT state_json FROM graph_checkpoints "
                "WHERE run_id = %s ORDER BY step DESC, id DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT step, node_name, created_at FROM graph_checkpoints "
                "WHERE run_id = %s ORDER BY id ASC",
                (run_id,),
            ).fetchall()
        return [{"step": r[0], "node_name": r[1], "created_at": r[2]} for r in rows]

    def list_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT run_id, MAX(step) AS step_count, "
                "MAX(node_name) AS node_name, MAX(created_at) AS timestamp "
                "FROM graph_checkpoints GROUP BY run_id "
                "ORDER BY MAX(id) DESC LIMIT %s",
                (limit,),
            ).fetchall()
        return [{"run_id": r[0], "step_count": r[1], "node_name": r[2], "timestamp": r[3]} for r in rows]

    def load_latest_run(self) -> RunState | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT state_json FROM graph_checkpoints ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return json.loads(row[0]) if row else None
```

### PostgresRunStore Implementation
```python
# Source: mirrors SQLiteRunStore (storage/sqlite.py, 214 lines)
import json
from datetime import UTC, datetime
from typing import Any
import anyio
from psycopg_pool import ConnectionPool

class PostgresRunStore:
    """Postgres implementation of RunStore protocol, using sync pool + anyio wrapping."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    async def initialize(self) -> None:
        """No-op -- tables created by init scripts."""

    async def save_run(self, run_id: str, *, status: str, **fields: Any) -> None:
        def _save() -> None:
            with self._pool.connection() as conn:
                conn.execute(
                    "INSERT INTO runs (run_id, status, user_input, prior_context_json, "
                    "client_ip, request_headers_json, result_json, created_at, "
                    "missions_completed, tools_used_json) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (run_id, status, fields.get("user_input"),
                     _to_json(fields.get("prior_context")),
                     fields.get("client_ip"),
                     _to_json(fields.get("request_headers")),
                     _to_json(fields.get("result")),
                     datetime.now(UTC).isoformat(),
                     fields.get("missions_completed", 0),
                     _to_json(fields.get("tools_used"))),
                )
        await anyio.to_thread.run_sync(_save)

    # ... get_run, list_runs, update_run follow same pattern

    def close(self) -> None:
        """Pool is closed externally at lifespan shutdown."""
```

### FastAPI Lifespan Store Selection
```python
# Source: extends existing api/app.py lifespan pattern
import os
from psycopg_pool import ConnectionPool

@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    db_url = os.environ.get("DATABASE_URL")
    pool = None

    if db_url:
        pool = ConnectionPool(
            conninfo=db_url,
            min_size=2,
            max_size=10,
            open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0},
        )
        pool.open(wait=True)  # sync open

        run_store = PostgresRunStore(pool)
        checkpoint_store = PostgresCheckpointStore(pool)
        memo_store = PostgresMemoStore(pool)
        log.info("api.startup", storage="postgres", pool_size=10)
    else:
        run_store = SQLiteRunStore()
        checkpoint_store = SQLiteCheckpointStore()
        memo_store = SQLiteMemoStore()
        log.info("api.startup", storage="sqlite")

    orchestrator = LangGraphOrchestrator(
        memo_store=memo_store,
        checkpoint_store=checkpoint_store,
    )
    application.state.orchestrator = orchestrator
    application.state.run_store = run_store
    # ... rest of lifespan

    yield

    if pool:
        pool.close()
    else:
        run_store.close()
```

### SQL Init Script (001_init.sql)
```sql
-- db/migrations/001_init.sql
-- Base schema for agentic_workflows

-- Runs table (RunStore)
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

-- Graph checkpoints (CheckpointStore)
CREATE TABLE IF NOT EXISTS graph_checkpoints (
    id                  SERIAL PRIMARY KEY,
    run_id              TEXT NOT NULL,
    step                INTEGER NOT NULL,
    node_name           TEXT NOT NULL,
    state_json          TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_graph_checkpoints_run_step
    ON graph_checkpoints(run_id, step);

-- Memo entries (MemoStore)
CREATE TABLE IF NOT EXISTS memo_entries (
    id                  SERIAL PRIMARY KEY,
    run_id              TEXT NOT NULL,
    namespace           TEXT NOT NULL,
    key                 TEXT NOT NULL,
    value_json          TEXT NOT NULL,
    value_hash          TEXT NOT NULL,
    source_tool         TEXT NOT NULL,
    step                INTEGER NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_memo_entries_run_key
    ON memo_entries(run_id, namespace, key);
```

### SQL Init Script (002_foundation.sql)
```sql
-- db/migrations/002_foundation.sql
-- pgvector extension + v2 foundation tables (empty, no pipelines yet)

CREATE EXTENSION IF NOT EXISTS vector;

-- Task run history (v2 context management)
CREATE TABLE IF NOT EXISTS task_runs (
    id                  SERIAL PRIMARY KEY,
    run_id              TEXT NOT NULL,
    task_description    TEXT NOT NULL,
    result_summary      TEXT,
    tools_used          TEXT[],
    success             BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- File chunks with embeddings (v2 context management)
CREATE TABLE IF NOT EXISTS file_chunks (
    id                  SERIAL PRIMARY KEY,
    file_path           TEXT NOT NULL,
    chunk_index         INTEGER NOT NULL,
    content             TEXT NOT NULL,
    embedding           vector(1536),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Solved task embeddings (v2 context management)
CREATE TABLE IF NOT EXISTS solved_tasks (
    id                  SERIAL PRIMARY KEY,
    task_description    TEXT NOT NULL,
    solution_summary    TEXT NOT NULL,
    embedding           vector(1536),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Dockerfile
```dockerfile
# Dockerfile -- single-stage build (user chose simplicity)
FROM python:3.12-slim

WORKDIR /app

# Install system deps for psycopg binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]" || pip install --no-cache-dir .

COPY . .
RUN pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["uvicorn", "agentic_workflows.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

### CI Workflow with Postgres Service
```yaml
# Source: GitHub Docs - Creating PostgreSQL service containers
name: CI

on:
  push:
    branches: ["**"]
  pull_request:
    branches: [main]

jobs:
  quality:
    name: Lint, Typecheck, Test
    runs-on: ubuntu-latest

    strategy:
      matrix:
        backend: [sqlite, postgres]

    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: test_agentic
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: ruff check src/ tests/
      - run: mypy src/
      - name: Test (SQLite)
        if: matrix.backend == 'sqlite'
        run: pytest tests/ -q --cov=src/agentic_workflows --cov-fail-under=80
        env:
          P1_PROVIDER: scripted
      - name: Test (Postgres)
        if: matrix.backend == 'postgres'
        run: pytest tests/ -q --cov=src/agentic_workflows --cov-fail-under=80
        env:
          P1_PROVIDER: scripted
          DATABASE_URL: postgresql://test:test@localhost:5432/test_agentic

  docker-build:
    name: Docker Build Test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t agentic-workflows-test .
```

### pytest-cov Configuration
```toml
# In pyproject.toml [tool.pytest.ini_options]
addopts = "--cov=src/agentic_workflows --cov-report=term-missing --cov-fail-under=80"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| asyncpg driver | psycopg (Psycopg 3) | 2024 | LangGraph ecosystem standardized on psycopg; async support built-in |
| psycopg2 | psycopg (v3) | 2023-2024 | Modern Python async, type hints, connection pooling built-in |
| SQLite in production | PostgreSQL | Always | SQLite has write locking under concurrent access; Postgres handles concurrent writes natively |
| Alembic migrations | Raw SQL for small projects | N/A | Alembic adds ORM-like complexity; raw SQL is explicit and learnable |
| docker-compose v1 (docker-compose) | docker compose v2 (docker compose) | 2023 | v2 is built into Docker CLI; v1 standalone binary deprecated |

**Deprecated/outdated:**
- `asyncpg` as default for LangGraph Postgres: langgraph-checkpoint-postgres uses psycopg, not asyncpg
- `docker-compose` (hyphenated, standalone): use `docker compose` (space, Docker CLI plugin) -- but both work with the YAML file
- Opening `AsyncConnectionPool` in constructor: deprecated by psycopg; use `open=False` then explicit `open()`

## Open Questions

1. **Sync vs Async Pool Choice**
   - What we know: CheckpointStore and MemoStore are called synchronously from graph nodes. RunStore is called from async FastAPI handlers but wraps sync calls with anyio.
   - What's unclear: Whether to use one sync pool for all three stores (simplest) or separate sync/async pools.
   - Recommendation: Single sync `ConnectionPool` for all three. RunStore wraps with `anyio.to_thread.run_sync` (matches existing SQLite pattern). Avoids pool management complexity.

2. **Coverage Baseline**
   - What we know: 536 tests currently pass. Project has ~66 test files.
   - What's unclear: Current coverage percentage (not measured yet).
   - Recommendation: Run `pytest --cov=src/agentic_workflows --cov-report=term-missing` before setting threshold. If baseline is below 80%, either lower threshold or add targeted tests. The 80% threshold is a user decision.

3. **psycopg[binary] vs psycopg[c]**
   - What we know: `psycopg[binary]` bundles libpq, no system deps needed. `psycopg[c]` compiles against system libpq.
   - What's unclear: Whether Docker image should use [binary] or [c] (with apt-get libpq-dev).
   - Recommendation: Use `psycopg[binary]` in pyproject.toml for simplicity. Works in both Docker and local dev without system deps.

4. **Docker init scripts: .sql vs .sh**
   - What we know: Some users report `CREATE EXTENSION vector` failing in `.sql` files in `/docker-entrypoint-initdb.d/`. Shell scripts are more reliable.
   - What's unclear: Whether this is fixed in recent pgvector/pgvector images.
   - Recommendation: Use `.sh` wrapper for extension creation to be safe. SQL for table creation.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.24+ + pytest-cov 6.x |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/unit/ -q -x` |
| Full suite command | `pytest tests/ -q --cov=src/agentic_workflows --cov-fail-under=80` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PROD-03 | PostgresCheckpointStore save/load matches SQLite behavior | unit | `pytest tests/unit/test_checkpoint_postgres.py -x` | No -- Wave 0 |
| PROD-03 | PostgresRunStore save/get/list/update matches SQLite behavior | unit | `pytest tests/unit/test_run_store_postgres.py -x` | No -- Wave 0 |
| PROD-03 | PostgresMemoStore put/get/list/delete matches SQLite behavior | unit | `pytest tests/unit/test_memo_postgres.py -x` | No -- Wave 0 |
| PROD-03 | ENV-based store switching selects correct backend | unit | `pytest tests/unit/test_store_factory.py -x` | No -- Wave 0 |
| PROD-04 | Docker build succeeds | smoke | `docker build -t test .` | No -- CI only |
| PROD-04 | docker-compose up starts both services | integration | `docker compose up -d && curl localhost:8000/health` | No -- manual/CI |
| PROD-04 | Data persists across container restart | integration | Manual verification | No -- manual |
| PROD-05 | CI workflow syntax valid | smoke | `gh workflow run ci.yml --ref $(git branch --show-current)` | .github/workflows/ci.yml exists |
| PROD-05 | pytest-cov enforces 80% threshold | unit | `pytest tests/ --cov=src/agentic_workflows --cov-fail-under=80` | No -- config only |
| PROD-03 | 5 concurrent requests produce no locking errors | integration | `pytest tests/integration/test_concurrent_postgres.py -x` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/unit/ -q -x`
- **Per wave merge:** `pytest tests/ -q --cov=src/agentic_workflows --cov-fail-under=80`
- **Phase gate:** Full suite green + Docker build green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_checkpoint_postgres.py` -- covers PROD-03 checkpoint
- [ ] `tests/unit/test_run_store_postgres.py` -- covers PROD-03 run store
- [ ] `tests/unit/test_memo_postgres.py` -- covers PROD-03 memo store
- [ ] `tests/unit/test_store_factory.py` -- covers PROD-03 ENV switching
- [ ] `tests/integration/test_concurrent_postgres.py` -- covers PROD-03 concurrency
- [ ] `pytest-cov` added to dev dependencies
- [ ] Postgres test fixtures in `tests/conftest.py` (skip if DATABASE_URL not set)

## Sources

### Primary (HIGH confidence)
- Project source code: `storage/protocol.py`, `storage/sqlite.py`, `checkpoint_store.py`, `memo_store.py`, `api/app.py`, `graph.py` -- read directly
- [langgraph-checkpoint-postgres PyPI](https://pypi.org/project/langgraph-checkpoint-postgres/) -- v3.0.4, uses psycopg driver
- [langgraph-checkpoint-postgres GitHub source](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/langgraph/checkpoint/postgres/__init__.py) -- confirmed psycopg imports, not asyncpg
- [psycopg_pool API docs](https://www.psycopg.org/psycopg3/docs/api/pool.html) -- AsyncConnectionPool and ConnectionPool API
- [GitHub Docs: PostgreSQL service containers](https://docs.github.com/en/actions/use-cases-and-examples/using-containerized-services/creating-postgresql-service-containers) -- CI configuration

### Secondary (MEDIUM confidence)
- [AsyncPostgresSaver Leeroopedia](https://leeroopedia.com/index.php/Implementation:Langchain_ai_Langgraph_AsyncPostgresSaver) -- confirms psycopg async driver, constructor signature
- [LangGraph GitHub Issue #4214](https://github.com/langchain-ai/langgraph/issues/4214) -- pool lifecycle mismatch pitfall
- [LangGraph GitHub Issue #2755](https://github.com/langchain-ai/langgraph/issues/2755) -- prepared statement conflicts, prepare_threshold=0 fix
- [pgvector GitHub Issue #355](https://github.com/pgvector/pgvector/issues/355) -- CREATE EXTENSION in .sql init scripts can fail
- [pytest-cov docs](https://pytest-cov.readthedocs.io/en/latest/config.html) -- fail-under configuration

### Tertiary (LOW confidence)
- Docker Compose examples from Medium/DEV.to -- verified patterns against official docs

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- psycopg confirmed as langgraph-checkpoint-postgres dependency via PyPI and source code
- Architecture: HIGH -- based on direct reading of 5 project source files + API compatibility analysis
- Pitfalls: HIGH -- sourced from real GitHub issues with confirmed fixes
- Driver mismatch finding: HIGH -- verified by reading actual source imports

**Research date:** 2026-03-06
**Valid until:** 2026-04-06 (stable ecosystem, 30 days)
