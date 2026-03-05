# External Integrations

**Analysis Date:** 2026-03-05

## APIs & External Services

**Payment Processing:**
- Not detected.

**Email/SMS:**
- Not detected.

**External APIs:**
- OpenAI API - Hosted model backend for planner calls when `P1_PROVIDER=openai`.
  - SDK/Client: `openai>=2.0` in `pyproject.toml`; client code in `src/agentic_workflows/orchestration/langgraph/provider.py` and `src/agentic_workflows/core/llm_provider.py`.
  - Auth: `OPENAI_API_KEY` env var from `.env.example`.
  - Endpoints used: chat completions via `client.chat.completions.create(...)`; JSON-object responses are requested in `src/agentic_workflows/orchestration/langgraph/provider.py`.
- Groq API - Hosted model backend when `P1_PROVIDER=groq`.
  - SDK/Client: `groq>=1.0` in `pyproject.toml`; client code in `src/agentic_workflows/orchestration/langgraph/provider.py` and `src/agentic_workflows/core/llm_provider.py`.
  - Auth: `GROQ_API_KEY` env var from `.env.example`.
  - Endpoints used: chat completions via `client.chat.completions.create(...)`.
- Ollama OpenAI-compatible API - Local/self-hosted model backend when `P1_PROVIDER=ollama` or `P1_PROVIDER=ollama_thinking`.
  - Integration method: OpenAI-compatible HTTP client in `src/agentic_workflows/orchestration/langgraph/provider.py` and `src/agentic_workflows/core/llm_provider.py`.
  - Auth: No real secret detected; code uses the placeholder API key `"ollama"` and resolves `OLLAMA_BASE_URL` / `OLLAMA_HOST` from `.env.example`.
  - Endpoint/base URL: default `http://localhost:11434/v1` from `.env.example` and `_resolve_ollama_base_url()` in `src/agentic_workflows/orchestration/langgraph/provider.py`.
- Langfuse - Optional LLM tracing/observability backend.
  - SDK/Client: optional `langfuse>=3.0` extra in `pyproject.toml`; client/callback code in `src/agentic_workflows/observability.py`.
  - Auth: `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, optional `LANGFUSE_HOST`, and optional `LANGFUSE_DISABLED` from `.env.example`.
  - Integration points: callback handler attached in `src/agentic_workflows/api/routes/run.py`; decorators used in `src/agentic_workflows/orchestration/langgraph/provider.py`.
- Arbitrary outbound HTTP targets - Generic external HTTP access exposed to the planner via the `http_request` tool.
  - Integration method: `urllib.request` in `src/agentic_workflows/tools/http_request.py`.
  - Auth: caller-supplied headers only; no fixed vendor credentials are stored in repo.
  - Guardrails: private IPs blocked in `src/agentic_workflows/tools/http_request.py`; domain allowlist via `P1_HTTP_ALLOWED_DOMAINS` and response-size cap via `P1_HTTP_MAX_RESPONSE_BYTES` in `src/agentic_workflows/tools/_security.py` and `.env.example`.
- Anthropic API - Partial/dormant integration only.
  - Detected surface: `langchain-anthropic>=0.3.0` in `pyproject.toml` and an Anthropic-gated `ToolNode` path in `src/agentic_workflows/orchestration/langgraph/graph.py`.
  - Missing piece: no Anthropic provider adapter is implemented in `src/agentic_workflows/orchestration/langgraph/provider.py`, so this is not a complete current backend.

## Data Storage

**Databases:**
- SQLite - Local durable persistence for API runs, graph checkpoints, and memoization.
  - Connection: `RUN_STORE_DB` env var controls `src/agentic_workflows/storage/sqlite.py`; `src/agentic_workflows/orchestration/langgraph/checkpoint_store.py` uses `.tmp/langgraph_checkpoints.db`; `src/agentic_workflows/orchestration/langgraph/memo_store.py` uses `.tmp/memo_store.db`.
  - Client: Python stdlib `sqlite3` in `src/agentic_workflows/storage/sqlite.py`, `src/agentic_workflows/orchestration/langgraph/checkpoint_store.py`, and `src/agentic_workflows/orchestration/langgraph/memo_store.py`.
  - Migrations: Not applicable (schema is created in code at startup/initialization).
- PostgreSQL / managed external database: Not detected in current runtime code.

**File Storage:**
- Local filesystem - Runtime artifacts and user session context.
  - SDK/Client: Python stdlib file I/O / `pathlib` in `src/agentic_workflows/cli/user_run.py` and tool modules under `src/agentic_workflows/tools/`.
  - Auth: Not applicable.
  - External object storage (S3, GCS, Supabase Storage): Not detected.

**Caching:**
- No external cache service detected.
  - Local cache/memo store: SQLite-backed memoization in `src/agentic_workflows/orchestration/langgraph/memo_store.py`.
  - Redis/Memcached: Not detected.

## Authentication & Identity

**Auth Provider:**
- Not detected.
  - Implementation: `src/agentic_workflows/api/app.py`, `src/agentic_workflows/api/routes/run.py`, `src/agentic_workflows/api/routes/health.py`, and `src/agentic_workflows/api/routes/tools.py` expose the API without user auth middleware, JWT handling, or session storage.
  - Token storage: Not applicable.
  - Session management: Not applicable.

**OAuth Integrations:**
- Not detected.

## Monitoring & Observability

**Tracing:**
- Langfuse - Optional span/callback tracing for model and graph execution.
  - SDK/Client: `langfuse` in `src/agentic_workflows/observability.py`.
  - Host: `LANGFUSE_HOST` in `.env.example` defaults to `https://cloud.langfuse.com`.
  - Integration: `get_langfuse_callback_handler()` in `src/agentic_workflows/observability.py`, used in `src/agentic_workflows/api/routes/run.py`.

**Error Tracking:**
- Not detected (no Sentry, Rollbar, or Bugsnag integration appears in `pyproject.toml` or `src/`).

**Analytics:**
- Not detected.

**Logs:**
- Process-local structured logs via `structlog`.
  - Integration: `src/agentic_workflows/api/app.py`, `src/agentic_workflows/orchestration/langgraph/graph.py`, and `src/agentic_workflows/logger.py`.
  - External log sink: Not detected.

## CI/CD & Deployment

**Hosting:**
- Self-hosted FastAPI/Uvicorn service.
  - Deployment: `uvicorn.run(...)` in `src/agentic_workflows/api/app.py`; `src/agentic_workflows/cli/user_run.py` auto-starts the service locally if it is not running.
  - Environment vars: process env / repo-root `.env` loaded by code in `src/agentic_workflows/orchestration/langgraph/provider.py` and `src/agentic_workflows/core/llm_provider.py`.
  - Cloud hosting vendor: Not detected.

**CI Pipeline:**
- GitHub Actions - quality gate automation.
  - Workflows: `.github/workflows/ci.yml` runs install, `ruff`, `mypy`, and `pytest` on push/PR; tests set `P1_PROVIDER=scripted`.
  - Secrets: none required for `.github/workflows/ci.yml`; live LLM keys are intentionally not used in CI.
- GitHub Actions + Anthropic Claude Code action - comment-driven repository automation.
  - Workflow: `.github/workflows/claude.yml`.
  - Secrets: `ANTHROPIC_API_KEY` GitHub secret passed to `anthropics/claude-code-action@v1`.

## Environment Configuration

**Development:**
- Required env vars: one provider path (`OPENAI_API_KEY`, `GROQ_API_KEY`, or `OLLAMA_BASE_URL` / `OLLAMA_HOST`) plus `P1_PROVIDER`; optional `LANGFUSE_*`, `API_HOST`, `API_PORT`, and `RUN_STORE_DB`, all documented in `.env.example`.
- Secrets location: repo-root `.env` loaded with `python-dotenv` in `src/agentic_workflows/orchestration/langgraph/provider.py` and `src/agentic_workflows/core/llm_provider.py`.
- Mock/stub services: `ScriptedProvider` in `tests/conftest.py`; CI pins `P1_PROVIDER=scripted` in `.github/workflows/ci.yml`; API/eval fixtures wire scripted providers in `tests/eval/conftest.py`.

**Staging:**
- Environment-specific differences: Not detected.
- Data: Not detected.

**Production:**
- Secrets management: process env / `.env` conventions only; no cloud secret manager integration is detected.
- Failover/redundancy: local SQLite persistence only; no replicated database, queue, or multi-region configuration is detected.

## Webhooks & Callbacks

**Incoming:**
- Not detected (no webhook-specific routes under `src/agentic_workflows/api/routes/`).

**Outgoing:**
- Langfuse callback handler - attached during run execution for observability.
  - Endpoint: controlled by `LANGFUSE_HOST` in `.env.example`; callback is constructed in `src/agentic_workflows/observability.py`.
  - Retry logic: Not detected in project code (delegated to the `langfuse` client/library).
- Generic HTTP requests - planner-triggered via `http_request` tool.
  - Endpoint: caller-supplied URL in `src/agentic_workflows/tools/http_request.py`.
  - Retry logic: Not detected.

---

*Integration audit: 2026-03-05*
*Update when adding/removing external services*
