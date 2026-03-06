# External Integrations

**Analysis Date:** 2026-03-05

## APIs & External Services

**Payment Processing:**
- Not detected.

**Email/SMS:**
- Not detected.

**External APIs:**
- OpenAI API - Planner/model calls when `P1_PROVIDER=openai`.
  SDK/Client: `openai>=2.0` via `OpenAI` in `src/agentic_workflows/orchestration/langgraph/provider.py`.
  Auth: `OPENAI_API_KEY`; model override via `OPENAI_MODEL`.
  Endpoints used: `client.chat.completions.create(...)`.
- Groq API - Planner/model calls when `P1_PROVIDER=groq`.
  SDK/Client: `groq>=1.0` via `Groq` in `src/agentic_workflows/orchestration/langgraph/provider.py`.
  Auth: `GROQ_API_KEY`; model override via `GROQ_MODEL`.
  Endpoints used: `client.chat.completions.create(...)`.
- Ollama OpenAI-compatible API - Local/self-hosted model serving when `P1_PROVIDER=ollama` or `P1_PROVIDER=ollama_thinking`.
  Integration method: `openai.OpenAI(base_url=...)` in `src/agentic_workflows/orchestration/langgraph/provider.py`.
  Auth: No external secret is required by repo code; the client uses `api_key="ollama"` and connects via `OLLAMA_BASE_URL` or `OLLAMA_HOST`.
  Default endpoint: `http://localhost:11434/v1` in `.env.example`.
- Arbitrary outbound HTTP APIs - Available through the `http_request` tool when the planner selects it.
  Integration method: REST calls via `urllib.request` in `src/agentic_workflows/tools/http_request.py`.
  Auth: Caller-supplied headers/body; optional domain allowlist via `P1_HTTP_ALLOWED_DOMAINS` in `src/agentic_workflows/tools/_security.py`.
  Guardrails: Private IPs are blocked, timeout is capped at 30 seconds, and response size can be limited via `P1_HTTP_MAX_RESPONSE_BYTES`.
- Anthropic runtime API - Not detected as an active provider in `src/agentic_workflows/orchestration/langgraph/provider.py`.
  Current state: `src/agentic_workflows/orchestration/langgraph/graph.py` retains a `P1_PROVIDER=anthropic` `ToolNode` branch, but the provider map does not currently construct an Anthropic client.

## Data Storage

**Databases:**
- SQLite run store - Primary persistence for API run metadata and results.
  Connection: `RUN_STORE_DB` or `.tmp/run_store.db` in `src/agentic_workflows/storage/sqlite.py`.
  Client: stdlib `sqlite3` wrapped with `anyio.to_thread.run_sync`.
  Migrations: Schema is created in code inside `src/agentic_workflows/storage/sqlite.py`; no separate migration directory is present.
- SQLite checkpoint store - Durable graph-node snapshots for replay/debugging.
  Connection: `.tmp/langgraph_checkpoints.db` in `src/agentic_workflows/orchestration/langgraph/checkpoint_store.py`.
  Client: stdlib `sqlite3`.
  Migrations: Schema is created in code inside `src/agentic_workflows/orchestration/langgraph/checkpoint_store.py`.
- SQLite memo store - Deterministic memoization and cache-reuse storage.
  Connection: `.tmp/memo_store.db` in `src/agentic_workflows/orchestration/langgraph/memo_store.py`.
  Client: stdlib `sqlite3`.
  Migrations: Schema is created in code inside `src/agentic_workflows/orchestration/langgraph/memo_store.py`.

**File Storage:**
- Local filesystem only - Session context and generated artifacts are stored on disk, not in a cloud object store.
  SDK/Client: stdlib file I/O in `src/agentic_workflows/cli/user_run.py` and deterministic file tools under `src/agentic_workflows/tools/`.
  Paths: `user_runs/context.json`, `.tmp/`, and repo-relative working-tree paths.
  Buckets/object storage: Not detected.

**Caching:**
- SQLite memo cache - Cache reuse is implemented through `src/agentic_workflows/orchestration/langgraph/memo_store.py`, not Redis or Memcached.
  Connection: local SQLite file `.tmp/memo_store.db`.
  Client: stdlib `sqlite3`.
  External cache service: Not detected.

## Authentication & Identity

**Auth Provider:**
- Custom API key middleware - Protects non-health HTTP routes when `API_KEY` is set.
  Implementation: `APIKeyMiddleware` in `src/agentic_workflows/api/middleware/api_key.py`.
  Token storage: Caller supplies `X-API-Key` on each request; server-side session storage is not implemented.
  Session management: Not applicable.
- HMAC stream tokens - Authorize SSE reconnects for `GET /run/{run_id}/stream`.
  Implementation: `generate_token()` / `validate_token()` in `src/agentic_workflows/api/stream_token.py`.
  Secret source: `API_KEY` or a per-startup random secret in `src/agentic_workflows/api/app.py`.
  Session management: Stateless token verification only.

**OAuth Integrations:**
- Not detected.

## Monitoring & Observability

**Error Tracking:**
- Langfuse - Optional tracing/callback integration when credentials are present.
  Credentials: `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, and optional `LANGFUSE_HOST` in `.env.example`.
  Implementation: `src/agentic_workflows/observability.py`, wired from `src/agentic_workflows/orchestration/langgraph/graph.py` and `src/agentic_workflows/api/routes/run.py`.
  Release tracking: Not detected.

**Analytics:**
- Not detected.

**Logs:**
- Local structured logs - `structlog` in `src/agentic_workflows/api/app.py` plus repo logging helpers in `src/agentic_workflows/logger.py`.
  Integration: stdout/stderr only.
  External log sink: Not detected.

## CI/CD & Deployment

**Hosting:**
- Self-hosted ASGI service - `uvicorn` runs `src/agentic_workflows/api/app.py`.
  Deployment: command-driven/manual from the repo; host/port come from `API_HOST` and `API_PORT` in `.env.example`.
  Managed cloud platform: Not detected.

**CI Pipeline:**
- GitHub Actions - Main quality pipeline in `.github/workflows/ci.yml`.
  Workflows: checkout, `pip install -e ".[dev]"`, `ruff check`, `mypy`, and `pytest tests/ -q`.
  Secrets: Not required for `.github/workflows/ci.yml`; tests force `P1_PROVIDER=scripted`.
- Claude Code GitHub Action - Comment-triggered automation in `.github/workflows/claude.yml`.
  Service: `anthropics/claude-code-action@v1`.
  Secrets: `ANTHROPIC_API_KEY` stored in GitHub Actions secrets.

## Environment Configuration

**Development:**
- Required env vars: at least one active provider path from `OPENAI_API_KEY`, `GROQ_API_KEY`, or `OLLAMA_BASE_URL` / `OLLAMA_HOST`; optional runtime vars live in `.env.example` and code paths under `src/agentic_workflows/api/` and `src/agentic_workflows/tools/_security.py`.
- Secrets location: repo-root `.env` loaded by `python-dotenv` in `src/agentic_workflows/orchestration/langgraph/provider.py`; `.env` is gitignored in `.gitignore`.
- Mock/stub services: `ScriptedProvider` in `tests/conftest.py`; API tests use `httpx.ASGITransport` in `tests/integration/test_api_service.py`.

**Staging:**
- Environment-specific differences: Not detected.
- Data: Not detected.

**Production:**
- Secrets management: Environment variables only; external secret manager integration is not detected.
- Failover/redundancy: provider failover can be configured with `P1_PROVIDER_CHAIN` in `src/agentic_workflows/orchestration/langgraph/provider.py`; storage remains single-node SQLite by default.

## Webhooks & Callbacks

**Incoming:**
- Third-party incoming webhooks: Not detected.

**Outgoing:**
- Langfuse callback handler - Emits tracing callbacks when Langfuse is configured.
  Endpoint: `LANGFUSE_HOST` from `.env.example` (default `https://cloud.langfuse.com`).
  Trigger: graph execution in `src/agentic_workflows/orchestration/langgraph/graph.py` and API-streamed runs in `src/agentic_workflows/api/routes/run.py`.
  Retry logic: Not configured in repo code.
- HTTP tool requests - Outbound calls happen when the planner invokes `http_request`.
  Endpoint: caller-supplied URL subject to allowlist/private-IP checks in `src/agentic_workflows/tools/http_request.py` and `src/agentic_workflows/tools/_security.py`.
  Retry logic: Not detected.

---

*Integration audit: 2026-03-05*
*Update when adding/removing external services*
