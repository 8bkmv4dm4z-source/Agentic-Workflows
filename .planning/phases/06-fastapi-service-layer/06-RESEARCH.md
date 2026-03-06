# Phase 6: Production Service Layer - Research

**Researched:** 2026-03-05
**Domain:** FastAPI + SSE + SQLite RunStore + LangGraph sync/async bridge
**Confidence:** HIGH

## Summary

Phase 6 wraps the existing synchronous `LangGraphOrchestrator.run()` in a FastAPI HTTP service with SSE streaming, a SQLite-backed RunStore abstraction, and a converted `user_run.py` API client. The central architectural challenge is bridging LangGraph's sync `_compiled.stream()` call into FastAPI's async SSE response — solved cleanly via `anyio.to_thread.run_sync()` feeding an `anyio` memory channel into `EventSourceResponse`.

The compiled graph already lives in `LangGraphOrchestrator.__init__()` (assigned to `self._compiled`). The lifespan pattern instantiates one `LangGraphOrchestrator` at startup, stores it on `app.state`, and every request handler reads it from there. SQLite WAL mode unlocks concurrent read-while-write so 3 simultaneous POST /run requests don't produce "database is locked" errors.

**Primary recommendation:** Use `sse-starlette 3.3.x` with `anyio.create_memory_object_stream` + `data_sender_callable` for the SSE boundary; use `run_in_threadpool` for the sync `LangGraphOrchestrator.run()` call on non-streaming endpoints; use `asyncio.to_thread.run_sync` inside the background producer for the streaming endpoint.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Endpoint Surface**
- POST /run — accepts {user_input: str, run_id?: str, prior_context?: list[dict]}. Returns SSE stream directly (not a run_id for later polling). Stream includes events for node transitions and final result.
- GET /run/{id} — returns completed results OR in-progress status with partial data {status: 'running', elapsed_s, missions_completed, tools_used_so_far}. Only available after the run has been initiated.
- GET /run/{id}/stream — reconnect to an in-progress run's SSE stream. Same session only — no cross-session access. Idempotent. Run IDs cannot be hijacked or accessed until the run returns success.
- GET /health — {status, provider, tool_count}
- GET /tools — list of {name, description} for all registered tools
- Error handling: structured JSON errors with run_id when available

**Streaming Design**
- Two tiers of SSE events: UI tier (node_start, node_end, run_complete) and Debug tier (full state diffs on every state change)
- Events include a `type` field so clients can filter by tier
- POST /run streams directly — best compatibility with user_run as API client
- Wire format: standard SSE with event/data fields (Claude's discretion confirmed)

**Concurrency and Storage**
- RunStore protocol/ABC — abstract interface with save_run(), get_run(), list_runs(). SQLite implements now, Postgres in Phase 7.
- Storage schema per run: full RunResult fields + created_at, completed_at, status (pending/running/completed/failed) + request metadata (user_input, prior_context, client IP, request headers)
- Graph compiled once at startup — FastAPI lifespan event. All requests share the compiled graph. Log line at startup confirms compilation.
- SQLite WAL mode for concurrent read/write support (3 concurrent requests per ROADMAP)

**user_run as API Client**
- user_run.py becomes an API client — talks to FastAPI service, not orchestrator directly.
- Rich terminal output — use Rich (already a dependency) to render SSE node transitions.
- Auto-start server — user_run.py checks if API is running; if not, spawns uvicorn in background, then connects.

**Project Structure Refactor**
- Reorganize src/agentic_workflows/ to accommodate API layer: api/, storage/, cli/ packages
- Dependency upgrades — update pyproject.toml deps to latest stable (langgraph, pydantic, fastapi, uvicorn, sse-starlette, etc.)

**Testing Strategy**
- Eval harness: tests/eval/ with 3+ ScriptedProvider scenarios (deterministic, CI-safe)
- HTTP contract tests: test FastAPI endpoints directly (POST /run SSE, GET /run/{id}, error responses, concurrent requests)
- Tool security verification: flag to confirm _security.py guardrails work correctly in API context

### Claude's Discretion
- SSE wire format details (standard SSE recommended)
- Exact Pydantic field names and JSON serialization in response models
- Uvicorn configuration defaults (host, port, workers)
- RunStore implementation details (table schema, connection pooling)
- Additional eval scenarios beyond minimum 3
- pytest marker vs directory-based collection for evals
- Exact Rich rendering layout for user_run SSE display

### Deferred Ideas (OUT OF SCOPE)
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
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PROD-01 | FastAPI service exposes POST /run (submit a mission) and GET /run/{id} (retrieve results) with request/response validation | Pydantic v2 request/response models; RunStore protocol; lifespan singleton pattern |
| PROD-02 | FastAPI service exposes GET /run/{id}/stream as a Server-Sent Events endpoint that streams step-transition events during execution | sse-starlette 3.3.x EventSourceResponse; anyio memory channel + data_sender_callable; LangGraph _compiled.stream() bridged via anyio.to_thread.run_sync |
</phase_requirements>

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | >=0.115 | HTTP framework, routing, dependency injection, lifespan | Current standard; native Pydantic v2 integration; ASGI-native |
| uvicorn | >=0.34 | ASGI server with uvloop | Standard FastAPI deployment server |
| sse-starlette | >=3.3.2 | EventSourceResponse + SSE wire protocol | Production-ready SSE for Starlette/FastAPI; W3C compliant; supports anyio memory channels |
| httpx | >=0.28 | Already in deps — use as async API client in user_run | Async SSE streaming via aiter_lines() |
| anyio | transitive | async memory channels bridging sync/async boundary | Pulled in by fastapi; create_memory_object_stream for producer/consumer SSE |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| starlette.concurrency.run_in_threadpool | (bundled) | Run sync LangGraph .run() without blocking event loop | GET /run/{id} — non-streaming full run call |
| anyio.to_thread.run_sync | (bundled) | Run sync code inside async SSE producer | POST /run SSE producer that calls _compiled.stream() |
| pytest-asyncio | >=0.24 | Already in dev deps — async test support | HTTP contract tests with AsyncClient |
| httpx-sse | >=0.4 | SSE client for test assertions | Consuming SSE in integration tests |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| sse-starlette | StreamingResponse (raw) | sse-starlette handles keep-alive pings, X-Accel-Buffering, and client disconnect detection automatically |
| anyio memory channel | asyncio.Queue | anyio is already pulled in by fastapi; memory channel integrates cleanly with data_sender_callable |
| httpx (user_run client) | requests + sseclient | httpx already in deps; async streaming with aiter_lines() avoids blocking |
| SQLite WAL mode | thread lock around writes | WAL mode is the correct SQLite-native solution; allows concurrent reads |

**Installation:**
```bash
pip install fastapi uvicorn sse-starlette
# httpx already in deps; anyio is transitive via fastapi
```

Add to pyproject.toml `[project.optional-dependencies]`:
```toml
api = ["fastapi>=0.115", "uvicorn>=0.34", "sse-starlette>=3.3"]
```
Or move to core `dependencies` since API is the primary interface after Phase 6.

---

## Architecture Patterns

### Recommended Project Structure

```
src/agentic_workflows/
├── api/
│   ├── __init__.py
│   ├── app.py          # FastAPI app + lifespan, app.state.orchestrator
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── run.py      # POST /run, GET /run/{id}, GET /run/{id}/stream
│   │   ├── health.py   # GET /health
│   │   └── tools.py    # GET /tools
│   ├── models.py       # Pydantic request/response models
│   └── sse.py          # SSE event builders (node_start, node_end, run_complete, state_diff)
├── storage/
│   ├── __init__.py
│   ├── protocol.py     # RunStore ABC (save_run, get_run, list_runs)
│   └── sqlite.py       # SQLiteRunStore — WAL mode, schema, connection-per-call
├── cli/
│   ├── __init__.py
│   └── user_run.py     # API client (moved from orchestration/langgraph/)
├── orchestration/      # unchanged
└── tools/              # unchanged
```

### Pattern 1: Lifespan Singleton — Graph Compiled Once

**What:** `LangGraphOrchestrator` is instantiated exactly once during app startup; stored on `app.state`; route handlers read it via request.app.state or Depends().

**When to use:** Any shared, expensive-to-initialize resource — compiled graph, DB pool, etc.

```python
# Source: https://fastapi.tiangolo.com/advanced/events/
from contextlib import asynccontextmanager
from fastapi import FastAPI
from agentic_workflows.orchestration.langgraph.langgraph_orchestrator import LangGraphOrchestrator
import structlog

log = structlog.get_logger("api.lifespan")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: compile graph once
    log.info("api.startup", event="compiling_graph")
    orchestrator = LangGraphOrchestrator()
    app.state.orchestrator = orchestrator
    log.info("api.startup", event="graph_compiled", tools=len(orchestrator.tools))
    yield
    # Shutdown: nothing to clean up for sync orchestrator

app = FastAPI(lifespan=lifespan)
```

### Pattern 2: SSE Streaming — Sync LangGraph via anyio Memory Channel

**What:** POST /run runs the LangGraph orchestrator in a thread pool, emits SSE events as graph nodes transition, and finally yields a `run_complete` event.

**When to use:** Any endpoint where a sync blocking function must produce a stream of events.

**Critical insight:** `LangGraphOrchestrator.run()` calls `self._compiled.invoke()` (sync). For SSE we use `self._compiled.stream(state, config, stream_mode="updates")` — also sync — inside `anyio.to_thread.run_sync()`. Each yielded `(node_name, updates)` chunk from `.stream()` is pushed into an anyio send channel; the SSE generator reads from the receive channel.

```python
# Source: sse-starlette 3.3.x docs + anyio pattern
import anyio
import json
from sse_starlette import EventSourceResponse, ServerSentEvent
from starlette.requests import Request
from agentic_workflows.orchestration.langgraph.state_schema import RunState

async def post_run(request: Request, body: RunRequest) -> EventSourceResponse:
    orchestrator: LangGraphOrchestrator = request.app.state.orchestrator
    run_store: RunStore = request.app.state.run_store

    send_stream, receive_stream = anyio.create_memory_object_stream(max_buffer_size=100)

    async def producer():
        """Runs LangGraph .stream() in a thread; pushes SSE events into channel."""
        run_id = body.run_id or str(uuid4())
        await run_store.save_run(run_id, status="running", user_input=body.user_input)
        try:
            def _stream_sync():
                state = orchestrator._build_initial_state(body.user_input, run_id)
                for node_name, chunk in orchestrator._compiled.stream(
                    state,
                    config={"recursion_limit": orchestrator.max_steps * 9},
                    stream_mode="updates",
                ):
                    # Push UI-tier event synchronously — anyio handles thread safety
                    anyio.from_thread.run_sync(
                        send_stream.send_nowait,
                        ServerSentEvent(
                            event="node_end",
                            data=json.dumps({"type": "node_end", "node": node_name}),
                            id=run_id,
                        )
                    )
            await anyio.to_thread.run_sync(_stream_sync)
            # Final run_complete event
            result = await run_store.get_run(run_id)
            await send_stream.send(ServerSentEvent(
                event="run_complete",
                data=json.dumps({"type": "run_complete", "run_id": run_id}),
            ))
        except Exception as exc:
            await send_stream.send(ServerSentEvent(
                event="error",
                data=json.dumps({"type": "error", "detail": str(exc)}),
            ))
        finally:
            await send_stream.aclose()

    async def event_generator():
        async with receive_stream:
            async for event in receive_stream:
                yield event

    return EventSourceResponse(
        event_generator(),
        data_sender_callable=producer,
    )
```

**Simpler alternative for non-streaming POST /run:** If streaming from within `.run()` is too invasive initially, the first wave can call `run_in_threadpool(orchestrator.run, ...)` and return a plain JSON response, then add SSE in a follow-up wave. The CONTEXT.md locks streaming for POST /run, so the channel pattern above is the target.

### Pattern 3: RunStore Protocol — Postgres-Ready Abstraction

**What:** Abstract protocol class with three methods; SQLiteRunStore implements it; Phase 7 adds PostgresRunStore without touching the API layer.

```python
# Source: CONTEXT.md decisions + Python typing.Protocol
from typing import Protocol, Any

class RunStore(Protocol):
    async def save_run(self, run_id: str, *, status: str, **fields: Any) -> None: ...
    async def get_run(self, run_id: str) -> dict[str, Any] | None: ...
    async def list_runs(self, limit: int = 50) -> list[dict[str, Any]]: ...
```

SQLite schema:
```sql
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending|running|completed|failed
    user_input TEXT,
    prior_context_json TEXT,
    client_ip TEXT,
    request_headers_json TEXT,
    result_json TEXT,          -- RunResult serialized
    created_at TEXT NOT NULL,
    completed_at TEXT,
    missions_completed INTEGER DEFAULT 0,
    tools_used_json TEXT       -- list[str] for partial progress
);
```

SQLite WAL mode activation (call once at connection time):
```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")   # 5s retry on locked page
```

### Pattern 4: FastAPI Pydantic v2 Models

Use `model_config = ConfigDict(...)` (not `class Config`), matching project convention.

```python
# Source: existing codebase convention (CONTEXT.md code_context)
from pydantic import BaseModel, ConfigDict
from typing import Any

class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_input: str
    run_id: str | None = None
    prior_context: list[dict[str, Any]] | None = None

class RunStatusResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    run_id: str
    status: str   # pending|running|completed|failed
    elapsed_s: float | None = None
    missions_completed: int = 0
    tools_used_so_far: list[str] = []
    result: dict[str, Any] | None = None  # None when still running
```

### Pattern 5: user_run.py as httpx API Client

```python
# Source: httpx docs + CONTEXT.md decisions
import httpx
import subprocess, time, sys

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

def _ensure_server_running():
    try:
        httpx.get(f"{API_BASE}/health", timeout=2).raise_for_status()
    except Exception:
        subprocess.Popen([sys.executable, "-m", "uvicorn",
                          "agentic_workflows.api.app:app", "--host", "0.0.0.0",
                          "--port", "8000", "--log-level", "warning"])
        time.sleep(2)  # wait for startup

async def stream_run(user_input: str) -> None:
    async with httpx.AsyncClient(base_url=API_BASE, timeout=300) as client:
        async with client.stream("POST", "/run",
                                 json={"user_input": user_input}) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    event = json.loads(line[6:])
                    _render_sse_event(event)  # Rich rendering
```

### Anti-Patterns to Avoid

- **Compiling graph per-request:** Avoids paying 100-200ms compile cost on every HTTP request. The `LangGraphOrchestrator.__init__()` already calls `_compile_graph()` — do it once in lifespan.
- **Blocking the event loop with sync .run():** Using `await orchestrator.run(...)` without threadpool offload will freeze the entire event loop. Always wrap in `run_in_threadpool` or `anyio.to_thread.run_sync`.
- **Opening new SQLite connections per event:** One connection per request is fine; connection pooling is not needed for 3-concurrent target. Use `sqlite3.connect(path, check_same_thread=False)` with WAL mode and busy_timeout.
- **Storing RunResult TypedDict directly:** TypedDict is not JSON-serializable via `json.dumps` without `dict(result)`. Use `json.dumps(dict(result), default=str)` or convert to Pydantic model first.
- **Using app-level global state (module-level singletons):** Use `app.state` instead. Module-level globals break test isolation when multiple test cases spin up different app instances.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SSE wire protocol | Custom StreamingResponse with manual `data:\n\n` formatting | sse-starlette EventSourceResponse | Handles keep-alive pings, X-Accel-Buffering header, client disconnect detection, and W3C SSE spec compliance |
| SSE client in user_run | Manual line-by-line HTTP parsing | httpx async streaming + aiter_lines() | httpx already in deps; handles chunked transfer encoding, connection reuse |
| Sync/async threadpool bridge | asyncio.get_event_loop().run_in_executor() | starlette.concurrency.run_in_threadpool OR anyio.to_thread.run_sync | Both are idiomatic; the starlette version is simpler for route handlers; anyio version integrates with SSE producer |
| Run state persistence | Custom JSON file per run | SQLiteRunStore with WAL mode | Concurrent access needs proper locking semantics; SQLite WAL allows readers while writing |
| Uvicorn auto-start in user_run | complex process management | subprocess.Popen + health check poll | Uvicorn starts in < 2 seconds; a simple health-check retry loop is sufficient for CLI use |

**Key insight:** The sse-starlette library handles all SSE infrastructure concerns. The only code the planner writes is the async generator that yields `ServerSentEvent` objects — not the protocol machinery.

---

## Common Pitfalls

### Pitfall 1: Blocking the Event Loop with Sync LangGraph

**What goes wrong:** An `async def` route handler calls `orchestrator.run(...)` directly (sync function), which blocks the event loop. All other in-flight requests freeze until it completes.

**Why it happens:** FastAPI automatically offloads `def` (non-async) route handlers to a threadpool, but `async def` handlers run on the event loop. Calling sync code inside `async def` without offloading is a subtle bug.

**How to avoid:** Use `await run_in_threadpool(orchestrator.run, user_input, run_id)` in async route handlers, or declare non-streaming routes as plain `def` (FastAPI auto-offloads them).

**Warning signs:** All endpoints become slow when one run is in progress; `asyncio.get_event_loop().is_running()` shows the loop blocked.

### Pitfall 2: SQLite "database is locked" Under Concurrency

**What goes wrong:** Three simultaneous POST /run requests each open a SQLite connection and write; the second writer gets `sqlite3.OperationalError: database is locked`.

**Why it happens:** Default SQLite journal mode uses exclusive write locks. WAL mode is needed for concurrent read-while-write, plus `busy_timeout` to retry on lock.

**How to avoid:** Activate WAL mode on every new connection:
```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
```
Verify with: `conn.execute("PRAGMA journal_mode").fetchone()` → should return `('wal',)`.

**Warning signs:** Tests pass sequentially but fail under `asyncio.gather()` with 3 concurrent requests.

### Pitfall 3: RunResult TypedDict Not JSON-Serializable

**What goes wrong:** `json.dumps(run_result)` raises `TypeError: Object of type ToolRecord is not JSON serializable` because TypedDict instances contain nested TypedDict objects.

**Why it happens:** TypedDicts are plain dicts at runtime but their nested values may include non-serializable objects (`datetime`, custom types).

**How to avoid:** Use `json.dumps(run_result, default=str)` for storage. For API responses, define Pydantic response models and use `model_validate(run_result)`.

**Warning signs:** 500 errors on POST /run completion; `TypeError` in logs.

### Pitfall 4: SSE Client Disconnect Not Detected

**What goes wrong:** When the user_run client disconnects mid-stream, the server keeps running the LangGraph orchestrator and pushing events into the channel indefinitely.

**Why it happens:** The server-side generator doesn't check `await request.is_disconnected()`.

**How to avoid:** In the SSE event generator, periodically check disconnect. sse-starlette's `EventSourceResponse` handles this automatically when the generator exits — the key is ensuring the `data_sender_callable` (producer) terminates when send channel is closed.

### Pitfall 5: GET /run/{id}/stream Cross-Session Access

**What goes wrong:** Any caller who knows a run_id can reconnect to its stream, exposing in-progress state to unauthorized clients.

**Why it happens:** No session binding on the stream endpoint.

**How to avoid:** Store `client_ip` (or a session token) at run creation time; verify it matches on `/stream` reconnect. The CONTEXT.md decision locks this: "same session only — no cross-session access."

---

## Code Examples

Verified patterns from official sources:

### FastAPI Lifespan Pattern
```python
# Source: https://fastapi.tiangolo.com/advanced/events/
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    app.state.orchestrator = LangGraphOrchestrator()
    yield
    # shutdown (nothing needed for sync orchestrator)

app = FastAPI(lifespan=lifespan)
```

### EventSourceResponse with ServerSentEvent
```python
# Source: https://fastapi.tiangolo.com/tutorial/server-sent-events/ (FastAPI native SSE)
# Also: sse-starlette 3.3.x (compatible API)
from sse_starlette import EventSourceResponse, ServerSentEvent

@app.get("/stream/{run_id}", response_class=EventSourceResponse)
async def stream_run(run_id: str, request: Request):
    async def generator():
        yield ServerSentEvent(event="node_start", data='{"node": "plan"}', id="1")
        yield ServerSentEvent(event="run_complete", data='{"status": "done"}')
    return EventSourceResponse(generator())
```

### SQLite WAL Mode Activation
```python
# Source: https://sqlite.org/wal.html
import sqlite3

def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn
```

### httpx Async SSE Client (for user_run.py)
```python
# Source: https://www.python-httpx.org/async/
import httpx, json

async def consume_sse(url: str, payload: dict):
    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream("POST", url, json=payload) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    yield json.loads(line[6:])
```

### Concurrent Test Pattern (pytest-asyncio)
```python
# Source: FastAPI async test docs + asyncio.gather pattern
import pytest, asyncio
from httpx import AsyncClient, ASGITransport

@pytest.mark.asyncio
async def test_concurrent_runs(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tasks = [client.post("/run", json={"user_input": f"mission {i}"}) for i in range(3)]
        responses = await asyncio.gather(*tasks)
        assert all(r.status_code == 200 for r in responses)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `@app.on_event("startup")` | `lifespan` context manager | FastAPI 0.93+ (2023) | Colocates startup/shutdown; `@on_event` deprecated |
| `StreamingResponse` with manual SSE | `sse-starlette EventSourceResponse` | ~2021 onward | Built-in keep-alive, W3C compliance, disconnect detection |
| `class Config:` in Pydantic models | `model_config = ConfigDict(...)` | Pydantic v2 (2023) | Project already uses this convention |
| `asyncio.get_event_loop().run_in_executor` | `anyio.to_thread.run_sync` | FastAPI/Starlette adoption of anyio | Cleaner API; better anyio/trio compatibility |

**Deprecated/outdated:**
- `@app.on_event("startup")` / `@app.on_event("shutdown")`: Replaced by `lifespan`. Do not use in new code.
- `sse_starlette.sse.ServerSentEvent` with `dict` data: Pass `data=json.dumps(payload)` — raw dict is not automatically serialized in all versions.

---

## Open Questions

1. **LangGraph .stream() vs .invoke() for SSE**
   - What we know: `_compiled.invoke()` returns the final state; `_compiled.stream()` yields `(node_name, state_update)` tuples on every node transition.
   - What's unclear: `graph.py` currently wires `_compiled.invoke()` inside `run()`. To emit per-node SSE events, the API layer either: (a) uses `_compiled.stream()` directly (bypassing `run()`'s audit logic), or (b) adds an `on_node_transition` callback hook to `run()`.
   - Recommendation: Wave 1 should implement a thin `run_streaming()` method on `LangGraphOrchestrator` that calls `_compiled.stream()` with `stream_mode="updates"`, emits SSE events per node, then calls `_finalize()`. This keeps audit logic intact.

2. **anyio.from_thread.run_sync vs send_nowait inside sync thread**
   - What we know: Pushing to anyio channel from a sync thread requires `anyio.from_thread.run_sync(send_stream.send, event)` (not `send_nowait` which is not thread-safe in all contexts).
   - What's unclear: Whether `send_nowait` is safe when called from a `anyio.to_thread.run_sync` worker thread.
   - Recommendation: Use `anyio.from_thread.run_sync(send_stream.send, event)` — the safe documented pattern.

3. **user_run.py auto-start server signal handling**
   - What we know: `subprocess.Popen` spawns uvicorn in background. Python signal handling when parent exits needs consideration.
   - What's unclear: Whether the spawned uvicorn survives the parent process exit cleanly.
   - Recommendation: Use `subprocess.Popen(..., start_new_session=True)` to detach; document that it leaves a background server running (acceptable for CLI dev tool).

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.24 |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/unit/ -q` |
| Full suite command | `pytest tests/ -q` |
| HTTP contract tests | `pytest tests/integration/test_api_service.py -q` |
| Eval tests | `pytest tests/eval/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PROD-01 | POST /run accepts RunRequest, returns SSE stream with run_id | integration | `pytest tests/integration/test_api_service.py::test_post_run_sse -x` | Wave 0 |
| PROD-01 | GET /run/{id} returns completed result with audit_report and mission_reports | integration | `pytest tests/integration/test_api_service.py::test_get_run_completed -x` | Wave 0 |
| PROD-01 | GET /run/{id} returns partial status for in-progress run | integration | `pytest tests/integration/test_api_service.py::test_get_run_in_progress -x` | Wave 0 |
| PROD-01 | GET /health returns provider + tool_count | integration | `pytest tests/integration/test_api_service.py::test_health -x` | Wave 0 |
| PROD-01 | GET /tools returns list of {name, description} | integration | `pytest tests/integration/test_api_service.py::test_tools_list -x` | Wave 0 |
| PROD-02 | GET /run/{id}/stream returns text/event-stream | integration | `pytest tests/integration/test_api_service.py::test_get_run_stream -x` | Wave 0 |
| PROD-02 | SSE events arrive before run completes (node_start, node_end) | integration | `pytest tests/integration/test_api_service.py::test_sse_events_stream -x` | Wave 0 |
| PROD-02 | Graph compiled once at startup, not per-request | unit | `pytest tests/unit/test_api_lifespan.py::test_graph_compiled_once -x` | Wave 0 |
| PROD-01+02 | 3 concurrent POST /run requests succeed without SQLite locked error | integration | `pytest tests/integration/test_api_service.py::test_concurrent_runs -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/unit/ -q`
- **Per wave merge:** `pytest tests/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/integration/test_api_service.py` — all PROD-01/PROD-02 contract tests
- [ ] `tests/unit/test_api_lifespan.py` — lifespan singleton tests
- [ ] `tests/eval/__init__.py` + `tests/eval/test_eval_harness.py` — 3+ ScriptedProvider scenarios
- [ ] `tests/eval/conftest.py` — eval fixtures (ScriptedProvider variants)
- [ ] Framework already installed; add `sse-starlette`, `fastapi`, `uvicorn`, `httpx-sse` to pyproject.toml

---

## Sources

### Primary (HIGH confidence)
- FastAPI official docs — https://fastapi.tiangolo.com/advanced/events/ — lifespan pattern
- FastAPI SSE official docs — https://fastapi.tiangolo.com/tutorial/server-sent-events/ — EventSourceResponse, ServerSentEvent
- sse-starlette PyPI — https://pypi.org/project/sse-starlette/ — version 3.3.2, anyio memory stream pattern
- SQLite WAL official — https://sqlite.org/wal.html — WAL mode semantics and concurrent access
- httpx official docs — https://www.python-httpx.org/async/ — aiter_lines() streaming

### Secondary (MEDIUM confidence)
- sse-starlette DeepWiki usage guide — anyio.from_thread pattern for sync-to-async bridge
- DEV community guide "Streaming AI Agent with FastAPI & LangGraph 2025-26" — get_stream_writer() and astream() patterns; verified against LangGraph docs
- Starlette run_in_threadpool docs — sync-to-async offload for non-streaming endpoints

### Tertiary (LOW confidence)
- Various community examples for httpx-sse usage in tests — pattern verified against httpx docs but not independently confirmed for test-specific behavior

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified against PyPI (sse-starlette 3.3.2), FastAPI official docs, httpx docs
- Architecture: HIGH — lifespan and SSE patterns verified against official FastAPI docs; SQLite WAL verified against sqlite.org
- Sync/async bridge: MEDIUM — anyio memory channel pattern verified from sse-starlette docs and DeepWiki; exact thread-safety of send_nowait needs validation
- Pitfalls: HIGH — event-loop blocking and SQLite locking are well-documented; disconnect handling verified from sse-starlette source

**Research date:** 2026-03-05
**Valid until:** 2026-04-05 (stable ecosystem; sse-starlette and FastAPI are mature)
