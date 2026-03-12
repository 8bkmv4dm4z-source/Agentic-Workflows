# Phase 6: FastAPI Service Layer — Feature Context

**Mode:** Extend
**Feature:** API security, input validation, public UUIDs, GET /runs, CORS, stream tokens
**Gathered:** 2026-03-05
**Status:** Ready for planning

<domain>
## Feature Boundary

Phase 6 scope: Wrap LangGraphOrchestrator.run() in a FastAPI HTTP service with SSE
streaming, run persistence, API client CLI, and eval harness.

This feature: Harden the existing Phase 6 FastAPI service with authentication middleware,
strict input validation, public-facing run IDs, stream tokens, CORS, request ID tracing,
and a GET /runs list endpoint — all within the existing HTTP service layer.

Does NOT extend phase scope. Does NOT modify ROADMAP.md.

</domain>

<decisions>
## Implementation Decisions

### API Key Authentication
- Middleware: `X-API-Key` request header, validated against `API_KEY` env var
- Lives in `src/agentic_workflows/api/middleware/api_key.py`
- All routes protected except `GET /health` (health check must remain public)
- If `API_KEY` is not set in env, middleware is skipped (dev mode passthrough)
- Returns `401 Unauthorized` with `ErrorResponse` on failure

### Public Run ID
- `POST /run` always generates a server-side run ID as `pub_<uuid4>` (e.g. `pub_3f2a1b...`)
- `run_id` field in `RunRequest` is **removed** — clients no longer supply run IDs
- The `pub_xxx` string is the canonical run ID across: SSE events, GET /run/{id}, DB storage
- Rationale: decouples public-facing ID format from any future internal DB key changes;
  eliminates client ID collision risk; makes run IDs instantly recognizable in logs

### Input Validation (Pydantic field constraints)
- `user_input`: min length 2 chars, max length 8000 chars
  - Note: 2-char min because "no", "ok", "go" are valid short responses in multi-turn contexts
- `prior_context`: max 50 entries (list length cap)
- Each `prior_context` entry validated: must have `role` (str) and `content` (str) keys
- Request body size: 1 MB limit enforced at the ASGI middleware level (before Pydantic)

### CORS Middleware
- Added via `fastapi.middleware.cors.CORSMiddleware`
- Allowed origins configurable via `CORS_ORIGINS` env var (comma-separated)
- Default when env var not set: `["http://localhost:3000", "http://localhost:8080"]`
- Allows credentials, all methods, all headers

### X-Request-ID Header
- Middleware reads `X-Request-ID` from incoming request headers
- If absent, generates a new `uuid4` as the request ID
- Attaches request ID to `structlog` context for all log lines in that request
- Returns the request ID in response headers as `X-Request-ID`

### Stream Tokens (reconnect + duration cap)
- `POST /run` response includes `X-Stream-Token` header alongside SSE body
- Token is a signed value: `<run_id>:<expiry_epoch>:<hmac_sha256>`; signed with `API_KEY`
  (falls back to a random per-startup secret if `API_KEY` not set)
- Token TTL: 10 minutes
- `GET /run/{id}/stream` requires `X-Stream-Token` header (replaces current IP check)
- Invalid/expired token → `403 Forbidden` with `ErrorResponse`
- Stream duration cap: `SSE_MAX_DURATION_SECONDS` env var (default: 300s / 5 min)
- When cap is hit: server sends an `error` SSE event with detail "stream_timeout", then closes

### GET /runs — Run History
- New endpoint: `GET /runs?limit=20&cursor=<run_id>`
- Returns `RunListResponse`: `{ items: RunSummary[], next_cursor: str | None }`
- `RunSummary` fields: `run_id`, `status`, `created_at`, `elapsed_s`, `missions_completed`
- Pagination: cursor-based (cursor = last `run_id` from previous page), limit max 100
- `SQLiteRunStore.list_runs(limit, cursor)` added to `RunStore` protocol + SQLite impl
- Ordered by `created_at DESC` (newest first)

### Claude's Discretion
- Exact HMAC implementation detail (which stdlib module, padding) — use `hmac.new` + `hashlib.sha256`
- Whether stream token is stored in DB or is stateless (prefer stateless — HMAC avoids DB write)
- Error message wording for validation failures

</decisions>

<acceptance_criteria>
## Done When

- [ ] `GET /health` returns 200 without `X-API-Key`; all other routes return 401 without it
  (when `API_KEY` is set in env)
- [ ] `POST /run` with `user_input=""` (empty) returns 422
- [ ] `POST /run` with `user_input="no"` (2 chars) returns 200 / starts run
- [ ] `POST /run` with `user_input` > 8000 chars returns 422
- [ ] `POST /run` with `prior_context` of 51 entries returns 422
- [ ] `POST /run` with body > 1MB returns 413
- [ ] `POST /run` response includes `X-Stream-Token` header
- [ ] `GET /run/{id}/stream` with valid stream token succeeds
- [ ] `GET /run/{id}/stream` with expired/missing stream token returns 403
- [ ] SSE stream auto-closes after `SSE_MAX_DURATION_SECONDS` (default 300s)
- [ ] `POST /run` no longer accepts client-supplied `run_id`; returned run_id starts with `pub_`
- [ ] `GET /runs` returns paginated list of runs ordered newest-first
- [ ] CORS headers present on all responses when `Origin` header is in allowed list
- [ ] `X-Request-ID` present in all response headers; same value echoed in structlog logs
- [ ] All 536 existing tests continue to pass after changes

</acceptance_criteria>

<deferred>
## Deferred Ideas

- Per-client API key store (multiple keys, revocation) — current static key is sufficient for single-tenant
- Rate limiting (requests/minute per key) — valid concern, deferred to a future hardening pass
- DELETE /run/{id} cancellation — useful but orthogonal to security focus
- JWT/OAuth2 — heavy for current single-tenant use case; static key + stream token is proportionate

</deferred>

---

*Phase: 06-fastapi-service-layer*
*Feature context gathered: 2026-03-05*
