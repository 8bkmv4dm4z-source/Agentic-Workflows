# Phase 7 Walkthrough: Production Persistence, Docker, and CI

Phase 7 replaced SQLite with Postgres for production persistence, containerized the
full stack with Docker Compose, and hardened CI with a dual-backend test matrix and
coverage enforcement. This walkthrough explains every layer of that transition --
Docker concepts for newcomers, the Postgres persistence architecture, the sync/async
pool decision, and the CI pipeline design.

---

## What Changed

### Files Created

| File | Purpose |
|------|---------|
| `src/agentic_workflows/storage/checkpoint_protocol.py` | CheckpointStore Protocol (structural subtyping) |
| `src/agentic_workflows/storage/memo_protocol.py` | MemoStore Protocol (structural subtyping) |
| `src/agentic_workflows/orchestration/langgraph/checkpoint_postgres.py` | PostgresCheckpointStore implementation |
| `src/agentic_workflows/orchestration/langgraph/memo_postgres.py` | PostgresMemoStore implementation |
| `src/agentic_workflows/storage/postgres.py` | PostgresRunStore implementation |
| `db/migrations/001_init.sql` | Core tables: runs, graph_checkpoints, memo_entries |
| `db/migrations/002_foundation.sql` | pgvector extension + v2 foundation tables |
| `Dockerfile` | Single-stage python:3.12-slim FastAPI image |
| `.dockerignore` | Build context exclusions |
| `docker-compose.yml` | Postgres + FastAPI service orchestration |
| `.github/workflows/ci.yml` | CI pipeline with sqlite/postgres matrix |

### Files Modified

| File | Change |
|------|--------|
| `src/agentic_workflows/api/app.py` | Store factory in lifespan -- DATABASE_URL switches backend |
| `pyproject.toml` | Added psycopg[binary], psycopg_pool, pytest-cov |
| `.env.example` | Added DATABASE_URL documentation |
| `Makefile` | Added docker-build, docker-up, docker-down, docker-reset, docker-logs |

---

## Docker Concepts

Docker is a platform that packages an application and everything it needs to run --
code, runtime, libraries, configuration -- into a single portable unit called a
**container**. You ship the container, not the app.

Before Docker, deploying software meant wrestling with environment differences: your
machine runs Python 3.12 with psycopg 3.2, the server runs Python 3.9 with psycopg 2.9.
The app breaks. Docker eliminates this by making the environment part of the artifact.

### Images vs Containers

A Docker **image** is a read-only blueprint -- like a class definition. It contains the
OS layer, installed packages, your application code, and a startup command. An image is
built from a `Dockerfile` and can be stored in a registry (Docker Hub, GitHub Container
Registry).

A **container** is a running instance of an image -- like an object instantiated from a
class. Multiple containers can run from the same image simultaneously. Each container
has its own filesystem, network stack, and process space. It cannot affect the host
system or other containers (unless you explicitly allow it via volumes or port mappings).

This matters because it gives you isolation without the overhead of a full virtual
machine. Containers share the host OS kernel -- they start in milliseconds and use
megabytes, not the gigabytes a VM requires.

### Volumes

A Docker **volume** is a persistent storage location that survives container restarts.
Without a volume, any data written inside a container is lost when the container stops.

In this project, the named volume `pgdata` stores the Postgres data directory. When you
run `docker compose down`, the containers stop but `pgdata` survives -- your database
persists. When you run `docker compose down -v`, the `-v` flag explicitly deletes the
volume, wiping the database. This is how you reset the schema after migration changes.

### Docker Compose

Docker Compose is a tool for defining multi-container systems declaratively in a single
YAML file. Instead of starting each service manually with separate `docker run` commands,
you declare all services, their dependencies, volumes, and networking in
`docker-compose.yml` and start everything with `docker compose up`.

### Health Checks

A health check tells Docker how to determine if a service is actually ready to accept
connections, not just running. In this project, the Postgres container uses
`pg_isready -U agentic` -- a standard PostgreSQL tool that tests whether the server
accepts connections. The API service uses `depends_on: condition: service_healthy` to
wait for Postgres to pass its health check before starting. Without this, the API would
crash on startup because it tries to open a connection pool to a database that is not
ready yet.

### The Project Dockerfile -- Line by Line

```dockerfile
FROM python:3.12-slim                    # Base layer: Debian slim + Python 3.12
WORKDIR /app                             # Set working directory inside the container
COPY pyproject.toml .                    # Copy dependency manifest (layer cached separately)
COPY src/ src/                           # Copy application source code
RUN pip install --no-cache-dir .         # Install production dependencies
EXPOSE 8000                              # Document the port (informational only)
CMD ["uvicorn", "agentic_workflows.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

This is a single-stage build. The `psycopg[binary]` package bundles `libpq` (the
Postgres C client library), so no system-level `apt-get` dependencies are needed. The
`pyproject.toml` is copied before `src/` so that Docker can cache the `pip install`
layer -- if only source code changes, the dependency layer is reused and rebuilds take
seconds instead of minutes.

### docker-compose.yml -- Service Topology

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16              # Pre-built Postgres 16 with pgvector extension
    environment:
      POSTGRES_USER: agentic
      POSTGRES_PASSWORD: agentic
      POSTGRES_DB: agentic_workflows
    ports:
      - "5433:5432"                            # Host port 5433 -> container port 5432
    volumes:
      - pgdata:/var/lib/postgresql/data        # Named volume for data persistence
      - ./db/migrations:/docker-entrypoint-initdb.d  # SQL init scripts
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "agentic"]
      interval: 5s
      timeout: 5s
      retries: 5

  api:
    build: .                                    # Build from local Dockerfile
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://agentic:agentic@postgres:5432/agentic_workflows
      P1_PROVIDER: ${P1_PROVIDER:-openai}
    depends_on:
      postgres:
        condition: service_healthy              # Wait for Postgres health check
    env_file:
      - path: .env
        required: false

volumes:
  pgdata:                                       # Named volume declaration
```

Two key networking details to understand. Inside Docker, containers talk to each other
via service name -- the `api` service connects to `postgres:5432` using Docker's
internal DNS. From your WSL2 terminal outside Docker, you connect via the mapped host
port: `localhost:5433`. These are two different addresses for the same database.

The port mapping is `5433:5432` (not the default `5432:5432`) because Docker Desktop
on WSL2 has a known issue where it internally occupies port 5432, preventing containers
from binding to it on the host. The container still listens on 5432 internally -- only
the host-side port changes. This quirk does not affect production Linux servers or CI,
where Docker binds `0.0.0.0:5432` correctly.

The `./db/migrations:/docker-entrypoint-initdb.d` volume mount makes SQL files in
`db/migrations/` auto-execute on the first container start (when the data directory is
empty). After that, Postgres considers itself initialized and will not re-run them --
this is why `docker compose down -v` is needed to apply schema changes.

---

## Postgres Persistence Architecture

### The Three Stores

The system uses three persistence stores, each serving a distinct purpose:

| Store | Purpose | Write frequency |
|-------|---------|-----------------|
| **CheckpointStore** | Saves full `RunState` at each graph step for resumability | ~30 writes per run |
| **MemoStore** | Caches tool results (e.g., write_file content) to prevent re-computation | ~5 writes per run |
| **RunStore** | Records API-level run metadata (status, input, result, timing) | 2 writes per run (create + complete) |

Each store has two implementations: a SQLite version (for dev/test) and a Postgres
version (for production). Both implement the same interface, so the rest of the
application is unaware of which backend is active.

### Protocol Abstractions

RunStore already had a `Protocol` from Phase 6. Phase 7 added Protocols for
CheckpointStore and MemoStore:

```python
# storage/checkpoint_protocol.py
@runtime_checkable
class CheckpointStore(Protocol):
    def save(self, *, run_id: str, step: int, node_name: str, state: RunState) -> None: ...
    def load_latest(self, run_id: str) -> RunState | None: ...
    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]: ...
    def list_runs(self, limit: int = 10) -> list[dict[str, Any]]: ...
    def load_latest_run(self) -> RunState | None: ...
```

This matters because Python Protocols use structural subtyping -- any class with
matching method signatures satisfies the Protocol, without inheriting from it. The
SQLite and Postgres implementations never reference these Protocols in their code;
they just happen to have the right methods. The Protocols exist for type checking
and documentation, not runtime dispatch.

### The Store Factory Pattern

The store factory lives in `app.py`'s lifespan function. It checks for the
`DATABASE_URL` environment variable at startup and creates either SQLite or Postgres
stores accordingly:

```python
@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    db_url = os.environ.get("DATABASE_URL")
    pool = None

    if db_url:
        from psycopg_pool import ConnectionPool as PgConnectionPool
        from agentic_workflows.orchestration.langgraph.checkpoint_postgres import PostgresCheckpointStore
        from agentic_workflows.orchestration.langgraph.memo_postgres import PostgresMemoStore
        from agentic_workflows.storage.postgres import PostgresRunStore

        pool = PgConnectionPool(
            conninfo=db_url, min_size=2, max_size=10, open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0},
        )
        pool.open(wait=True)

        run_store = PostgresRunStore(pool)
        checkpoint_store = PostgresCheckpointStore(pool)
        memo_store = PostgresMemoStore(pool)
    else:
        from agentic_workflows.orchestration.langgraph.checkpoint_store import SQLiteCheckpointStore
        from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore

        run_store = SQLiteRunStore()
        checkpoint_store = SQLiteCheckpointStore()
        memo_store = SQLiteMemoStore()

    orchestrator = LangGraphOrchestrator(
        memo_store=memo_store, checkpoint_store=checkpoint_store
    )
    # ... rest of startup
```

The imports are lazy and conditional -- Postgres store imports only happen when
`DATABASE_URL` is set. This means a developer without `psycopg` installed can still
run the project in SQLite mode without import errors.

### SQL Init Scripts

**`001_init.sql`** creates the three core tables that back the stores:
- `runs` -- one row per API request, keyed by `run_id` (UUID)
- `graph_checkpoints` -- one row per graph step, with full `state_json`
- `memo_entries` -- one row per cached tool result, unique on `(run_id, namespace, key)`

**`002_foundation.sql`** enables the pgvector extension and creates three v2 foundation
tables: `task_runs`, `file_chunks` (with a `vector(1536)` column), and `solved_tasks`
(also with a `vector(1536)` column). These tables are empty -- no code writes to them
yet. They establish the schema for future semantic search and RAG features that will use
embedding similarity to retrieve relevant prior task results and file context.

The scripts are numbered to control execution order. The `002_foundation.sql` script
must run after `001_init.sql` because it depends on a clean database state, and the
pgvector `CREATE EXTENSION` must happen before any tables use the `vector` type.

---

## Sync vs Async Pool Decision

### The Problem

CheckpointStore and MemoStore are called synchronously from graph node functions. The
LangGraph compiled graph runs nodes in a sync context -- even when the FastAPI layer
wraps the graph invocation with `anyio.to_thread.run_sync`, the code inside that thread
is synchronous Python. Attempting to use `await` from a sync function raises
`RuntimeError: cannot use await outside async function`.

RunStore, on the other hand, is called from async FastAPI route handlers.

### The Solution: Single Sync ConnectionPool

Rather than maintaining two separate pools (sync for CheckpointStore/MemoStore, async
for RunStore), the project uses a single sync `ConnectionPool` from `psycopg_pool` for
all three stores. RunStore wraps its sync pool calls with `anyio.to_thread.run_sync` --
the same pattern already used by `SQLiteRunStore` in Phase 6.

This matters because one pool means one set of connection limits to tune, one lifecycle
to manage (open at startup, close at shutdown), and one health check configuration.

### Why psycopg, Not asyncpg

The CONTEXT.md originally specified `asyncpg` as the Postgres driver. Research found
this was incompatible:

1. `langgraph-checkpoint-postgres` (LangGraph's first-party Postgres integration) uses
   `psycopg` (Psycopg 3), not `asyncpg`. Mixing two Postgres drivers in one project
   doubles connection management complexity.

2. `AsyncPostgresSaver` (LangGraph's built-in checkpointer) has API methods
   `aput(config, checkpoint, metadata, new_versions)` / `aget(config)` / `alist(config)`.
   The project's `SQLiteCheckpointStore` has `save(run_id, step, node_name, state)` /
   `load_latest(run_id)` / `list_checkpoints(run_id)`. These APIs are incompatible --
   adopting AsyncPostgresSaver would require rewriting 30+ call sites.

3. `psycopg` supports both sync and async operation from the same driver, so a single
   dependency serves all three stores.

### Connection Pool Configuration

```python
pool = PgConnectionPool(
    conninfo=db_url,
    min_size=2,                               # Keep 2 connections warm
    max_size=10,                              # Scale up under load
    open=False,                               # Don't connect in constructor
    kwargs={"autocommit": True, "prepare_threshold": 0},
)
pool.open(wait=True)                          # Explicit open with readiness wait
```

Two connection kwargs require explanation:

**`autocommit=True`** -- psycopg defaults to transaction mode, where every statement
runs inside an implicit transaction. Without autocommit, DDL statements (CREATE TABLE)
and DML statements (INSERT, UPDATE) may not persist because the transaction is never
explicitly committed. Setting `autocommit=True` means each statement commits immediately.

**`prepare_threshold=0`** -- psycopg caches prepared statements per connection. When
connections are recycled through a pool, stale prepared statements from a previous
borrower can conflict with new ones, causing `DuplicatePreparedStatement` errors.
Setting the threshold to 0 disables prepared statement caching entirely. This is the
same fix documented in `langgraph-checkpoint-postgres` and multiple psycopg GitHub
issues.

---

## CI Pipeline Architecture

### The Test Matrix

The CI workflow runs two parallel jobs via a strategy matrix:

| Matrix leg | Lint | Typecheck | Init Postgres | Test backend | Coverage |
|------------|------|-----------|---------------|--------------|----------|
| **sqlite** | ruff check | mypy | -- | SQLite (default) | 80% threshold |
| **postgres** | -- | -- | psql -f migrations | Postgres via DATABASE_URL | 80% threshold |

Lint and typecheck run only on the SQLite leg to avoid duplicate work -- these tools
check code correctness, not database behavior.

### Postgres Service Container in GitHub Actions

```yaml
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
```

GitHub Actions service containers run alongside the job runner on the same network.
The runner connects to `localhost:5432` -- no port remapping needed (the WSL2 port
quirk does not apply to CI Linux runners).

CI uses separate credentials (`test/test/test_agentic`) from local dev
(`agentic/agentic/agentic_workflows`) to prevent accidental cross-environment data
contamination.

### Why Init Scripts Run via psql in CI

In Docker Compose, init scripts auto-execute via the
`/docker-entrypoint-initdb.d/` volume mount. GitHub Actions service containers do not
support volume mounts -- they are pulled images run with `--health-cmd` options only.
So the CI pipeline explicitly runs the migration scripts with `psql`:

```yaml
- name: Init Postgres
  if: matrix.backend == 'postgres'
  run: |
    sudo apt-get update && sudo apt-get install -y --no-install-recommends postgresql-client
    PGPASSWORD=test psql -h localhost -U test -d test_agentic -f db/migrations/001_init.sql
    PGPASSWORD=test psql -h localhost -U test -d test_agentic -f db/migrations/002_foundation.sql
```

### Docker Build Test Job

A separate `docker-build` job builds the image to verify the Dockerfile is valid:

```yaml
docker-build:
  name: Docker Build Test
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - run: docker build -t agentic-workflows-test .
```

This is build-only, no push. It catches Dockerfile syntax errors, missing files, and
dependency installation failures before they reach a deployment environment.

### Coverage Enforcement

Both matrix legs run `pytest --cov=src/agentic_workflows --cov-report=term-missing --cov-fail-under=80`. The `--cov-fail-under=80` flag causes pytest to exit with a
non-zero code if line coverage drops below 80%, failing the CI job.

Coverage is enforced only in CI, not in the default `pytest` configuration
(`pyproject.toml`). This avoids slowing down local development with coverage
instrumentation on every test run.

### ScriptedProvider in CI

All CI test runs use `P1_PROVIDER: scripted`. The `ScriptedProvider` returns
pre-defined LLM responses from a fixture, so no live API credentials (OpenAI, Groq,
Ollama) are needed in CI. This keeps CI deterministic and cost-free.

---

## Common Operations

**Start the full stack:**
```bash
docker compose up -d           # Detached mode (background)
docker compose logs -f         # Follow logs from both services
```

**Start just Postgres for local dev** (run Python locally, connect to containerized DB):
```bash
docker compose up -d postgres
export DATABASE_URL=postgresql://agentic:agentic@localhost:5433/agentic_workflows
pytest tests/ -q               # Tests run against Postgres
```

**Reset the database after schema changes:**
```bash
docker compose down -v         # Stop containers AND delete pgdata volume
docker compose up -d           # Restart -- init scripts re-execute on empty DB
```

**Run Postgres tests locally:**
```bash
export DATABASE_URL=postgresql://agentic:agentic@localhost:5433/agentic_workflows
pytest tests/unit/test_checkpoint_postgres.py \
       tests/unit/test_run_store_postgres.py \
       tests/unit/test_memo_postgres.py \
       tests/integration/test_concurrent_postgres.py -v
```

**Check container status:**
```bash
docker compose ps              # Running services and port mappings
docker compose logs postgres   # Postgres-specific logs
```

---

## Known Constraints and Gotchas

**Docker init scripts only run on empty database.** The PostgreSQL Docker image runs
`/docker-entrypoint-initdb.d/` scripts only when the data directory is empty (first
start). After modifying SQL migration scripts, you must run `docker compose down -v`
to wipe the volume before restarting. Forgetting this is the most common source of
"my schema changes aren't showing up."

**`prepare_threshold=0` is required.** Without it, psycopg caches prepared statements
per connection. When a pooled connection is reused, stale prepared statements cause
`DuplicatePreparedStatement` errors -- intermittent failures that are difficult to
diagnose because they depend on which connection the pool hands out.

**`psycopg[binary]` bundles libpq.** No system-level `apt-get install libpq-dev` is
needed. The binary wheel includes the compiled C extension and the PostgreSQL client
library. This simplifies both the Dockerfile (no multi-stage build) and local dev
setup.

**Postgres tests auto-skip without DATABASE_URL.** Test files use
`pytest.importorskip("psycopg_pool")` at module level. When `psycopg_pool` is not
installed or `DATABASE_URL` is not set, the entire test module is skipped rather than
failing. This allows the SQLite CI leg to run without Postgres test failures.

**WSL2 port mapping is 5433:5432, not 5432:5432.** Docker Desktop on WSL2 internally
occupies port 5432, preventing containers from binding to it on the host. The fix is
straightforward: map to host port 5433 instead. Inside Docker, containers still
communicate on port 5432 via service name (`postgres:5432`). CI runners on Linux are
unaffected -- they use the standard 5432 port.

**`conftest.py` pg_pool uses `prepare=False`.** The test fixture that creates the
Postgres connection pool passes `prepare=False` when executing multi-statement migration
SQL. Without this, psycopg attempts to prepare the multi-statement string as a single
prepared statement, which fails.

---

## References

- `.planning/phases/07-production-persistence-and-ci/07-RESEARCH.md` -- Driver choice
  analysis, pitfall catalog, architecture patterns
- `.planning/phases/07-production-persistence-and-ci/07-01-SUMMARY.md` -- Postgres store
  implementation details
- `.planning/phases/07-production-persistence-and-ci/07-03-SUMMARY.md` -- Docker and CI
  implementation details
- `src/agentic_workflows/api/app.py` -- Store factory lifespan (lines 29-76)
- `docker-compose.yml` -- Service topology and volume configuration
- `.github/workflows/ci.yml` -- CI pipeline with matrix strategy
