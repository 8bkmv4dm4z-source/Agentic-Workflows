# Coding Conventions

**Analysis Date:** 2026-03-05

## Naming Patterns

**Files:**
- Python modules use `snake_case.py` across `src/agentic_workflows/`, for example `src/agentic_workflows/orchestration/langgraph/state_schema.py` and `src/agentic_workflows/tools/search_files.py`.
- Test files use `test_<subject>.py` under `tests/unit/`, `tests/integration/`, and `tests/eval/`, for example `tests/unit/test_run_store.py` and `tests/integration/test_api_service.py`.
- Package markers use `__init__.py`; documentation files are mixed `README.md` plus topic-specific markdown such as `src/agentic_workflows/directives/phase1_langgraph.md`.

**Functions:**
- Functions and methods use `snake_case`, including async functions such as `lifespan()` in `src/agentic_workflows/api/app.py` and `validation_error_handler()` in `src/agentic_workflows/api/app.py`.
- Async functions do not use a special prefix; `async def` is the only async marker.
- Internal helpers commonly use a leading underscore, for example `_resolve_ollama_base_url()` in `src/agentic_workflows/orchestration/langgraph/provider.py`, `_build_eval_app()` in `tests/eval/conftest.py`, and `_search_glob()` in `src/agentic_workflows/tools/search_files.py`.

**Variables:**
- Variables and attributes use `snake_case`, for example `retry_backoff_seconds` in `src/agentic_workflows/orchestration/langgraph/provider.py`.
- Constants use `UPPER_SNAKE_CASE`, for example `DEFAULT_PROVIDER_TIMEOUT_SECONDS` in `src/agentic_workflows/orchestration/langgraph/provider.py`.
- Module-private globals often combine leading underscore plus constant casing or snake case, for example `_ADMIN_PREFIXES` and `_setup_done` in `src/agentic_workflows/logger.py`.

**Types:**
- Classes, `BaseModel`s, `TypedDict`s, `Protocol`s, and exception types use `PascalCase`, for example `RunRequest` in `src/agentic_workflows/api/models.py`, `RunState` in `src/agentic_workflows/orchestration/langgraph/state_schema.py`, `RunStore` in `src/agentic_workflows/storage/protocol.py`, and `ProviderTimeoutError` in `src/agentic_workflows/orchestration/langgraph/provider.py`.
- No `I` prefix pattern was detected for interfaces/protocols.
- Literal enum-like values are lowercase strings such as `"pending"`, `"completed"`, `"tool"`, and `"finish"` in `src/agentic_workflows/api/models.py` and `src/agentic_workflows/schemas.py`.

## Code Style

**Formatting:**
- `ruff format` is the formatter, configured in `pyproject.toml`.
- Line length is `100` via `[tool.ruff]` in `pyproject.toml`.
- Quote style is mixed in current code, but formatter-driven files trend toward Ruff defaults; do not hand-enforce a custom quote style beyond `ruff format`.
- Semicolons are not applicable in Python code.
- Indentation is 4 spaces throughout sampled files such as `src/agentic_workflows/api/app.py` and `src/agentic_workflows/tools/write_file.py`.
- Python 3.12 syntax is standard: built-in generics (`list[str]`), union operators (`str | None`), and `from __future__ import annotations` are common in newer modules such as `src/agentic_workflows/api/models.py`.

**Linting:**
- `ruff check src/ tests/` is the primary lint command from `AGENTS.md`.
- Active Ruff rule groups in `pyproject.toml` are `E`, `F`, `I`, `UP`, `B`, and `SIM`.
- `E402` and `E501` are ignored in `pyproject.toml` to accommodate legacy import/docstring placement and long strings.
- `mypy src/` is also part of the standard quality pass in `AGENTS.md`.

## Import Organization

**Order:**
1. `from __future__ import annotations` when used, often before the module docstring in newer files such as `src/agentic_workflows/api/app.py`.
2. Standard library imports.
3. Third-party imports.
4. Local imports, usually absolute package imports such as `from agentic_workflows.api.models import ErrorResponse`.
5. Sibling relative imports are used inside packages when convenient, for example `from .base import Tool` in `src/agentic_workflows/tools/search_files.py`.

**Grouping:**
- Blank lines separate import groups in sampled files such as `src/agentic_workflows/orchestration/langgraph/provider.py` and `tests/eval/conftest.py`.
- Import sorting is consistent with Ruff/isort behavior.
- Dedicated type-only import groups were not detected; typing symbols are usually imported inline with other imports.

**Path Aliases:**
- Not applicable. No Python import alias system comparable to TS path aliases was detected.

## Error Handling

**Patterns:**
- Tool implementations usually return structured error dictionaries for expected input, path, or guardrail failures, for example `{"error": "path is required"}` in `src/agentic_workflows/tools/write_file.py` and `src/agentic_workflows/tools/search_files.py`.
- API boundaries convert exceptions into structured `ErrorResponse` payloads, for example the `422` and `500` handlers in `src/agentic_workflows/api/app.py`.
- Custom exception hierarchies are used for orchestration/provider failures, centered on `AgentError` in `src/agentic_workflows/errors.py` and `ProviderTimeoutError` in `src/agentic_workflows/orchestration/langgraph/provider.py`.
- Bare `except` was not detected. Some integration boundaries intentionally use `except Exception as exc  # noqa: BLE001` for graceful degradation, for example in `src/agentic_workflows/orchestration/langgraph/provider.py`, `src/agentic_workflows/observability.py`, and `src/agentic_workflows/orchestration/langgraph/graph.py`.

**Error Types:**
- Invalid request shapes are enforced with Pydantic `ValidationError` via models in `src/agentic_workflows/api/models.py`.
- Provider/runtime failures are raised as exceptions and usually logged near the boundary.
- Expected recoverable failures in tool code return data instead of raising, which keeps the planner/tool contract deterministic.

## Logging

**Framework:**
- Two logging styles are active.
- Standard library logging is wrapped by `get_logger()` and `setup_dual_logging()` in `src/agentic_workflows/logger.py`.
- `structlog` is used in the API layer, for example `src/agentic_workflows/api/app.py`, `src/agentic_workflows/api/routes/run.py`, and `src/agentic_workflows/api/routes/runs.py`.
- Active levels include `debug`, `info`, `warning`, and `error`.

**Patterns:**
- API logs use structured event names plus keyword context, for example `log.info("api.startup", status="graph_compiled", tools=tool_count)` in `src/agentic_workflows/api/app.py`.
- Orchestration logs use high-signal text prefixes such as `RUN START`, `TOOL EXEC`, and `MISSION STATUS`, filtered by `AdminFilter` in `src/agentic_workflows/logger.py`.
- Logging is concentrated at service boundaries, graph transitions, tool execution, and failure handling rather than in pure helper logic.
- CLI and interactive flows use terminal output directly with `print()` or `console.print()` in `src/agentic_workflows/core/main.py`, `src/agentic_workflows/cli/user_run.py`, and `src/agentic_workflows/orchestration/langgraph/run.py`.

## Comments

**When to Comment:**
- Module docstrings are common for purpose and context, for example `src/agentic_workflows/api/app.py`, `src/agentic_workflows/observability.py`, and `tests/integration/test_api_service.py`.
- Inline comments explain why a guardrail or architectural choice exists, for example shell-script guardrails in `src/agentic_workflows/tools/write_file.py` and middleware ordering in `src/agentic_workflows/api/app.py`.
- Section-divider comments such as `# ----- Routes -----` and `# ---------------------------------------------------------------------------` are common in both source and tests.
- Obvious line-by-line comments are uncommon outside legacy or instructional test files.

**JSDoc/TSDoc:**
- Not applicable.
- Python docstrings are the documentation pattern for modules, classes, and many public functions.

**TODO Comments:**
- `TODO` and `FIXME` comments were not detected in `src/` or `tests/` via repository search on 2026-03-05.

## Function Design

**Size:**
- Small focused helpers are common in the tool layer, for example `_stat_entry()` in `src/agentic_workflows/tools/search_files.py`.
- Large orchestration methods also exist where state-machine coordination is intentionally centralized, especially in `src/agentic_workflows/orchestration/langgraph/graph.py`.
- Guard clauses and early returns are common in tool `execute()` methods and API handlers.

**Parameters:**
- Public APIs are usually typed.
- Tool interfaces standardize on `execute(self, args: dict[str, Any])`.
- Keyword-only arguments are used selectively for clarity, for example `save_run(self, run_id: str, *, status: str, **fields: Any)` in `src/agentic_workflows/storage/protocol.py`.

**Return Values:**
- Explicit returns are standard.
- Tools return structured dictionaries for both success and failure.
- Cross-module contracts use `BaseModel`, `TypedDict`, or `Protocol` rather than untyped tuples, for example `RunRequest` in `src/agentic_workflows/api/models.py` and `RunResult` in `src/agentic_workflows/orchestration/langgraph/state_schema.py`.

## Module Design

**Exports:**
- Named exports are the norm for Python modules.
- Compatibility or façade modules sometimes use explicit `__all__`, for example `src/agentic_workflows/orchestration/langgraph/langgraph_orchestrator.py` and `src/agentic_workflows/api/middleware/__init__.py`.
- Default exports are not applicable in Python.

**Barrel Files:**
- Minimal `__init__.py` files are used; many are empty markers such as `src/agentic_workflows/api/routes/__init__.py` and `src/agentic_workflows/cli/__init__.py`.
- Selective re-export barrels exist, but broad barrel-file usage is limited.
- Cross-layer import boundaries are documented in `AGENTS.md` and generally reflected in package layout: `src/agentic_workflows/directives/`, `src/agentic_workflows/orchestration/`, and `src/agentic_workflows/tools/`.

*Convention analysis: 2026-03-05*
*Update when patterns change*
