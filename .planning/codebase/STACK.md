# Technology Stack

**Analysis Date:** 2026-03-05

## Languages

**Primary:**
- Python 3.12+ - All executable application, API, CLI, orchestration, storage, and test code in `pyproject.toml`, `src/agentic_workflows/`, and `tests/`.

**Secondary:**
- Markdown (version not applicable) - Directive and operational docs in `README.md`, `src/agentic_workflows/README.md`, `src/agentic_workflows/orchestration/langgraph/README.md`, and `src/agentic_workflows/directives/planner.md`.
- YAML (version not applicable) - Automation/config files in `.github/workflows/ci.yml`, `.github/workflows/claude.yml`, and `.pre-commit-config.yaml`.

## Runtime

**Environment:**
- CPython 3.12+ - Declared in `pyproject.toml` (`requires-python = ">=3.12"`) and pinned to Python 3.12 in `.github/workflows/ci.yml`.
- ASGI server runtime via `uvicorn>=0.34` - API service entrypoint is `src/agentic_workflows/api/app.py`.
- CLI runtime via `python -m ...` entrypoints - documented in `AGENTS.md` and `README.md`.
- Browser/frontend runtime: Not detected.

**Package Manager:**
- `pip` with editable installs (version not pinned in repo) - used by `pip install -e ".[dev]"` in `AGENTS.md` and `.github/workflows/ci.yml`.
- Build backend: `setuptools>=75.0` via `build-system` in `pyproject.toml`.
- Lockfile: Not detected (`poetry.lock`, `uv.lock`, `Pipfile.lock`, `requirements*.txt` not present).

## Frameworks

**Core:**
- `langgraph>=1.0.6,<2.0` - State-machine orchestration runtime in `pyproject.toml` and `src/agentic_workflows/orchestration/langgraph/graph.py`.
- `langgraph-prebuilt>=1.0.6,<1.1.0` - `ToolNode` / `tools_condition` support in `pyproject.toml` and `src/agentic_workflows/orchestration/langgraph/graph.py`.
- `fastapi>=0.115` - HTTP API layer in `pyproject.toml`, `src/agentic_workflows/api/app.py`, `src/agentic_workflows/api/routes/run.py`, `src/agentic_workflows/api/routes/health.py`, and `src/agentic_workflows/api/routes/tools.py`.
- `pydantic>=2.12,<3.0` - Request/response/schema models in `pyproject.toml`, `src/agentic_workflows/api/models.py`, and `src/agentic_workflows/schemas.py`.

**Testing:**
- `pytest>=8.0` - Main test runner in `pyproject.toml` and `tests/`.
- `pytest-asyncio>=0.24` - Async test support in `pyproject.toml`, `tests/integration/test_api_service.py`, and `tests/eval/test_eval_harness.py`.
- `httpx-sse>=0.4` - SSE test/dev dependency declared in `pyproject.toml`; `httpx`-based streaming is exercised in `tests/integration/test_api_service.py` and `tests/eval/test_eval_harness.py`.

**Build/Dev:**
- `ruff>=0.11` - Lint/format tool in `pyproject.toml`, `AGENTS.md`, and `.github/workflows/ci.yml`.
- `mypy>=1.10` - Type checking in `pyproject.toml`, `AGENTS.md`, and `.github/workflows/ci.yml`.
- `pre-commit>=4.0` - Local hook runner in `pyproject.toml` and `.pre-commit-config.yaml`.

## Key Dependencies

**Critical:**
- `langgraph>=1.0.6,<2.0` - Core orchestration graph runtime in `src/agentic_workflows/orchestration/langgraph/graph.py`.
- `fastapi>=0.115` - Production service layer in `src/agentic_workflows/api/app.py`.
- `openai>=2.0` - Used for direct OpenAI calls and as the OpenAI-compatible client for Ollama in `src/agentic_workflows/orchestration/langgraph/provider.py` and `src/agentic_workflows/core/llm_provider.py`.
- `groq>=1.0` - Alternate hosted LLM backend in `src/agentic_workflows/orchestration/langgraph/provider.py` and `src/agentic_workflows/core/llm_provider.py`.
- `langchain-anthropic>=0.3.0` - Dependency is present in `pyproject.toml` for the Anthropic/ToolNode path, but no Anthropic provider adapter exists in `src/agentic_workflows/orchestration/langgraph/provider.py`.

**Infrastructure:**
- `anyio>=4.0` - Thread offloading and memory streams for API/SSE flow in `src/agentic_workflows/api/routes/run.py` and `src/agentic_workflows/storage/sqlite.py`.
- `sse-starlette>=3.3` - SSE transport for `POST /run` in `src/agentic_workflows/api/routes/run.py`.
- `httpx>=0.28` - API client and integration-test transport in `src/agentic_workflows/cli/user_run.py`, `tests/integration/test_api_service.py`, and `tests/eval/conftest.py`.
- `structlog>=25.0` - Structured logging in `src/agentic_workflows/api/app.py` and `src/agentic_workflows/logger.py`.
- `langfuse>=3.0` (optional extra) - Observability/tracing in `pyproject.toml` and `src/agentic_workflows/observability.py`.

## Configuration

**Environment:**
- Repo-level `.env` is loaded via `python-dotenv` in `src/agentic_workflows/orchestration/langgraph/provider.py` and `src/agentic_workflows/core/llm_provider.py`; example values live in `.env.example`.
- Key runtime config is env-var driven: `P1_PROVIDER`, `P1_PROVIDER_CHAIN`, `OPENAI_API_KEY`, `GROQ_API_KEY`, `OLLAMA_BASE_URL`, `OPENAI_MODEL`, `GROQ_MODEL`, `OLLAMA_MODEL`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_HOST`, `API_HOST`, `API_PORT`, and `RUN_STORE_DB` in `.env.example`.
- Security guardrails are also env-gated in `.env.example` and `src/agentic_workflows/tools/_security.py` (`P1_TOOL_SANDBOX_ROOT`, `P1_BASH_DENIED_PATTERNS`, `P1_BASH_ALLOWED_COMMANDS`, `P1_HTTP_ALLOWED_DOMAINS`, and size caps).

**Build:**
- `pyproject.toml` - Package metadata, dependencies, build backend, Ruff, pytest, and mypy configuration.
- `.github/workflows/ci.yml` - Quality gate for install, lint, typecheck, and tests.
- `.pre-commit-config.yaml` - Local pre-commit hooks.
- Container/deployment manifests: Not detected.

## Platform Requirements

**Development:**
- Any platform with Python 3.12+ and `pip`; no OS-specific code or container dependency is declared in `pyproject.toml`, `AGENTS.md`, or `README.md`.
- Writable local filesystem is required for SQLite/runtime artifacts in `src/agentic_workflows/storage/sqlite.py`, `src/agentic_workflows/orchestration/langgraph/checkpoint_store.py`, `src/agentic_workflows/orchestration/langgraph/memo_store.py`, and `src/agentic_workflows/cli/user_run.py`.
- Optional local Ollama server at `http://localhost:11434/v1` for local-model development, per `.env.example` and `src/agentic_workflows/orchestration/langgraph/provider.py`.

**Production:**
- Deployment target: self-hosted Python ASGI service via `uvicorn` in `src/agentic_workflows/api/app.py`; no cloud-vendor or container deployment config is checked in.
- Persistence expectation: local SQLite files (`.tmp/run_store.db`, `.tmp/langgraph_checkpoints.db`, `.tmp/memo_store.db`) unless the code is extended with another backend.
- Version requirements: Python 3.12+; no separate runtime manager file (`.python-version`, `runtime.txt`) is detected.

---

*Stack analysis: 2026-03-05*
*Update after major dependency changes*
