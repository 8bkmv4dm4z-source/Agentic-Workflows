# Technology Stack

**Analysis Date:** 2026-03-05

## Languages

**Primary:**
- Python 3.12+ - All application/runtime code lives under `src/agentic_workflows/`, with tests in `tests/` and the package contract in `pyproject.toml`.

**Secondary:**
- YAML (not versioned) - CI and automation config live in `.github/workflows/ci.yml`, `.github/workflows/claude.yml`, and `.pre-commit-config.yaml`.
- Markdown (not versioned) - Operator docs and directives live in `README.md`, `src/agentic_workflows/README.md`, and `src/agentic_workflows/directives/*.md`.

## Runtime

**Environment:**
- CPython 3.12+ - Declared by `requires-python = ">=3.12"` in `pyproject.toml`.
- ASGI + CLI runtime - `src/agentic_workflows/api/app.py` serves the HTTP API via `uvicorn`, while `src/agentic_workflows/orchestration/langgraph/run.py` and `src/agentic_workflows/cli/user_run.py` provide CLI entrypoints.
- Optional local model runtime - `src/agentic_workflows/orchestration/langgraph/provider.py` supports local Ollama through `OLLAMA_BASE_URL` / `OLLAMA_HOST`, with `.env.example` defaulting to `http://localhost:11434/v1`.

**Package Manager:**
- `pip` with `setuptools.build_meta` - Install flow is `pip install -e ".[dev]"` in `AGENTS.md`, and the build backend is declared in `pyproject.toml`.
- Lockfile: Not detected (`uv.lock`, `poetry.lock`, `requirements*.txt`, and `package-lock.json` are absent).

## Frameworks

**Core:**
- LangGraph 1.x - State-machine orchestration in `src/agentic_workflows/orchestration/langgraph/graph.py`, `src/agentic_workflows/orchestration/langgraph/specialist_executor.py`, and `src/agentic_workflows/orchestration/langgraph/specialist_evaluator.py`.
- FastAPI 0.115+ - HTTP service layer in `src/agentic_workflows/api/app.py` and `src/agentic_workflows/api/routes/`.
- Pydantic 2.12+ - Typed schemas and validation in `src/agentic_workflows/schemas.py` and `src/agentic_workflows/api/models.py`.

**Testing:**
- pytest 8+ - Main test runner configured in `pyproject.toml` and used across `tests/unit/`, `tests/integration/`, and `tests/eval/`.
- pytest-asyncio 0.24+ - Async test support enabled by `asyncio_mode = "auto"` in `pyproject.toml`.
- httpx ASGI transport - Integration/eval API tests exercise the FastAPI app in `tests/integration/test_api_service.py` and `tests/eval/conftest.py`.

**Build/Dev:**
- setuptools 75+ - Packaging backend declared in `pyproject.toml`.
- Ruff 0.11+ - Lint/format tooling configured in `pyproject.toml`, `.pre-commit-config.yaml`, and `.github/workflows/ci.yml`.
- mypy 1.10+ - Static type checking configured in `pyproject.toml` and run in `.github/workflows/ci.yml`.
- Uvicorn 0.34+ - ASGI server dependency used by `src/agentic_workflows/api/app.py`.

## Key Dependencies

**Critical:**
- `langgraph>=1.0.6,<2.0` - Core orchestration engine for the `plan -> execute -> policy -> finalize` graph in `src/agentic_workflows/orchestration/langgraph/graph.py`.
- `langgraph-prebuilt>=1.0.6,<1.1.0` - Supplies `ToolNode` / `tools_condition` for the guarded Anthropic branch in `src/agentic_workflows/orchestration/langgraph/graph.py`.
- `pydantic>=2.12,<3.0` - Schema validation for actions, API models, and typed state contracts in `src/agentic_workflows/schemas.py` and `src/agentic_workflows/api/models.py`.
- `fastapi>=0.115` - HTTP API framework for `src/agentic_workflows/api/app.py`.
- `openai>=2.0` - OpenAI provider client and Ollama OpenAI-compatible client in `src/agentic_workflows/orchestration/langgraph/provider.py`.
- `groq>=1.0` - Groq provider client in `src/agentic_workflows/orchestration/langgraph/provider.py`.
- `sse-starlette>=3.3` - Server-sent events for `/run` and `/run/{run_id}/stream` in `src/agentic_workflows/api/routes/run.py`.
- `anyio>=4.0` - Thread offloading and in-memory stream bridging in `src/agentic_workflows/api/routes/run.py` and `src/agentic_workflows/storage/sqlite.py`.

**Infrastructure:**
- `httpx>=0.28` - API client in `src/agentic_workflows/cli/user_run.py` and transport for API tests in `tests/integration/test_api_service.py`.
- `structlog>=25.0` - Structured API logging in `src/agentic_workflows/api/app.py`.
- `python-dotenv>=1.0` - Loads repo-root `.env` in `src/agentic_workflows/orchestration/langgraph/provider.py`.
- `langfuse>=3.0` (optional extra) - Observability/tracing integration in `src/agentic_workflows/observability.py`.

## Configuration

**Environment:**
- Repo-root `.env` is loaded by `load_dotenv()` in `src/agentic_workflows/orchestration/langgraph/provider.py`; the sample file is `.env.example`, and `.env` is gitignored in `.gitignore`.
- Key runtime variables come from `.env.example` and code paths in `src/agentic_workflows/api/app.py`, `src/agentic_workflows/api/middleware/api_key.py`, and `src/agentic_workflows/tools/_security.py`: `P1_PROVIDER`, `P1_PROVIDER_CHAIN`, `OPENAI_API_KEY`, `GROQ_API_KEY`, `OLLAMA_BASE_URL`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `API_HOST`, `API_PORT`, `RUN_STORE_DB`, `API_KEY`, `CORS_ORIGINS`, `P1_TOOL_SANDBOX_ROOT`, `P1_HTTP_ALLOWED_DOMAINS`, and `SSE_MAX_DURATION_SECONDS`.

**Build:**
- `pyproject.toml` - Package metadata, dependencies, Ruff, pytest, and mypy config.
- `.pre-commit-config.yaml` - Local Ruff hooks.
- `.github/workflows/ci.yml` - CI install/lint/typecheck/test pipeline.
- `.github/workflows/claude.yml` - Comment-triggered Claude Code automation.

## Platform Requirements

**Development:**
- Any platform with Python 3.12+ and stdlib SQLite support; CI runs on `ubuntu-latest` in `.github/workflows/ci.yml`.
- Optional local Ollama server at `http://localhost:11434/v1` when using `P1_PROVIDER=ollama` or `P1_PROVIDER=ollama_thinking`.
- Container tooling: Not detected.

**Production:**
- ASGI deployment via `uvicorn` serving `src/agentic_workflows/api/app.py`.
- Default persistence is local SQLite files: `RUN_STORE_DB` (`.tmp/run_store.db`), `src/agentic_workflows/orchestration/langgraph/checkpoint_store.py` (`.tmp/langgraph_checkpoints.db`), and `src/agentic_workflows/orchestration/langgraph/memo_store.py` (`.tmp/memo_store.db`).
- Managed hosting target, container image, or IaC stack: Not detected.

---

*Stack analysis: 2026-03-05*
*Update after major dependency changes*
