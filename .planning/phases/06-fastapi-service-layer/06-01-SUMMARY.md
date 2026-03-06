---
phase: 06-fastapi-service-layer
plan: 01
subsystem: api
tags: [fastapi, pydantic, sqlite, sse, uvicorn, anyio]

requires:
  - phase: 05-observability
    provides: LangGraphOrchestrator, RunResult TypedDict, tools registry
provides:
  - FastAPI app skeleton with lifespan graph singleton
  - Pydantic v2 request/response models (RunRequest, RunStatusResponse, HealthResponse, ToolInfo, SSEEvent, ErrorResponse)
  - SSE event builder functions (node_start, node_end, run_complete, state_diff, error)
  - RunStore protocol (async CRUD)
  - SQLiteRunStore with WAL mode and anyio thread offload
  - GET /health and GET /tools routes
affects: [06-02, 06-03, 07-postgres]

tech-stack:
  added: [fastapi, uvicorn, sse-starlette, anyio, httpx-sse]
  patterns: [lifespan singleton, Protocol-based storage abstraction, anyio thread offload for sync SQLite]

key-files:
  created:
    - src/agentic_workflows/api/app.py
    - src/agentic_workflows/api/models.py
    - src/agentic_workflows/api/sse.py
    - src/agentic_workflows/api/routes/health.py
    - src/agentic_workflows/api/routes/tools.py
    - src/agentic_workflows/storage/protocol.py
    - src/agentic_workflows/storage/sqlite.py
    - tests/unit/test_api_models.py
    - tests/unit/test_run_store.py
  modified:
    - pyproject.toml
    - .env.example

key-decisions:
  - "RunStore uses typing.Protocol (not ABC) for structural subtyping compatibility with future Postgres backend"
  - "SQLite sync calls wrapped in anyio.to_thread.run_sync for event-loop safety"
  - "pytest asyncio_mode=auto configured globally to avoid per-test decorator boilerplate"

patterns-established:
  - "Lifespan singleton: graph compiled once at startup, stored on app.state"
  - "Storage protocol: RunStore Protocol with save/get/list/update async methods"
  - "SSE event builders: pure functions returning dicts with type, tier, timestamp"
  - "Route organization: separate router files under api/routes/"

requirements-completed: [PROD-01]

duration: 3min
completed: 2026-03-04
---

# Phase 06 Plan 01: Foundation Summary

**FastAPI app skeleton with lifespan graph singleton, Pydantic v2 models, SQLiteRunStore (WAL), and SSE event builders**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-04T23:21:43Z
- **Completed:** 2026-03-04T23:25:02Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments
- FastAPI app with lifespan that compiles LangGraphOrchestrator once at startup
- Full set of Pydantic v2 request/response models with extra="forbid" validation
- SSE event builder functions for both UI and debug tiers
- RunStore Protocol with SQLiteRunStore (WAL mode, anyio thread offload)
- GET /health and GET /tools routes with proper response models
- 17 new unit tests (11 model/SSE + 6 storage), 525 total tests passing

## Task Commits

Each task was committed atomically:

1. **Task 1: Dependencies, models, SSE, RunStore** - `f9b91e3` (feat)
2. **Task 2: FastAPI app, routes, unit tests** - `674e423` (feat)

## Files Created/Modified
- `pyproject.toml` - Added fastapi, uvicorn, sse-starlette, anyio, httpx-sse; asyncio_mode=auto
- `src/agentic_workflows/api/__init__.py` - Package init
- `src/agentic_workflows/api/models.py` - 6 Pydantic models (RunRequest, RunStatusResponse, HealthResponse, ToolInfo, SSEEvent, ErrorResponse)
- `src/agentic_workflows/api/sse.py` - 5 SSE event builder functions with ui/debug tiers
- `src/agentic_workflows/api/app.py` - FastAPI app with lifespan singleton, error handlers
- `src/agentic_workflows/api/routes/__init__.py` - Package init
- `src/agentic_workflows/api/routes/health.py` - GET /health route
- `src/agentic_workflows/api/routes/tools.py` - GET /tools route
- `src/agentic_workflows/storage/__init__.py` - Package init
- `src/agentic_workflows/storage/protocol.py` - RunStore Protocol (runtime_checkable)
- `src/agentic_workflows/storage/sqlite.py` - SQLiteRunStore with WAL, busy_timeout, anyio offload
- `.env.example` - Added API_HOST, API_PORT, RUN_STORE_DB
- `tests/unit/test_api_models.py` - 11 tests for models and SSE builders
- `tests/unit/test_run_store.py` - 6 tests for SQLiteRunStore

## Decisions Made
- Used `typing.Protocol` (not ABC) for RunStore -- enables structural subtyping so future Postgres backend just needs matching method signatures
- Wrapped sync SQLite calls in `anyio.to_thread.run_sync` -- keeps event loop non-blocking without requiring aiosqlite dependency
- Set `asyncio_mode = "auto"` in pyproject.toml -- avoids needing `@pytest.mark.asyncio` on every async test

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- All contracts (models, protocol, SSE events) are stable for Wave 2 route implementation
- App skeleton ready for POST /runs and GET /runs/{run_id} endpoints
- RunStore ready for run persistence in route handlers

---
*Phase: 06-fastapi-service-layer*
*Completed: 2026-03-04*
