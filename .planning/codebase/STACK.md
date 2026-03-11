# Technology Stack

**Analysis Date:** 2026-03-12

## Languages

**Primary:**
- Python 3.12 - All source code: `src/agentic_workflows/`, `tests/`

**Secondary:**
- SQL - Database migrations in `db/migrations/` (PostgreSQL dialect, pgvector extension)

## Runtime

**Environment:**
- CPython 3.12.3 (installed: 3.12.3)
- Minimum required: `>=3.12` (enforced in `pyproject.toml`)

**Package Manager:**
- pip with editable install (`pip install -e ".[dev]"`)
- Lockfile: Not present — dependency ranges specified in `pyproject.toml`

**Containerization:**
- Docker via `Dockerfile` (python:3.12-slim base)
- Docker Compose via `docker-compose.yml` (Postgres + API services)

## Frameworks

**Core Orchestration:**
- LangGraph 1.0.10 (`langgraph>=1.0.6,<2.0`) - State graph for multi-agent orchestration; compiled once at startup
- LangGraph Prebuilt 1.0.x (`langgraph-prebuilt>=1.0.6,<1.1.0`) - Prebuilt node utilities

**LLM Provider Bindings:**
- langchain-anthropic 1.3.4 (`langchain-anthropic>=0.3.0`) - Anthropic Claude provider path
- openai 2.24.0 (`openai>=2.0`) - OpenAI and Ollama/llama-cpp (OpenAI-compatible) provider path
- groq 1.0.0 (`groq>=1.0`) - Groq provider path

**Web Framework:**
- FastAPI 0.135.1 (`fastapi>=0.115`) - REST + SSE streaming API; entry point `src/agentic_workflows/api/app.py`
- Uvicorn 0.41.0 (`uvicorn>=0.34`) - ASGI server; exposed on port 8000
- sse-starlette (`sse-starlette>=3.3`) - Server-Sent Events for streaming run results

**Data Validation:**
- Pydantic 2.12.5 (`pydantic>=2.12,<3.0`) - All schemas, state types, handoff models

**Testing:**
- pytest 9.0.2 (`pytest>=8.0`) - Test runner
- pytest-asyncio 1.3.0 (`pytest-asyncio>=0.24`) - Async test support; `asyncio_mode = "auto"`
- pytest-cov 7.0.0 (`pytest-cov>=6.0`) - Coverage reporting

## Key Dependencies

**Critical:**
- `langgraph>=1.0.6,<2.0` — Core graph engine; breaking changes expected across major versions
- `pydantic>=2.12,<3.0` — Used for all typed schemas; v2 API (`model_validate`, `model_dump`)
- `langchain-anthropic>=0.3.0` — Required for Anthropic/Claude provider path in graph
- `openai>=2.0` — Required for OpenAI, Ollama, and llama-cpp provider paths (OpenAI-compatible wire format)

**Infrastructure:**
- `psycopg[binary]>=3.2` (3.3.3) — PostgreSQL async driver; bundled libpq (no system deps)
- `psycopg_pool>=3.2` (3.3.0) — Connection pool; `min_size=2, max_size=10` in production
- `httpx>=0.28` (0.28.1) — HTTP client used inside provider adapters for timeout control
- `structlog>=25.0` (25.5.0) — Structured logging throughout
- `rich>=14.0` (14.3.3) — Terminal UI for run display (`run_ui.py`, `run.py`)
- `anyio>=4.0` (4.12.1) — Async primitives; used in SQLite run store for thread offloading
- `requests>=2.32` — Used by tool implementations requiring simple HTTP

**Optional Extras:**
- `langfuse>=3.0` (optional `[observability]`) — LLM tracing; graceful no-op if absent; see `src/agentic_workflows/observability.py`
- `fastembed>=0.3` (optional `[context]`) — ONNX embeddings (BAAI/bge-small-en-v1.5, 384-dim); see `src/agentic_workflows/context/embedding_provider.py`

## Build / Dev Tools

**Linting & Formatting:**
- ruff 0.15.4 (`ruff>=0.11`) — Both lint (`ruff check`) and format (`ruff format`); line-length 100, target py312
- Rules: `E, F, I, UP, B, SIM`; `E402` and `E501` ignored

**Type Checking:**
- mypy 1.10+ (`mypy>=1.10`) — Strict return-any and unused-config warnings; `ignore_missing_imports = true`
- Several modules explicitly excluded via `[[tool.mypy.overrides]]` in `pyproject.toml`

**Pre-commit:**
- pre-commit 4.0+ with ruff hooks (`ruff` + `ruff-format`) configured in `.pre-commit-config.yaml`

**Build Backend:**
- setuptools>=75.0 with `find` packages discovery from `src/`

## Configuration

**Environment:**
- All runtime config via `.env` file at repo root (loaded via `python-dotenv`)
- `.env.example` documents all variables
- Key variable: `P1_PROVIDER` selects LLM backend (`openai` | `groq` | `ollama` | `llama-cpp`)
- `DATABASE_URL` selects storage backend: absent → SQLite (`.tmp/`), present → PostgreSQL

**Build:**
- `pyproject.toml` — single source of truth for deps, tool config, test paths
- `Makefile` — convenience commands for all common workflows

## Platform Requirements

**Development:**
- Python 3.12+
- `.env` configured with at least one provider key
- SQLite used by default (no external services needed)
- Optional: Docker Desktop for Postgres + full API stack (`make user-run`)

**Production:**
- Docker + Docker Compose (`docker-compose.yml`)
- PostgreSQL 16 with pgvector extension (`pgvector/pgvector:pg16` image)
- `DATABASE_URL` environment variable required for Postgres backend
- Uvicorn serving FastAPI on port 8000

---

*Stack analysis: 2026-03-12*
