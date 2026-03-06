# Phase 6: Production Service Layer - Context

**Gathered:** 2026-03-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Wrap LangGraphOrchestrator.run() in a FastAPI HTTP service. POST /run streams SSE events and returns results. GET /run/{id} retrieves completed results with partial progress for in-progress runs. GET /run/{id}/stream allows reconnection to an in-progress run (same session only). GET /health and GET /tools provide service introspection. Introduce a RunStore abstraction for run persistence (SQLite now, Postgres-ready for Phase 7). Convert user_run.py to an API client. Add eval harness and HTTP contract tests. Upgrade dependencies and refactor project structure. No Dockerfile/docker-compose (Phase 7). No Postgres (Phase 7). No web UI.

</domain>

<decisions>
## Implementation Decisions

### Endpoint Surface
- **POST /run** — accepts {user_input: str, run_id?: str, prior_context?: list[dict]}. Returns SSE stream directly (not a run_id for later polling). Stream includes events for node transitions and final result.
- **GET /run/{id}** — returns completed results OR in-progress status with partial data {status: 'running', elapsed_s, missions_completed, tools_used_so_far}. Only available after the run has been initiated.
- **GET /run/{id}/stream** — reconnect to an in-progress run's SSE stream. Same session only — no cross-session access. Idempotent. Run IDs cannot be hijacked or accessed until the run returns success.
- **GET /health** — {status, provider, tool_count}
- **GET /tools** — list of {name, description} for all registered tools
- Error handling: structured JSON errors with run_id when available

### Streaming Design
- **Two tiers of SSE events:**
  - UI tier: node_start, node_end, run_complete — lightweight, for clients and user_run
  - Debug tier: full state diffs on every state change — for logging and debugging
- Events include a `type` field so clients can filter by tier
- **POST /run streams directly** — best compatibility with user_run as API client
- **Wire format:** Claude's discretion (standard SSE with event/data fields recommended)

### Concurrency and Storage
- **RunStore protocol/ABC** — abstract interface with save_run(), get_run(), list_runs(). SQLite implements now, Postgres in Phase 7. Minimal changes between phases.
- **Storage schema per run:** full RunResult fields + created_at, completed_at, status (pending/running/completed/failed) + request metadata (user_input, prior_context, client IP, request headers)
- **Graph compiled once at startup** — FastAPI lifespan event. All requests share the compiled graph. Log line at startup confirms compilation.
- **SQLite WAL mode** for concurrent read/write support (3 concurrent requests per ROADMAP)

### user_run as API Client
- user_run.py becomes an API client — talks to FastAPI service, not orchestrator directly. API is the single source of truth.
- **Rich terminal output** — use Rich (already a dependency) to render SSE node transitions, tool calls, and progress as they stream in
- **Auto-start server** — user_run.py checks if API is running; if not, spawns uvicorn in background, then connects

### Project Structure Refactor
- Reorganize src/agentic_workflows/ to accommodate API layer: api/, storage/, cli/ packages
- **Dependency upgrades** — update pyproject.toml deps to latest stable (langgraph, pydantic, fastapi, uvicorn, sse-starlette, etc.)

### Testing Strategy
- **Eval harness:** tests/eval/ with 3+ ScriptedProvider scenarios (deterministic, CI-safe)
- **HTTP contract tests:** test FastAPI endpoints directly (POST /run SSE, GET /run/{id}, error responses, concurrent requests)
- **Tool security verification:** flag to confirm _security.py guardrails work correctly in API context (already built, just verify)

### Claude's Discretion
- SSE wire format details (standard SSE recommended)
- Exact Pydantic field names and JSON serialization in response models
- Uvicorn configuration defaults (host, port, workers)
- RunStore implementation details (table schema, connection pooling)
- Additional eval scenarios beyond minimum 3
- pytest marker vs directory-based collection for evals
- Exact Rich rendering layout for user_run SSE display

</decisions>

<specifics>
## Specific Ideas

- "I want as little changes from P6 to P7" — design storage abstraction now so Postgres swap is clean
- "Single source of truth" — user_run must go through the API, not call orchestrator directly
- "No UI/UX but keep single source of truth" — no web frontend, CLI stays the interface
- POST /run streaming directly gives best compatibility with user_run as API client
- GET /run/{id}/stream stays idempotent and separate — no run ID hijacking or cross-session access

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `LangGraphOrchestrator.run()` in graph.py — sync method, returns RunResult TypedDict
- `build_tool_registry(store)` in tools_registry.py — enumerate all 24 tools for GET /tools
- `ScriptedProvider` in tests/conftest.py — deterministic provider for evals
- `_security.py` — bash/HTTP/path/size guardrails already implemented, env-var gated
- `RunResult` TypedDict in state_schema.py — typed return contract for API responses
- `Rich` library already in dependencies — reuse for user_run SSE rendering
- `httpx` already in dependencies — use as API client in user_run.py

### Established Patterns
- Pydantic v2 with ConfigDict (not class Config) — use for all API models
- Env-based configuration via os.environ.get() with defaults
- Tools return {"error": ...} dicts on failure, never raise
- SQLite for checkpoints (.tmp/langgraph_checkpoints.db) and memos (.tmp/memo_store.db)

### Integration Points
- graph.py LangGraphOrchestrator — the function the API wraps
- tools_registry.py build_tool_registry() — tool enumeration for /tools
- run.py — existing CLI entrypoint; API replaces this as primary interface
- user_run.py — converted from direct orchestrator caller to API client
- pyproject.toml — add fastapi, uvicorn, sse-starlette dependencies
- .env.example — add API host/port configuration

</code_context>

<deferred>
## Deferred Ideas

- Containerization (Dockerfile, docker-compose) — Phase 7
- Postgres migration (AsyncPostgresSaver) — Phase 7
- Authentication/authorization on API endpoints — Phase 7 or beyond
- Rate limiting and request validation middleware — Phase 7
- Full sandbox for run_bash (seccomp, containers) — Phase 7
- Web UI frontend — explicitly rejected, CLI stays
- Multi-turn conversation API (session management) — v2 feature
- OpenAPI schema publishing and client SDK generation — post-Phase 6
- Async orchestrator rewrite — future refactor
- Live-provider eval scenarios (manual, not CI) — future phase

</deferred>

---

*Phase: 06-fastapi-service-layer*
*Context gathered: 2026-03-05*
