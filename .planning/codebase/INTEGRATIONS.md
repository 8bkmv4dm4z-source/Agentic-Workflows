# External Integrations

**Analysis Date:** 2026-03-12

## APIs & External Services

**LLM Providers (runtime-selectable via `P1_PROVIDER` env var):**

- OpenAI API — Chat completions for planner/executor roles
  - SDK/Client: `openai>=2.0` (`OpenAI` client)
  - Auth: `OPENAI_API_KEY`
  - Model: `OPENAI_MODEL` (default: `gpt-4.1-mini`)
  - Implementation: `src/agentic_workflows/orchestration/langgraph/provider.py`

- Groq API — Fast inference via Groq cloud
  - SDK/Client: `groq>=1.0` (`Groq` client)
  - Auth: `GROQ_API_KEY`
  - Model: `GROQ_MODEL` (default: `llama-3.3-70b-versatile`)
  - Implementation: `src/agentic_workflows/orchestration/langgraph/provider.py`

- Anthropic Claude — Via LangChain binding (used in LangGraph Anthropic provider path)
  - SDK/Client: `langchain-anthropic>=0.3.0`
  - Auth: `ANTHROPIC_API_KEY` (standard LangChain env var)
  - Implementation: `src/agentic_workflows/orchestration/langgraph/provider.py`

- Ollama — Local OpenAI-compatible endpoint
  - SDK/Client: `openai>=2.0` (OpenAI-compatible wire format)
  - Auth: `OLLAMA_API_KEY` (optional, defaults to `"ollama"`)
  - Base URL: `OLLAMA_BASE_URL` (default: `http://localhost:11434/v1`)
  - Model: `OLLAMA_MODEL` (default: `qwen2.5:14b`)
  - Implementation: `src/agentic_workflows/orchestration/langgraph/provider.py`

- llama-cpp (llama-server) — Self-hosted OpenAI-compatible server, SYCL/CPU
  - SDK/Client: `openai>=2.0` (OpenAI-compatible wire format)
  - Auth: Not required
  - Base URL: `LLAMA_CPP_BASE_URL` (default: `http://127.0.0.1:8080/v1`)
  - Model: `LLAMA_CPP_MODEL` (or `"auto"` to detect via `GET /v1/models`)
  - SYCL multi-server: `LLAMA_CPP_PLANNER_PORT` / `LLAMA_CPP_EXECUTOR_PORT` for split routing
  - Implementation: `src/agentic_workflows/orchestration/langgraph/provider.py`

**Provider Chain Fallback:**
- `P1_PROVIDER_CHAIN=groq,ollama` — tries providers left-to-right on failure
- Timeout tuning: `P1_PROVIDER_TIMEOUT_SECONDS` (30s), `P1_PLAN_CALL_TIMEOUT_SECONDS` (45s)
- Retry config: `P1_PROVIDER_MAX_RETRIES` (2), `P1_PROVIDER_RETRY_BACKOFF_SECONDS` (1.0s)

## Data Storage

**Databases:**

- PostgreSQL 16 (production)
  - Image: `pgvector/pgvector:pg16` (includes pgvector extension)
  - Connection: `DATABASE_URL` env var (e.g., `postgresql://agentic:agentic@localhost:5433/agentic_workflows`)
  - Client: `psycopg[binary]>=3.2` + `psycopg_pool>=3.2`
  - Connection pool: `min_size=2, max_size=10`
  - Docker port: `5433:5432` (avoids conflict with local installs)
  - Stores: runs (`PostgresRunStore`), checkpoints (`PostgresCheckpointStore`), memos (`PostgresMemoStore`)
  - Implementations: `src/agentic_workflows/storage/postgres.py`, `src/agentic_workflows/orchestration/langgraph/checkpoint_postgres.py`, `src/agentic_workflows/orchestration/langgraph/memo_postgres.py`

- SQLite (development / testing default)
  - Activated when `DATABASE_URL` is absent
  - Files written to `.tmp/` directory (e.g., `RUN_STORE_DB=.tmp/run_store.db`)
  - WAL journal mode enabled; thread-safe via `threading.Lock`
  - Stores: runs (`SQLiteRunStore`), checkpoints (`SQLiteCheckpointStore`), memos (`SQLiteMemoStore`)
  - Implementations: `src/agentic_workflows/storage/sqlite.py`, `src/agentic_workflows/orchestration/langgraph/checkpoint_store.py`, `src/agentic_workflows/orchestration/langgraph/memo_store.py`

**Database Migrations:**
- Location: `db/migrations/` (run automatically by Docker Compose Postgres entrypoint)
  - `001_init.sql` — Base runs table
  - `002_foundation.sql` — pgvector extension + `file_chunks` and `solved_tasks` tables (384-dim embeddings)
  - `003_mission_contexts.sql` — Mission context store with tsvector (BM25) + pgvector (HNSW cosine) indexes
  - `004_mission_artifacts.sql` — Mission artifact storage
  - `005_sub_task_cursors.sql` — Sub-task cursor persistence
  - `006_tool_result_cache.sql` — Tool result caching table

**File Storage:**
- Local filesystem only (no cloud file storage)
- Agent writes controlled by `AGENT_WORKDIR` env var (default: `./workspace/`)
- Readable root set by `AGENT_ROOT` env var
- Write size cap: `P1_WRITE_FILE_MAX_BYTES` (default: 10 MB)
- Sandboxing: `P1_TOOL_SANDBOX_ROOT` restricts file tools to a directory

**Caching:**
- In-process tool result cache: `src/agentic_workflows/storage/tool_result_cache.py`
- Memoization policy enforced via `memoize` tool (`src/agentic_workflows/tools/memoize.py`)
- No external cache service (Redis, Memcached, etc.)

## Authentication & Identity

**API Key Auth (FastAPI):**
- Middleware: `src/agentic_workflows/api/middleware/api_key.py`
- Auth: `API_KEY` env var; if unset → dev passthrough (no auth enforced)
- Request ID: `src/agentic_workflows/api/middleware/request_id.py`

**SSE Stream Tokens:**
- Stateless HMAC tokens for SSE reconnect authorization
- Implementation: `src/agentic_workflows/api/stream_token.py`

**LLM Provider Auth:**
- All provider keys are env vars (see LLM Providers section above)
- No user identity system — single-tenant design

## Monitoring & Observability

**LLM Tracing (optional):**
- Langfuse — cloud LLM observability platform
  - Package: `langfuse>=3.0` (optional extra `[observability]`)
  - Auth: `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`
  - Host: `LANGFUSE_HOST` (default: `https://cloud.langfuse.com`)
  - Graceful degradation: all decorators become no-ops if not installed/configured
  - Reports: schema compliance scores, trace spans
  - Implementation: `src/agentic_workflows/observability.py`

**Structured Logging:**
- structlog 25.5.0 — JSON-structured log output
- Dual logging (console + file) via `setup_dual_logging()` in `src/agentic_workflows/logger.py`
- Log dir controlled by `GSD_LOG_DIR` env var (default: `.tmp`)

**Error Tracking:**
- No dedicated error tracking service (Sentry, etc.) detected

## Vector Search / Embeddings (Phase 7.3)

**Embedding Provider:**
- Mock (default, CI-safe): `MockEmbeddingProvider` — deterministic 384-dim, SHA-256 seeded
- FastEmbed (optional): `FastEmbedProvider` — BAAI/bge-small-en-v1.5, ONNX-based, ~24MB download
  - Package: `fastembed>=0.3` (optional extra `[context]`)
  - Controlled by: `EMBEDDING_PROVIDER` env var (`mock` | `fastembed`)
  - Implementation: `src/agentic_workflows/context/embedding_provider.py`

**Vector Database:**
- pgvector extension on PostgreSQL (active when `DATABASE_URL` set)
- 384-dimensional float32 vectors, HNSW cosine similarity index
- Used for mission context semantic search (`src/agentic_workflows/storage/mission_context_store.py`) and artifact retrieval (`src/agentic_workflows/storage/artifact_store.py`)

## CI/CD & Deployment

**Hosting:**
- Docker Compose (`docker-compose.yml`) for self-hosted deployment
- No cloud hosting config detected (no Heroku, Railway, Fly.io, etc.)

**CI Pipeline:**
- No CI config detected (no `.github/workflows/`, `.circleci/`, etc.)

**Pre-commit Hooks:**
- ruff lint + ruff format via `.pre-commit-config.yaml`

## HTTP Tool (Agent-callable)

**Outbound HTTP from agent:**
- `HttpRequestTool` (`src/agentic_workflows/tools/http_request.py`) — agent can call arbitrary URLs
- Uses stdlib `urllib.request` (not httpx/requests)
- Private IP ranges blocked by default (SSRF protection in `src/agentic_workflows/tools/_security.py`)
- Domain allowlist: `P1_HTTP_ALLOWED_DOMAINS` env var
- Response cap: `P1_HTTP_MAX_RESPONSE_BYTES` (default: 10 MB)
- Timeout cap: 30 seconds

## Webhooks & Callbacks

**Incoming:**
- None detected — no webhook receiver endpoints in `src/agentic_workflows/api/routes/`

**Outgoing:**
- Agent can make outbound HTTP via `HttpRequestTool` (see above); not a structured webhook system

## API Surface

**REST Endpoints (FastAPI):**
- `POST /run` — Submit task; streams SSE events (`EventSourceResponse` via `sse-starlette`)
- `GET /run/{id}` — Retrieve completed run result
- `GET /run/{id}/stream` — Re-stream SSE for a completed run
- `GET /runs` — List runs
- `GET /tools` — List available agent tools
- `GET /health` — Health check

**CORS:**
- Configured via `CORS_ORIGINS` env var (comma-separated); permissive in dev

---

*Integration audit: 2026-03-12*
