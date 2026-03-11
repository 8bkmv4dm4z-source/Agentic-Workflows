# Technology Stack

**Analysis Date:** 2026-03-12

## Languages

**Primary:**
- Python 3.12 - All source code, tests, tooling

**Secondary:**
- SQL - Database migrations in `db/migrations/` (PostgreSQL dialect)

## Runtime

**Environment:**
- CPython 3.12.3 (WSL2 / Linux)

**Package Manager:**
- pip with setuptools>=75.0 build backend
- Lockfile: Not present (pyproject.toml specifies version ranges only)
- Install: `pip install -e ".[dev]"`

## Frameworks

**Core:**
- LangGraph 1.0.10 (`langgraph>=1.0.6,<2.0`) - Graph-based agent orchestration
- LangGraph Prebuilt 1.0.x (`langgraph-prebuilt>=1.0.6,<1.1.0`) - Pre-built graph nodes
- FastAPI 0.135.1 (`fastapi>=0.115`) - REST/SSE API server
- Pydantic 2.12.5 (`pydantic>=2.12,<3.0`) - Data validation and schemas

**LLM Provider SDKs:**
- OpenAI 2.24.0 (`openai>=2.0`) - OpenAI API and OpenAI-compatible endpoints (Ollama, llama-cpp)
- Groq 1.0.0 (`groq>=1.0`) - Groq API
- langchain-anthropic 1.3.4 (`langchain-anthropic>=0.3.0`) - Anthropic Claude via LangChain
- langchain-core 1.2.17 - Structural tools (`StructuredTool`) for LangGraph nodes

**HTTP:**
- httpx 0.28.1 (`httpx>=0.28`) - Async HTTP client used in providers and tools

**Logging/Output:**
- structlog 25.5.0 (`structlog>=25.0`) - Structured logging throughout
- rich 14.3.3 (`rich>=14.0`) - Terminal UI for run output

**ASGI/Server:**
- uvicorn 0.41.0 (`uvicorn>=0.34`) - ASGI server for FastAPI app
- sse-starlette (`sse-starlette>=3.3`) - Server-Sent Events streaming

**Database:**
- psycopg 3.3.3 with binary extension (`psycopg[binary]>=3.2`) - PostgreSQL async driver
- psycopg_pool (`psycopg_pool>=3.2`) - Connection pool for Postgres

**Utilities:**
- python-dotenv 1.x (`python-dotenv>=1.0`) - `.env` loading
- anyio 4.12.1 (`anyio>=4.0`) - Async thread offload for SQLite
- requests 2.x (`requests>=2.32`) - HTTP in tools (e.g., `http_request.py`)

**Testing:**
- pytest 8.x (`pytest>=8.0`) - Test runner
- pytest-asyncio (`pytest-asyncio>=0.24`) - Async test support, `asyncio_mode = "auto"`
- pytest-cov (`pytest-cov>=6.0`) - Coverage reporting

**Build/Dev:**
- ruff 0.11.x (`ruff>=0.11`) - Linting and formatting (`line-length=100`, `target-version=py312`)
- mypy 1.10.x (`mypy>=1.10`) - Type checking (`python_version = "3.12"`)
- pre-commit 4.x (`pre-commit>=4.0`) - Git hooks

## Optional / Extra Dependencies

**Observability** (`pip install ".[observability]"`):
- langfuse 3.14.5 (`langfuse>=3.0`) - LLM tracing and evaluation; gracefully no-ops when absent

**Semantic Context / RAG** (`pip install ".[context]"`):
- fastembed 0.3.x (`fastembed>=0.3`) - Local embedding via BAAI/bge-small-en-v1.5 (384-dim, ~24MB)
  - Default in CI/dev: `MockEmbeddingProvider` (deterministic, no download)
  - Source: `src/agentic_workflows/context/embedding_provider.py`

## Key Dependencies

**Critical:**
- `langgraph` - The entire orchestration engine depends on this; graph compiled once at startup
- `pydantic` - Used for all schema contracts: `ToolAction`, `FinishAction`, `TaskHandoff`, `HandoffResult`, `RunState`
- `openai` SDK - Used as OpenAI-compatible client for Ollama and llama-cpp endpoints as well

**Infrastructure:**
- `psycopg[binary]` - PostgreSQL backend for checkpoints, memos, run store, mission context store
- `structlog` - Universal logging; all modules use `get_logger()` from `src/agentic_workflows/logger.py`
- `python-dotenv` - `.env` loaded at module import time in `provider.py` via `load_dotenv()`

## Configuration

**Environment:**
- All runtime config via `.env` (not committed); `.env.example` documents all variables
- Key config families:
  - `P1_PROVIDER` (ollama | groq | openai | llama-cpp) or `P1_PROVIDER_CHAIN=groq,ollama`
  - Provider-specific: `OPENAI_API_KEY`, `OPENAI_MODEL`, `GROQ_API_KEY`, `GROQ_MODEL`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `LLAMA_CPP_BASE_URL`, `LLAMA_CPP_MODEL`
  - Tuning: `P1_PROVIDER_TIMEOUT_SECONDS` (30), `P1_PLAN_CALL_TIMEOUT_SECONDS` (45), `P1_PROVIDER_MAX_RETRIES` (2)
  - Database: `DATABASE_URL` (absent = SQLite in `.tmp/`; set = PostgreSQL)
  - API server: `API_HOST`, `API_PORT` (8000), `API_KEY` (unset = dev passthrough)
  - Observability: `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_HOST`
  - RAG: `EMBEDDING_PROVIDER` (mock | fastembed)
  - Tool sandboxing: `P1_BASH_ENABLED`, `P1_TOOL_SANDBOX_ROOT`, `P1_BASH_DENIED_PATTERNS`, `P1_HTTP_ALLOWED_DOMAINS`

**Build:**
- `pyproject.toml` - Single source of truth for project metadata, deps, ruff, mypy, pytest config
- `Makefile` - Developer workflow commands (`make run`, `make test`, `make lint`, etc.)
- `Dockerfile` - Single-stage `python:3.12-slim` build; production deps only
- `docker-compose.yml` - Postgres (pgvector/pgvector:pg16) + FastAPI API service

## Platform Requirements

**Development:**
- Python 3.12+
- Docker Desktop (for `make user-run` full stack mode)
- Provider API key OR local Ollama/llama-server running

**Production:**
- Docker container via `Dockerfile` (exposes port 8000)
- PostgreSQL 16 with pgvector extension (via `pgvector/pgvector:pg16` image)
- Postgres port: 5433 on host (avoids conflict with local installs), 5432 inside Docker

---

*Stack analysis: 2026-03-12*
