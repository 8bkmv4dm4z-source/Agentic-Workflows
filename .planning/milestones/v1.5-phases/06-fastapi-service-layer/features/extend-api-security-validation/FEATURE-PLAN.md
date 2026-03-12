---
feature_name: extend-api-security-validation
phase: 06-fastapi-service-layer
mode: extend
source_context: .planning/phases/06-fastapi-service-layer/features/extend-api-security-validation/FEATURE-CONTEXT.md
baseline_tests: 536

must_haves:
  truths:
    - "GET /health returns 200 without X-API-Key (when API_KEY is set)"
    - "All non-health routes return 401 without X-API-Key (when API_KEY is set)"
    - "All routes pass without X-API-Key when API_KEY is not set (dev passthrough)"
    - "POST /run with user_input shorter than 2 chars returns 422"
    - "POST /run with user_input longer than 8000 chars returns 422"
    - "POST /run with 51 prior_context entries returns 422"
    - "POST /run with body larger than 1MB returns 413"
    - "POST /run response includes X-Stream-Token header"
    - "GET /run/{id}/stream with valid stream token returns 200"
    - "GET /run/{id}/stream with expired or missing stream token returns 403"
    - "SSE stream auto-closes after SSE_MAX_DURATION_SECONDS seconds"
    - "POST /run returned run_id always starts with pub_"
    - "POST /run ignores any client-supplied run_id field"
    - "GET /runs returns paginated list ordered newest-first"
    - "CORS headers present on responses when Origin matches allowed list"
    - "X-Request-ID present in all response headers"
    - "All 536 existing tests continue to pass"
  artifacts:
    - path: "src/agentic_workflows/api/middleware/__init__.py"
      provides: "Middleware package exports"
      exports: ["APIKeyMiddleware", "RequestIDMiddleware"]
    - path: "src/agentic_workflows/api/middleware/api_key.py"
      provides: "X-API-Key authentication middleware"
      contains: "class APIKeyMiddleware"
    - path: "src/agentic_workflows/api/middleware/request_id.py"
      provides: "X-Request-ID tracing middleware"
      contains: "class RequestIDMiddleware"
    - path: "src/agentic_workflows/api/stream_token.py"
      provides: "Stateless HMAC stream token generation and validation"
      exports: ["generate_token", "validate_token"]
    - path: "src/agentic_workflows/api/routes/runs.py"
      provides: "GET /runs paginated run history endpoint"
      contains: "GET /runs"
  key_links:
    - from: "src/agentic_workflows/api/app.py"
      to: "src/agentic_workflows/api/middleware/api_key.py"
      via: "add_middleware(APIKeyMiddleware)"
      pattern: "add_middleware.*APIKeyMiddleware"
    - from: "src/agentic_workflows/api/app.py"
      to: "src/agentic_workflows/api/routes/runs.py"
      via: "include_router(runs_router)"
      pattern: "include_router.*runs"
    - from: "src/agentic_workflows/api/routes/run.py"
      to: "src/agentic_workflows/api/stream_token.py"
      via: "generate_token / validate_token calls"
      pattern: "generate_token|validate_token"
    - from: "src/agentic_workflows/storage/protocol.py"
      to: "src/agentic_workflows/storage/sqlite.py"
      via: "list_runs(limit, cursor) protocol + implementation"
      pattern: "list_runs.*cursor"

notes:
  - Tasks are independent — no inter-task file conflicts, can be executed in any order
  - Dev passthrough (API_KEY unset) keeps all 536 existing integration tests green without changes
  - Stream token secret lives in app.state — no DB writes needed (stateless HMAC)
  - Cursor-based pagination avoids OFFSET performance issues on large run histories
  - list_runs already exists on RunStore protocol (limit-only) and SQLiteRunStore;
    Task 2 upgrades the signature to add the cursor parameter
---

<objective>
Harden the Phase 6 FastAPI service with authentication, strict input validation,
public-facing run IDs, stream tokens, CORS, request ID tracing, and a GET /runs
history endpoint. All work is within the existing HTTP service layer — no new
infrastructure, no ROADMAP changes.

Purpose: Make the API production-ready for single-tenant use: protected endpoints,
tamper-resistant stream access, traceable requests, and auditable run history.

Output:
- src/agentic_workflows/api/middleware/ (3 files)
- src/agentic_workflows/api/stream_token.py
- src/agentic_workflows/api/routes/runs.py
- Updated: app.py, models.py, routes/run.py, storage/protocol.py, storage/sqlite.py
</objective>

<execution_context>
@/home/nir/.claude/get-shit-done/workflows/execute-plan.md
@/home/nir/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/06-fastapi-service-layer/features/extend-api-security-validation/FEATURE-CONTEXT.md

Key existing interfaces for executor reference:

```python
# src/agentic_workflows/api/app.py — current lifespan and middleware registration point
# app.state currently holds: orchestrator, run_store, active_streams
# No middleware registered yet (plain include_router calls only)

# src/agentic_workflows/api/models.py — current RunRequest (to be modified in Task 2)
class RunRequest(BaseModel):
    user_input: str                           # Field with no constraints yet
    run_id: str | None = Field(default=None)  # REMOVE this field in Task 2
    prior_context: list[dict[str, Any]] | None = Field(default=None)  # CHANGE type in Task 2

class ErrorResponse(BaseModel):
    error: str
    run_id: str | None = Field(default=None)
    detail: str | None = Field(default=None)

# src/agentic_workflows/storage/protocol.py — current list_runs signature (upgrade in Task 2)
async def list_runs(self, limit: int = 50) -> list[dict[str, Any]]: ...

# src/agentic_workflows/storage/sqlite.py — current list_runs impl (upgrade in Task 2)
# runs table columns: run_id, status, user_input, prior_context_json, client_ip,
#   request_headers_json, result_json, created_at, completed_at,
#   missions_completed, tools_used_json

# src/agentic_workflows/api/routes/run.py — current run_id generation and stream reconnect
# run_id = body.run_id or str(uuid4())  — Task 2 changes this to pub_<uuid4>
# GET /run/{id}/stream currently validates by client IP — Task 3 replaces with HMAC token
```
</context>

<tasks>

<task id="task-1" type="auto">
  <name>Task 1: Add authentication, request ID, CORS, and body size middleware</name>
  <files>
    CREATE src/agentic_workflows/api/middleware/__init__.py
    CREATE src/agentic_workflows/api/middleware/api_key.py
    CREATE src/agentic_workflows/api/middleware/request_id.py
    MODIFY src/agentic_workflows/api/app.py
  </files>
  <action>
Create `src/agentic_workflows/api/middleware/` package with two middleware classes, then
register all middleware in `app.py`.

**`api_key.py` — `APIKeyMiddleware(BaseHTTPMiddleware)`:**
- Read `API_KEY` from `os.environ.get("API_KEY")` at request time (not at import time,
  so tests can set/unset it).
- If `API_KEY` is not set (empty or None): call `await call_next(request)` and return
  immediately (dev passthrough — keeps all 536 existing tests green).
- Exempt path: if `request.url.path == "/health"` skip validation and pass through.
- Otherwise: read `request.headers.get("X-API-Key")`. If missing or not equal to
  `API_KEY`, return a `JSONResponse` with status 401 and body
  `ErrorResponse(error="Unauthorized", detail="Missing or invalid X-API-Key header").model_dump()`.
- Import `ErrorResponse` from `agentic_workflows.api.models`.

**`request_id.py` — `RequestIDMiddleware(BaseHTTPMiddleware)`:**
- Read `request.headers.get("X-Request-ID")`. If absent, generate `str(uuid4())`.
- Bind to structlog context: `structlog.contextvars.bind_contextvars(request_id=request_id)`.
- Call `response = await call_next(request)`.
- Add header: `response.headers["X-Request-ID"] = request_id`.
- Clear structlog contextvars after response: `structlog.contextvars.clear_contextvars()`.
- Import `uuid4` from `uuid` and `structlog`.

**`__init__.py`:**
```python
from agentic_workflows.api.middleware.api_key import APIKeyMiddleware
from agentic_workflows.api.middleware.request_id import RequestIDMiddleware

__all__ = ["APIKeyMiddleware", "RequestIDMiddleware"]
```

**`app.py` modifications — register middleware AFTER app instantiation, BEFORE route inclusion:**

Add these imports at the top:
```python
import secrets
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from agentic_workflows.api.middleware import APIKeyMiddleware, RequestIDMiddleware
```

Register in this order (Starlette processes middleware in reverse registration order, so
register outermost-first: CORS wraps everything, then body limit, then request ID, then
API key as innermost):

```python
# 1. CORS — outermost, handles preflight before auth check
cors_origins_raw = os.environ.get("CORS_ORIGINS", "")
cors_origins = (
    [o.strip() for o in cors_origins_raw.split(",") if o.strip()]
    if cors_origins_raw
    else ["http://localhost:3000", "http://localhost:8080"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Body size limit — 1MB (1_048_576 bytes); returns 413 on exceed
from starlette.middleware.trustedhost import TrustedHostMiddleware  # not used — just showing placement
# Use a custom BaseHTTPMiddleware for body size:
class _BodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > 1_048_576:
            from fastapi.responses import JSONResponse
            from agentic_workflows.api.models import ErrorResponse
            return JSONResponse(
                status_code=413,
                content=ErrorResponse(
                    error="Payload Too Large",
                    detail="Request body exceeds 1MB limit",
                ).model_dump(),
            )
        return await call_next(request)

app.add_middleware(_BodySizeLimitMiddleware)

# 3. Request ID — binds request_id to structlog context
app.add_middleware(RequestIDMiddleware)

# 4. API Key — innermost auth check
app.add_middleware(APIKeyMiddleware)
```

Also add in `lifespan`, after `run_store` assignment:
```python
application.state.stream_secret = (
    os.environ.get("API_KEY") or secrets.token_hex(32)
)
```
(This is needed by Task 3; add it here so Task 3 can depend on `app.state.stream_secret`
being available. If Task 3 runs first, it will add this itself — either is fine.)

Keep all existing error handlers and route registrations unchanged.
  </action>
  <verify>
Run the test suite to confirm no regressions:
```
cd /home/nir/dev/agent_phase0 && pytest tests/ -q 2>&1 | tail -5
```
Expected: 536 tests pass (same as baseline).

Manual smoke checks (requires running server with API_KEY set):
- `GET /health` without `X-API-Key` → 200
- `POST /run` without `X-API-Key` → 401
- Any response → includes `X-Request-ID` header
- OPTIONS preflight with `Origin: http://localhost:3000` → includes `Access-Control-Allow-Origin`
- POST with `Content-Length: 2000000` → 413
  </verify>
  <done>
middleware/ package exists with api_key.py, request_id.py, __init__.py. app.py registers
CORSMiddleware, body size limit, RequestIDMiddleware, and APIKeyMiddleware. All 536 tests pass.
  </done>
  <rollback>
Delete src/agentic_workflows/api/middleware/ directory. In app.py: remove the four
add_middleware() calls and their associated imports (_BodySizeLimitMiddleware class, CORS
import, middleware package import, secrets import). Remove stream_secret assignment from
lifespan if added.
  </rollback>
</task>

<task id="task-2" type="auto">
  <name>Task 2: Add field constraints, public run IDs, ContextEntry model, and GET /runs endpoint</name>
  <files>
    MODIFY src/agentic_workflows/api/models.py
    MODIFY src/agentic_workflows/api/routes/run.py
    CREATE src/agentic_workflows/api/routes/runs.py
    MODIFY src/agentic_workflows/storage/protocol.py
    MODIFY src/agentic_workflows/storage/sqlite.py
    MODIFY src/agentic_workflows/api/app.py
  </files>
  <action>
**`models.py` changes:**

Add `datetime` import: `from datetime import datetime`

Replace the `RunRequest` class entirely:
```python
class ContextEntry(BaseModel):
    """A single prior-context message with role and content."""
    model_config = ConfigDict(extra="forbid")
    role: str = Field(description="Message role (e.g. 'user', 'assistant', 'system')")
    content: str = Field(description="Message content")


class RunRequest(BaseModel):
    """Request body for POST /run — start an orchestrator run."""
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"user_input": "Sort [3,1,2] and compute fibonacci(10)"},
                {"user_input": "Analyze the dataset [10, 20, 300, 25, 15]"},
            ]
        },
    )
    user_input: str = Field(
        min_length=2,
        max_length=8000,
        description="The natural-language task for the agent to execute",
    )
    prior_context: list[ContextEntry] = Field(
        default=[],
        max_length=50,
        description="Prior conversation messages for multi-turn context (max 50 entries)",
    )
```

Note: `run_id` field is removed — server always generates it.

Add two new models after `ErrorResponse`:
```python
class RunSummary(BaseModel):
    """Summary row returned by GET /runs."""
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(description="Public run identifier")
    status: str = Field(description="Run status")
    created_at: datetime = Field(description="When the run was created")
    elapsed_s: float | None = Field(default=None, description="Wall-clock seconds if completed")
    missions_completed: int = Field(default=0, description="Missions finished")


class RunListResponse(BaseModel):
    """Paginated response for GET /runs."""
    model_config = ConfigDict(extra="forbid")
    items: list[RunSummary] = Field(description="Run summaries, newest first")
    next_cursor: str | None = Field(default=None, description="Cursor for next page; None if last page")
```

**`routes/run.py` changes:**

In `post_run`:
- Replace `run_id = body.run_id or str(uuid4())` with `run_id = f"pub_{uuid4().hex}"`.
- Replace `prior_context = body.prior_context` (which is now `list[ContextEntry]`) with:
  `prior_context = [entry.model_dump() for entry in body.prior_context] or None`
  This converts ContextEntry objects back to plain dicts before passing to state logic.
  The existing `if prior_context:` checks and dict-key access downstream remain valid.

**`storage/protocol.py` changes:**

Update the `list_runs` method signature in the `RunStore` protocol:
```python
async def list_runs(
    self, limit: int = 20, cursor: str | None = None
) -> list[dict[str, Any]]:
    """Return runs ordered by created_at DESC, with optional cursor pagination."""
    ...
```

**`storage/sqlite.py` changes:**

Replace the existing `list_runs` method body with cursor-aware pagination:
```python
async def list_runs(
    self, limit: int = 20, cursor: str | None = None
) -> list[dict[str, Any]]:
    """Return runs newest-first with optional cursor-based pagination."""

    def _list() -> list[dict[str, Any]]:
        if cursor is not None:
            # Look up the created_at of the cursor row to use as the anchor
            anchor_row = self._conn.execute(
                "SELECT created_at FROM runs WHERE run_id = ?", (cursor,)
            ).fetchone()
            if anchor_row:
                rows = self._conn.execute(
                    "SELECT * FROM runs WHERE created_at < ? ORDER BY created_at DESC LIMIT ?",
                    (anchor_row["created_at"], limit),
                ).fetchall()
            else:
                # Cursor not found — return empty page
                rows = []
        else:
            rows = self._conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    return await anyio.to_thread.run_sync(_list)
```

**`routes/runs.py` (new file):**
```python
"""GET /runs — paginated run history endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from agentic_workflows.api.models import ErrorResponse, RunListResponse, RunSummary

log = structlog.get_logger()

router = APIRouter()


@router.get(
    "/runs",
    response_model=RunListResponse,
    summary="List recent runs",
    description="Return a paginated list of agent runs ordered newest-first. "
    "Use the next_cursor field to fetch the next page.",
    responses={500: {"model": ErrorResponse, "description": "Storage error"}},
)
async def get_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100, description="Number of results per page"),
    cursor: str | None = Query(default=None, description="Pagination cursor (run_id of last item)"),
) -> JSONResponse:
    """Return paginated run summaries, newest first."""
    run_store = request.app.state.run_store

    try:
        rows = await run_store.list_runs(limit=limit + 1, cursor=cursor)
    except Exception as exc:
        log.error("runs.list_error", error=str(exc))
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(error="Storage error", detail=str(exc)).model_dump(),
        )

    # Determine next cursor: if we got limit+1 rows, there is a next page
    has_next = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = page_rows[-1]["run_id"] if has_next and page_rows else None

    items = []
    for row in page_rows:
        # Parse elapsed_s from created_at / completed_at
        elapsed_s: float | None = None
        try:
            if row.get("created_at") and row.get("completed_at"):
                created = datetime.fromisoformat(row["created_at"])
                completed = datetime.fromisoformat(row["completed_at"])
                elapsed_s = (completed - created).total_seconds()
        except (ValueError, TypeError):
            pass

        # Parse created_at to datetime
        created_at: datetime
        try:
            created_at = datetime.fromisoformat(row["created_at"])
        except (ValueError, TypeError, KeyError):
            from datetime import UTC
            created_at = datetime.now(UTC)

        items.append(
            RunSummary(
                run_id=row["run_id"],
                status=row.get("status", "unknown"),
                created_at=created_at,
                elapsed_s=elapsed_s,
                missions_completed=row.get("missions_completed", 0),
            )
        )

    response = RunListResponse(items=items, next_cursor=next_cursor)
    return JSONResponse(content=response.model_dump(mode="json"))
```

**`app.py` change:**

Add import and router registration alongside existing routers:
```python
from agentic_workflows.api.routes import health, run, runs, tools
# ...
app.include_router(runs.router)
```
  </action>
  <verify>
Run the test suite:
```
cd /home/nir/dev/agent_phase0 && pytest tests/ -q 2>&1 | tail -5
```
Expected: 536 tests pass.

Targeted validation checks:
```
cd /home/nir/dev/agent_phase0 && python -c "
from agentic_workflows.api.models import RunRequest
from pydantic import ValidationError

# user_input empty string -> ValidationError
try:
    RunRequest(user_input='')
    print('FAIL: empty string should raise')
except ValidationError:
    print('PASS: empty string raises ValidationError')

# user_input 1 char -> ValidationError
try:
    RunRequest(user_input='x')
    print('FAIL: 1-char should raise')
except ValidationError:
    print('PASS: 1-char raises ValidationError')

# user_input 2 chars -> OK
r = RunRequest(user_input='no')
print(f'PASS: 2-char ok, run_id not in model: {not hasattr(r, \"run_id\")}')

# user_input 8001 chars -> ValidationError
try:
    RunRequest(user_input='x' * 8001)
    print('FAIL: 8001-char should raise')
except ValidationError:
    print('PASS: 8001-char raises ValidationError')

# 51 prior_context entries -> ValidationError
try:
    RunRequest(user_input='hello', prior_context=[{'role': 'user', 'content': 'x'}] * 51)
    print('FAIL: 51 entries should raise')
except ValidationError:
    print('PASS: 51 prior_context entries raises ValidationError')
"
```

Verify run_id format in route (inspect code):
```
cd /home/nir/dev/agent_phase0 && grep 'pub_' src/agentic_workflows/api/routes/run.py
```
Expected: line containing `f"pub_{uuid4().hex}"`.

Verify GET /runs router registered:
```
cd /home/nir/dev/agent_phase0 && python -c "
from agentic_workflows.api.app import app
routes = [r.path for r in app.routes]
print('/runs in routes:', '/runs' in routes)
"
```
  </verify>
  <done>
models.py has ContextEntry, updated RunRequest (no run_id field, Field constraints on
user_input and prior_context), RunSummary, RunListResponse. routes/run.py generates
pub_&lt;uuid4.hex&gt; run IDs. routes/runs.py exists with GET /runs cursor pagination.
storage/protocol.py and sqlite.py list_runs accept cursor parameter. app.py registers
runs router. All 536 tests pass.
  </done>
  <rollback>
Restore original RunRequest (add back run_id field, remove Field constraints, revert
prior_context to list[dict[str, Any]] | None). Remove ContextEntry, RunSummary,
RunListResponse from models.py. In routes/run.py: restore run_id line to
`body.run_id or str(uuid4())` and prior_context to `body.prior_context`. Delete
routes/runs.py. Restore list_runs signature in protocol.py to `limit: int = 50` with
no cursor. Restore sqlite.py list_runs to original limit-only implementation. Remove
`from agentic_workflows.api.routes import ... runs ...` and
`app.include_router(runs.router)` from app.py.
  </rollback>
</task>

<task id="task-3" type="auto">
  <name>Task 3: Add HMAC stream tokens and SSE max-duration cap</name>
  <files>
    CREATE src/agentic_workflows/api/stream_token.py
    MODIFY src/agentic_workflows/api/app.py
    MODIFY src/agentic_workflows/api/routes/run.py
  </files>
  <action>
**`stream_token.py` (new file):**

Stateless HMAC token — no DB writes. Standard library only (`hmac`, `hashlib`, `time`).

```python
"""Stateless HMAC stream tokens for SSE reconnect authorization."""

from __future__ import annotations

import hashlib
import hmac
import time


def generate_token(run_id: str, secret: str, ttl: int = 600) -> str:
    """Return a signed token: '<run_id>:<expiry_epoch>:<hmac_sha256_hex>'.

    TTL defaults to 600 seconds (10 minutes).
    """
    expiry = int(time.time()) + ttl
    message = f"{run_id}:{expiry}".encode()
    signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return f"{run_id}:{expiry}:{signature}"


def validate_token(token: str, run_id: str, secret: str) -> bool:
    """Return True iff token is structurally valid, unexpired, and HMAC matches.

    Uses hmac.compare_digest to prevent timing attacks.
    """
    try:
        parts = token.split(":")
        # Token format: <run_id>:<expiry>:<hmac> where run_id itself may contain colons
        # run_id is everything up to the last two colon-delimited parts
        if len(parts) < 3:
            return False
        token_hmac = parts[-1]
        expiry_str = parts[-2]
        token_run_id = ":".join(parts[:-2])

        if token_run_id != run_id:
            return False

        expiry = int(expiry_str)
        if time.time() > expiry:
            return False

        message = f"{run_id}:{expiry_str}".encode()
        expected_hmac = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(token_hmac, expected_hmac)
    except (ValueError, AttributeError):
        return False
```

**`app.py` changes:**

Add `import secrets` at the top (if not already present from Task 1).

In `lifespan`, after `run_store` assignment, add:
```python
application.state.stream_secret = (
    os.environ.get("API_KEY") or secrets.token_hex(32)
)
```
If Task 1 already added this line, skip (it is idempotent — same logic).

**`routes/run.py` changes:**

Add imports at top:
```python
from agentic_workflows.api.stream_token import generate_token, validate_token
```

In `post_run` handler, after `run_id` is generated and before `await run_store.save_run(...)`:
```python
stream_secret = request.app.state.stream_secret
stream_token = generate_token(run_id, stream_secret)
```

Change the return statement to pass response headers:
```python
return EventSourceResponse(
    event_generator(),
    data_sender_callable=producer,
    headers={"X-Stream-Token": stream_token},
)
```

In `event_generator()` inside `post_run`, add SSE duration cap:
```python
import os as _os
_SSE_MAX = int(_os.environ.get("SSE_MAX_DURATION_SECONDS", "300"))

async def event_generator():
    start = time.time()
    async for event in receive_stream:
        if time.time() - start > _SSE_MAX:
            yield json.dumps({"type": "error", "detail": "stream_timeout"}, default=str)
            return
        yield json.dumps(event, default=str)
```

Note: `import os as _os` at the top of the function avoids shadowing the module-level
import; alternatively, `os` is already imported at the top of routes/run.py — just use
`int(os.environ.get(...))` directly.

In `get_run_stream` handler, replace the IP-based session validation with token validation:

```python
# Remove the old client_ip check block entirely. Replace with:
stream_token_header = request.headers.get("X-Stream-Token")
stream_secret = request.app.state.stream_secret

if not stream_token_header or not validate_token(stream_token_header, run_id, stream_secret):
    return JSONResponse(
        status_code=403,
        content=ErrorResponse(
            error="Forbidden",
            run_id=run_id,
            detail="Missing or invalid stream token",
        ).model_dump(),
    )
```

Also add duration cap to `event_generator()` in `get_run_stream`:
```python
_SSE_MAX = int(os.environ.get("SSE_MAX_DURATION_SECONDS", "300"))

async def event_generator():
    start = time.time()
    try:
        async for event in receive_stream:
            if time.time() - start > _SSE_MAX:
                yield json.dumps({"type": "error", "detail": "stream_timeout"}, default=str)
                return
            yield json.dumps(event, default=str)
    except anyio.ClosedResourceError:
        pass
```
  </action>
  <verify>
Run the test suite:
```
cd /home/nir/dev/agent_phase0 && pytest tests/ -q 2>&1 | tail -5
```
Expected: 536 tests pass.

Unit test the token module directly:
```
cd /home/nir/dev/agent_phase0 && python -c "
from agentic_workflows.api.stream_token import generate_token, validate_token
import time

secret = 'test-secret-abc'
run_id = 'pub_abc123'

# Valid token
tok = generate_token(run_id, secret, ttl=60)
print('PASS: generate returns string:', isinstance(tok, str))
print('PASS: valid token:', validate_token(tok, run_id, secret))

# Wrong run_id
print('PASS: wrong run_id rejected:', not validate_token(tok, 'pub_other', secret))

# Expired token (ttl=0 means expiry is in the past by the time we validate)
expired = generate_token(run_id, secret, ttl=-1)
print('PASS: expired token rejected:', not validate_token(expired, run_id, secret))

# Tampered token
parts = tok.split(':')
parts[-1] = 'deadbeef' * 8
tampered = ':'.join(parts)
print('PASS: tampered token rejected:', not validate_token(tampered, run_id, secret))

# Missing token (empty string)
print('PASS: empty token rejected:', not validate_token('', run_id, secret))
"
```

Verify X-Stream-Token appears in POST /run response header (code inspection):
```
cd /home/nir/dev/agent_phase0 && grep 'X-Stream-Token' src/agentic_workflows/api/routes/run.py
```

Verify validate_token called in get_run_stream (no IP check remaining):
```
cd /home/nir/dev/agent_phase0 && grep -n 'client_ip\|validate_token' src/agentic_workflows/api/routes/run.py
```
Expected: no `client_ip` comparison in `get_run_stream`, `validate_token` present.
  </verify>
  <done>
stream_token.py exists with generate_token and validate_token. POST /run returns
X-Stream-Token header. GET /run/{id}/stream validates token via HMAC (403 on
invalid/expired/missing). Both SSE event_generators apply SSE_MAX_DURATION_SECONDS cap.
app.state.stream_secret set in lifespan. All 536 tests pass.
  </done>
  <rollback>
Delete src/agentic_workflows/api/stream_token.py. In routes/run.py: remove
generate_token/validate_token imports; restore IP-based check in get_run_stream
(re-add `client_ip = request.client.host` and the `if stream_info.get("client_ip")`
block); remove `headers={"X-Stream-Token": stream_token}` from EventSourceResponse in
post_run; remove duration cap from both event_generator functions. In app.py: remove
stream_secret assignment from lifespan.
  </rollback>
</task>

</tasks>

<verification>
After all tasks complete, run the full test suite:

```
cd /home/nir/dev/agent_phase0 && pytest tests/ -q
```

Expected: all 536 tests pass. No new failures introduced.

Check that key new files exist:
```
ls -la \
  src/agentic_workflows/api/middleware/__init__.py \
  src/agentic_workflows/api/middleware/api_key.py \
  src/agentic_workflows/api/middleware/request_id.py \
  src/agentic_workflows/api/stream_token.py \
  src/agentic_workflows/api/routes/runs.py
```

Verify model constraints are in place:
```
cd /home/nir/dev/agent_phase0 && python -c "
import json
from agentic_workflows.api.models import RunRequest
s = RunRequest.model_json_schema()
ui = s['properties']['user_input']
pc = s['properties']['prior_context']
print('user_input minLength:', ui.get('minLength'))
print('user_input maxLength:', ui.get('maxLength'))
print('prior_context maxItems:', pc.get('maxItems'))
assert 'run_id' not in s['properties'], 'run_id should not be in RunRequest schema'
print('run_id absent from schema: PASS')
"
```

Verify runs router is registered:
```
cd /home/nir/dev/agent_phase0 && python -c "
from agentic_workflows.api.app import app
paths = [r.path for r in app.routes]
assert '/runs' in paths, f'/runs not in {paths}'
print('/runs registered: PASS')
"
```
</verification>

<success_criteria>
- All 536 baseline tests continue to pass (zero regressions)
- middleware/ package exists with api_key.py, request_id.py, __init__.py
- GET /health returns 200 without X-API-Key when API_KEY is set
- POST /run returns 401 without X-API-Key when API_KEY is set
- All routes pass without authentication when API_KEY is not set (dev passthrough)
- POST /run with user_input of 0 or 1 char returns 422
- POST /run with user_input of 2 chars returns 200/stream
- POST /run with user_input exceeding 8000 chars returns 422
- POST /run with 51 prior_context entries returns 422
- POST /run with body exceeding 1MB returns 413
- POST /run response includes X-Stream-Token header
- GET /run/{id}/stream with valid token returns 200
- GET /run/{id}/stream with expired or missing token returns 403
- SSE stream stops after SSE_MAX_DURATION_SECONDS with stream_timeout error event
- POST /run returned run_id starts with "pub_"
- GET /runs endpoint exists and returns paginated RunListResponse newest-first
- CORS headers present when Origin header matches allowed list
- X-Request-ID present in all response headers
</success_criteria>

<output>
After completion, create `.planning/phases/06-fastapi-service-layer/features/extend-api-security-validation/FEATURE-SUMMARY.md`
with what was built, decisions made, files modified, and test results.
</output>
