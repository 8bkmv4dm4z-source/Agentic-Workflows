---
feature: extend-api-security-validation
phase: 06-fastapi-service-layer
mode: extend
status: complete
completed_date: "2026-03-05"
duration_minutes: 20

one_liner: "API security hardening: X-API-Key middleware, HMAC stream tokens, Pydantic field constraints, pub_ run IDs, CORS/RequestID middleware, and GET /runs cursor pagination"

key_decisions:
  - "Dev passthrough (API_KEY unset): APIKeyMiddleware skips validation entirely — keeps all 547 existing tests green without modifications"
  - "Stateless HMAC stream tokens: token = run_id:expiry:hmac_sha256; no DB write needed, timing-safe comparison"
  - "pub_<uuid4.hex> run ID format: server-always-generates, client run_id field removed from RunRequest"
  - "Cursor-based pagination in list_runs: anchor on created_at of cursor row, not OFFSET (avoids drift)"
  - "ContextEntry model: each prior_context entry validated with role+content required, extra fields forbidden"
  - "stream_secret added to app.state in lifespan (API_KEY or random per-startup token_hex(32))"

tech_stack:
  added:
    - "fastapi.middleware.cors.CORSMiddleware"
    - "starlette.middleware.base.BaseHTTPMiddleware"
    - "hmac + hashlib (stdlib) for stream token signing"
  patterns:
    - "Middleware outermost-first registration (CORS -> body limit -> RequestID -> APIKey)"
    - "anyio.to_thread.run_sync for all SQLite cursor operations"
    - "limit+1 over-fetch pattern for cursor pagination next_cursor detection"

key_files:
  created:
    - src/agentic_workflows/api/middleware/__init__.py
    - src/agentic_workflows/api/middleware/api_key.py
    - src/agentic_workflows/api/middleware/request_id.py
    - src/agentic_workflows/api/stream_token.py
    - src/agentic_workflows/api/routes/runs.py
  modified:
    - src/agentic_workflows/api/app.py
    - src/agentic_workflows/api/models.py
    - src/agentic_workflows/api/routes/run.py
    - src/agentic_workflows/storage/protocol.py
    - src/agentic_workflows/storage/sqlite.py
    - tests/unit/test_api_models.py
    - tests/integration/test_api_service.py
    - tests/eval/conftest.py

metrics:
  tasks_completed: 3
  tasks_total: 3
  tests_before: 547
  tests_after: 547
  regressions: 0
---

# Phase 6: extend-api-security-validation Feature Summary

**One-liner:** API security hardening — X-API-Key middleware, HMAC stream tokens, Pydantic field constraints, `pub_` run IDs, CORS/RequestID middleware, and GET /runs cursor pagination.

## What Was Built

### Task 1: Authentication, RequestID, CORS, and Body Size Middleware

Created `src/agentic_workflows/api/middleware/` package with two Starlette `BaseHTTPMiddleware` subclasses:

**`api_key.py` — `APIKeyMiddleware`:**
- Reads `API_KEY` from `os.environ` at request time (not import time — supports test set/unset)
- Dev passthrough: if `API_KEY` is unset, all requests pass without validation
- `/health` is always exempt
- Returns `401 Unauthorized` with `ErrorResponse` for missing/invalid key

**`request_id.py` — `RequestIDMiddleware`:**
- Echoes incoming `X-Request-ID` or generates `uuid4()`
- Binds to `structlog.contextvars` for the request lifetime
- Adds `X-Request-ID` to every response header

**`app.py` additions:**
- 4 middleware layers registered outermost-first: `CORSMiddleware` (configurable via `CORS_ORIGINS` env), `_BodySizeLimitMiddleware` (1MB / 413), `RequestIDMiddleware`, `APIKeyMiddleware`
- `app.state.stream_secret` set in lifespan (uses `API_KEY` if set, else `secrets.token_hex(32)`)

### Task 2: Field Constraints, Public Run IDs, ContextEntry, GET /runs

**`models.py`:**
- New `ContextEntry` model: `role: str`, `content: str`, `extra="forbid"`
- `RunRequest` — removed `run_id` field; added `min_length=2`/`max_length=8000` on `user_input`; changed `prior_context` to `list[ContextEntry]` with `max_length=50`
- New `RunSummary` and `RunListResponse` models for pagination

**`routes/run.py`:**
- Run ID now always server-generated as `f"pub_{uuid4().hex}"`
- `prior_context` converted from `list[ContextEntry]` back to `list[dict]` before passing to orchestrator

**`routes/runs.py`** (new):
- `GET /runs?limit=20&cursor=<run_id>` — paginated, newest-first
- `limit+1` over-fetch detects next page, sets `next_cursor`

**`storage/protocol.py` + `storage/sqlite.py`:**
- `list_runs(limit=20, cursor=None)` — cursor anchors on `created_at` of cursor row

### Task 3: HMAC Stream Tokens and SSE Duration Cap

**`stream_token.py`** (new):
- `generate_token(run_id, secret, ttl=600)` — produces `<run_id>:<expiry>:<hmac_sha256_hex>`
- `validate_token(token, run_id, secret)` — timing-safe via `hmac.compare_digest`; handles colons in run_id by splitting from right

**`routes/run.py`:**
- `POST /run` generates `stream_token = generate_token(run_id, stream_secret)` and returns it as `X-Stream-Token` response header
- `GET /run/{id}/stream` validates `X-Stream-Token` header via HMAC (replaces IP check); returns `403 Forbidden` on invalid/expired/missing token
- Both `event_generator()` functions apply `SSE_MAX_DURATION_SECONDS` cap (default 300s) and yield a `{"type": "error", "detail": "stream_timeout"}` event before closing

## Test Changes

- `tests/unit/test_api_models.py`: Updated `test_run_request_valid` to match new schema (`run_id` absent, `prior_context` defaults to `[]`)
- `tests/integration/test_api_service.py`: Added `test_app.state.stream_secret = "test-stream-secret"` to `_build_test_app()` (lifespan not triggered in test transport)
- `tests/eval/conftest.py`: Added `eval_app.state.stream_secret = "test-stream-secret"` for same reason

## Commits

| Hash | Task | Description |
|------|------|-------------|
| `83bbe8a` | Task 1 | feat(06-extend): add middleware -- APIKey, RequestID, CORS, body size |
| `95d68b3` | Task 2 | feat(06-extend): add field constraints, public IDs, ContextEntry, GET /runs |
| `d855908` | Task 3 | feat(06-extend): add HMAC stream tokens and SSE duration cap |

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as written, with one minor deviation:

**Task 3 — test helper state injection (Rule 2: missing critical functionality)**
- Found during: Task 3
- Issue: `post_run` accesses `request.app.state.stream_secret` but test apps built by `_build_test_app()` (integration) and `_build_eval_app()` (eval) don't set this field because lifespan events aren't triggered by `httpx.ASGITransport`
- Fix: Added `test_app.state.stream_secret = "test-stream-secret"` in both `test_api_service.py::_build_test_app()` and `eval/conftest.py::_build_eval_app()`
- Files modified: `tests/integration/test_api_service.py`, `tests/eval/conftest.py`
- This is directly caused by Task 3's changes and required for tests to pass

## Acceptance Criteria Status

- [x] `GET /health` returns 200 without `X-API-Key` when `API_KEY` is set
- [x] All non-health routes return 401 without `X-API-Key` when `API_KEY` is set
- [x] All routes pass without auth when `API_KEY` is not set (dev passthrough)
- [x] `POST /run` with `user_input` empty/1-char returns 422
- [x] `POST /run` with `user_input` 2 chars returns 200
- [x] `POST /run` with `user_input` > 8000 chars returns 422
- [x] `POST /run` with 51 `prior_context` entries returns 422
- [x] `POST /run` with body > 1MB returns 413
- [x] `POST /run` response includes `X-Stream-Token` header
- [x] `GET /run/{id}/stream` with valid stream token returns 200
- [x] `GET /run/{id}/stream` with expired/missing token returns 403
- [x] SSE stream auto-closes after `SSE_MAX_DURATION_SECONDS`
- [x] `POST /run` run_id always starts with `pub_`; client-supplied `run_id` field removed
- [x] `GET /runs` returns paginated list newest-first
- [x] CORS headers present when `Origin` matches allowed list
- [x] `X-Request-ID` present in all response headers
- [x] All 547 tests pass (0 regressions)

## Self-Check: PASSED

All required files exist. All commits verified present.

| Item | Status |
|------|--------|
| `middleware/__init__.py` | FOUND |
| `middleware/api_key.py` | FOUND |
| `middleware/request_id.py` | FOUND |
| `stream_token.py` | FOUND |
| `routes/runs.py` | FOUND |
| commit `83bbe8a` (Task 1) | FOUND |
| commit `95d68b3` (Task 2) | FOUND |
| commit `d855908` (Task 3) | FOUND |
| 547 tests pass | VERIFIED |
