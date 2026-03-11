# External Integrations

**Analysis Date:** 2026-03-12

## LLM Providers

**OpenAI:**
- Purpose: Primary cloud LLM for plan and execute nodes
- SDK: `openai>=2.0` via `OpenAIChatProvider` in `src/agentic_workflows/orchestration/langgraph/provider.py`
- Auth: `OPENAI_API_KEY` env var
- Model: `OPENAI_MODEL` (default: `gpt-4.1-mini`)
- Response format: JSON schema-guided (`json_schema` mode, falls back to `json_object`)

**Groq:**
- Purpose: Fast cloud inference (open-weight models)
- SDK: `groq>=1.0` via `GroqChatProvider` in `src/agentic_workflows/orchestration/langgraph/provider.py`
- Auth: `GROQ_API_KEY` env var
- Model: `GROQ_MODEL` (default: `llama-3.3-70b-versatile`)

**Ollama:**
- Purpose: Local LLM inference (self-hosted)
- SDK: `openai` SDK pointed at OpenAI-compatible Ollama endpoint OR native Ollama chat API
- Auth: `OLLAMA_API_KEY` (optional), `OLLAMA_BASE_URL` (default: `http://localhost:11434/v1`)
- Model: `OLLAMA_MODEL` (default: `qwen2.5:14b`)
- Implementation: `OllamaChatProvider` in `src/agentic_workflows/orchestration/langgraph/provider.py`
- Notes: Native chat API mode toggleable via `OLLAMA_USE_NATIVE_CHAT_API=true`

**llama-cpp (llama-server):**
- Purpose: Local GGUF model inference via SYCL/CPU; supports multi-server planner/executor split
- SDK: `openai` SDK pointed at llama-server OpenAI-compatible endpoint
- Auth: None (hardcoded key `"llama-cpp"`)
- Config: `LLAMA_CPP_BASE_URL` (default: `http://127.0.0.1:8080/v1`), `LLAMA_CPP_MODEL`
- Implementation: `LlamaCppChatProvider` in `src/agentic_workflows/orchestration/langgraph/provider.py`
- Notes: Supports GBNF grammar enforcement for JSON; multi-port routing via `LLAMA_CPP_PLANNER_PORT` / `LLAMA_CPP_EXECUTOR_PORT`

**Anthropic (LangChain path):**
- Purpose: Anthropic Claude models via LangChain tool-call graph path
- SDK: `langchain-anthropic>=0.3.0`, `langchain-core` `StructuredTool`
- Auth: Anthropic API key (via langchain-anthropic standard env var)
- Usage: Conditional graph path in `src/agentic_workflows/orchestration/langgraph/graph.py` (Anthropic provider path uses `add_conditional_edges("plan", tools_condition, ...)`)

**Provider Chain / Fallback:**
- Configured via `P1_PROVIDER_CHAIN=groq,ollama` for left-to-right fallback on failure
- Factory: `get_provider()` in `src/agentic_workflows/orchestration/langgraph/provider.py`

## Data Storage

**Databases:**
- **SQLite** (dev/test default)
  - Location: `.tmp/run_store.db` (configurable via `RUN_STORE_DB`)
  - Client: Python stdlib `sqlite3`, WAL mode, offloaded via `anyio`
  - Implementation: `src/agentic_workflows/storage/sqlite.py` (`SQLiteRunStore`)
  - Auto-created on first run; no migrations needed

- **PostgreSQL 16 with pgvector** (production)
  - Connection: `DATABASE_URL` env var (e.g. `postgresql://agentic:agentic@localhost:5433/agentic_workflows`)
  - Client: `psycopg[binary]>=3.2` with `psycopg_pool` connection pool
  - Docker image: `pgvector/pgvector:pg16` (maps to host port 5433)
  - Run store: `src/agentic_workflows/storage/postgres.py` (`PostgresRunStore`)
  - Checkpoint store: `src/agentic_workflows/orchestration/langgraph/checkpoint_postgres.py` (`PostgresCheckpointStore`)
  - Memo store: `src/agentic_workflows/orchestration/langgraph/memo_postgres.py` (`PostgresMemoStore`)
  - Migrations: SQL files in `db/migrations/` (001–006), auto-run by Docker entrypoint on first start
  - Key migration files: `001_init.sql`, `002_foundation.sql`, `003_mission_contexts.sql`, `004_mission_artifacts.sql`, `005_sub_task_cursors.sql`, `006_tool_result_cache.sql`

**SQLite Checkpoint/Memo Stores (dev):**
- Checkpoint: `src/agentic_workflows/orchestration/langgraph/checkpoint_store.py` — file-based SQLite checkpoints
- Memo: `src/agentic_workflows/orchestration/langgraph/memo_store.py` — file-based SQLite memos
- Default path: `.tmp/` directory (created on demand)

**File Storage:**
- Local filesystem only; agent writes go to `workspace/` directory (configurable via `AGENT_WORKDIR`)
- `P1_TOOL_SANDBOX_ROOT` restricts file tool access to a specified directory
- Write/read size capped via `P1_WRITE_FILE_MAX_BYTES` / `P1_READ_FILE_MAX_BYTES` (default 10 MB)

**Caching:**
- Tool result cache: `src/agentic_workflows/storage/tool_result_cache.py` (in-process / Postgres-backed)

## Semantic Embeddings / RAG

**Provider:**
- Default (CI-safe): `MockEmbeddingProvider` — deterministic 384-dim SHA-256-seeded vectors, no download
- Production optional: `FastEmbedProvider` using BAAI/bge-small-en-v1.5 model (~24MB download on first use)
- Controlled by: `EMBEDDING_PROVIDER=mock` (default) or `EMBEDDING_PROVIDER=fastembed`
- Requires: `pip install ".[context]"` for fastembed
- Source: `src/agentic_workflows/context/embedding_provider.py`
- Used by: `MissionContextStore` and `ArtifactStore` for semantic context retrieval

## Observability

**LLM Tracing — Langfuse (optional):**
- Purpose: LLM call tracing, schema compliance scoring, session tracking
- SDK: `langfuse>=3.0` (optional extra: `pip install ".[observability]"`)
- Auth: `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY` env vars
- Host: `LANGFUSE_HOST` (default: `https://cloud.langfuse.com`)
- Integration: `src/agentic_workflows/observability.py` — gracefully no-ops when package absent or env vars unset
- Features wired: `@observe()` decorator, `get_langfuse_callback_handler()` for LangChain, `report_schema_compliance()` numeric scores

**Structured Logs:**
- Tool: `structlog` throughout, with dual logging (console + file) via `setup_dual_logging()` in `src/agentic_workflows/logger.py`
- Log files: `.tmp/` directory (configurable via `GSD_LOG_DIR`)

## Authentication

**API Key (FastAPI REST API):**
- Middleware: `APIKeyMiddleware` in `src/agentic_workflows/api/middleware/api_key.py`
- Header: `X-API-Key`
- Config: `API_KEY` env var; unset = dev passthrough (all requests pass)
- Health endpoint (`/health`) always public
- No external auth provider; custom middleware only

## API Server

**FastAPI REST + SSE:**
- App: `src/agentic_workflows/api/app.py`
- Routes:
  - `POST /runs` — submit a new run, returns SSE stream of events (`src/agentic_workflows/api/routes/run.py`)
  - `GET /runs/{run_id}` — fetch completed run result
  - `GET /runs/{run_id}/stream` — replay run events as SSE
  - `GET /health` — health check
  - `GET /tools` — list registered tools (`src/agentic_workflows/api/routes/tools.py`)
- Streaming: Server-Sent Events via `sse-starlette`; `SSE_MAX_DURATION_SECONDS` configurable (default 1800s)
- CORS: `CORSMiddleware`; domains configurable via `CORS_ORIGINS` env var
- Middleware: `RequestIDMiddleware`, `APIKeyMiddleware`

## CI/CD & Deployment

**Hosting:**
- Docker container (single-stage `python:3.12-slim`) exposing port 8000
- `docker-compose.yml` orchestrates Postgres + API service
- Docker commands via `docker.exe` (WSL2 Docker Desktop integration)

**CI Pipeline:**
- Not detected (no GitHub Actions, CircleCI, or similar config found)

## Webhooks & Callbacks

**Incoming:**
- None — no webhook endpoints defined in API routes

**Outgoing:**
- None — agent tools include `http_request` (`src/agentic_workflows/tools/http_request.py`) for arbitrary HTTP calls, controlled by `P1_HTTP_ALLOWED_DOMAINS` allowlist and `P1_HTTP_MAX_RESPONSE_BYTES` cap; but no system-level outgoing webhook calls

## Environment Configuration

**Required env vars (production):**
- `P1_PROVIDER` — LLM provider selection
- Provider-specific key: `OPENAI_API_KEY` or `GROQ_API_KEY` or `OLLAMA_BASE_URL`
- `DATABASE_URL` — Postgres connection string (absent = SQLite)

**Optional env vars:**
- `LANGFUSE_SECRET_KEY` + `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_HOST` — observability
- `EMBEDDING_PROVIDER=fastembed` — semantic context (requires `.[context]` install)
- `API_KEY` — REST API authentication key
- `CORS_ORIGINS` — allowed CORS origins
- `AGENT_WORKDIR`, `AGENT_ROOT` — agent filesystem sandbox paths

**Secrets location:**
- `.env` file at project root (not committed; `.env.example` is the template)

---

*Integration audit: 2026-03-12*
