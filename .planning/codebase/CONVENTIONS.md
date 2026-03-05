# Coding Conventions

**Analysis Date:** 2026-03-05

## Naming Patterns

**Files:**
- Python modules use snake_case filenames under `src/agentic_workflows/` (`src/agentic_workflows/tools/write_file.py`, `src/agentic_workflows/orchestration/langgraph/state_schema.py`, `src/agentic_workflows/api/routes/run.py`).
- Test files use `test_*.py` under dedicated test trees, not alongside source (`tests/unit/test_run_store.py`, `tests/integration/test_api_service.py`, `tests/eval/test_eval_harness.py`).
- Package entrypoints use `__init__.py`; public/runtime entry scripts are descriptive snake_case files such as `src/agentic_workflows/cli/user_run.py` and `src/agentic_workflows/orchestration/langgraph/run.py`.

**Functions:**
- Functions and methods use snake_case (`setup_dual_logging`, `validate_path_within_sandbox`, `post_run`, `get_run_stream`).
- Internal helpers use a leading underscore (`_build_test_app`, `_env_float`, `_safe_serialize`, `_parse_missions_inner`).
- Async functions keep the same snake_case style; there is no `async_` prefix convention (`src/agentic_workflows/api/app.py`, `src/agentic_workflows/api/routes/run.py`, `src/agentic_workflows/storage/sqlite.py`).
- Route handlers are verb/resource oriented (`health`, `list_tools`, `post_run`, `get_run` in `src/agentic_workflows/api/routes/`).

**Variables:**
- Local variables and instance attributes use snake_case (`run_store`, `tool_count`, `retry_counts`, `target_path`).
- Constants use UPPER_SNAKE_CASE, often with a module-private underscore when internal (`_DEFAULT_DB_PATH`, `_CREATE_TABLE`, `_ADMIN_PREFIXES`, `DEFAULT_PROVIDER_TIMEOUT_SECONDS`).
- Internal state flags and caches also use underscore-prefixed names (`_setup_done`, `_langfuse_client`, `_TOOLNODE_AVAILABLE`).

**Types:**
- Classes, Pydantic models, TypedDicts, Protocols, and dataclasses use PascalCase (`RunRequest`, `RunStore`, `RunState`, `LangGraphOrchestrator`, `MemoizationPolicy`).
- Tool implementations consistently use a `Tool` suffix (`WriteFileTool`, `ParseCodeStructureTool`, `HttpRequestTool`).
- Storage and provider abstractions use `*Store`, `*Provider`, and `*Policy` naming (`SQLiteRunStore`, `SQLiteCheckpointStore`, `ChatProvider`, `MemoizationPolicy`).
- Python `Enum` usage: Not detected.

## Code Style

**Formatting:**
- `ruff` is the active formatter/linter, configured in `pyproject.toml`; pre-commit runs `ruff --fix` and `ruff-format` from `.pre-commit-config.yaml`.
- Maximum line length is 100 in `pyproject.toml`.
- Indentation is 4 spaces, and type hints are pervasive across public APIs and many internals (`src/agentic_workflows/api/models.py`, `src/agentic_workflows/storage/protocol.py`, `src/agentic_workflows/orchestration/langgraph/state_schema.py`).
- `from __future__ import annotations` is common in newer modules and tests (`src/agentic_workflows/api/app.py`, `src/agentic_workflows/orchestration/langgraph/provider.py`, `tests/conftest.py`), but not universal in older files such as `src/agentic_workflows/logger.py` and `src/agentic_workflows/tools/write_file.py`.
- Triple-double-quoted module/class/function docstrings are the default documentation style; double-quoted string literals dominate in newer formatted files.
- Semicolons: Not applicable.

**Linting:**
- `ruff` is configured with `E`, `F`, `I`, `UP`, `B`, and `SIM` rule families in `pyproject.toml`.
- `E402` and `E501` are explicitly ignored in `pyproject.toml`.
- Run commands match `AGENTS.md`: `ruff check src/ tests/`, `ruff format src/ tests/`, and `mypy src/`.

## Import Organization

**Order:**
1. `from __future__ import annotations` first when present (`src/agentic_workflows/api/app.py`, `tests/conftest.py`).
2. Standard-library imports (`os`, `json`, `sqlite3`, `pathlib`, `typing`).
3. Third-party imports (`fastapi`, `httpx`, `pytest`, `pydantic`, `structlog`).
4. Local absolute package imports (`from agentic_workflows...`).
5. Package-local relative imports inside leaf packages (`from .base import Tool`, `from ._security import ...`).

**Grouping:**
- Imports are separated by blank lines between groups in representative files such as `src/agentic_workflows/api/app.py`, `src/agentic_workflows/storage/sqlite.py`, and `tests/eval/conftest.py`.
- Sorting is largely delegated to Ruff/isort (`I` rules), so imports are generally normalized rather than hand-styled.
- Type-only import syntax (`from typing import TYPE_CHECKING` style splits): Not detected as a dominant pattern.

**Path Aliases:**
- Import path aliases: Not detected.
- The codebase relies on the real package root `agentic_workflows` plus local relative imports inside package folders.

## Error Handling

**Patterns:**
- Deterministic tools usually return structured error dictionaries for expected operational failures instead of raising (`src/agentic_workflows/tools/write_file.py`, `src/agentic_workflows/tools/read_file.py`, `src/agentic_workflows/tools/_security.py`).
- Runtime and orchestration layers define explicit exception classes for control flow and retry semantics (`src/agentic_workflows/errors.py`, `src/agentic_workflows/orchestration/langgraph/provider.py`).
- API boundaries convert failures into structured JSON envelopes (`src/agentic_workflows/api/app.py`, `src/agentic_workflows/api/models.py`, `src/agentic_workflows/api/routes/run.py`).
- Guard clauses are common: validate inputs early, return/raise immediately, then continue with the happy path (`src/agentic_workflows/tools/write_file.py`, `src/agentic_workflows/storage/sqlite.py`).

**Error Types:**
- Common concrete exception types include `OSError`, `ValueError`, `ValidationError`, and `ProviderTimeoutError`.
- Expected lookup misses commonly return `None` or an error/result dict instead of exceptions (`src/agentic_workflows/storage/sqlite.py`, `src/agentic_workflows/tools/search_files.py`).
- Broad `except Exception` blocks do exist at containment boundaries for graceful degradation and telemetry (`src/agentic_workflows/observability.py`, `src/agentic_workflows/api/routes/run.py`, `src/agentic_workflows/orchestration/langgraph/graph.py`), so the current codebase standard is "no bare except", not "no broad catch".
- Logging before/while handling failures is common at service and orchestration boundaries.

## Logging

**Framework:**
- Two logging styles are active: stdlib `logging` via `src/agentic_workflows/logger.py` and `structlog` in the FastAPI surface (`src/agentic_workflows/api/app.py`, `src/agentic_workflows/api/routes/run.py`).
- Stdio/file logger format is `%(asctime)s | %(levelname)s | %(name)s | %(message)s` in `src/agentic_workflows/logger.py`.
- Common levels are `info`, `warning`, and `error`; `debug` appears mainly in tests and verbose file logging.

**Patterns:**
- API logging uses event-name strings with key/value context, for example `log.info("api.startup", status="graph_compiled", tools=tool_count)` in `src/agentic_workflows/api/app.py`.
- Orchestration logging uses high-signal status prefixes such as `RUN START`, `TOOL EXEC`, `TOOL RESULT`, and `AUDIT REPORT` defined in `src/agentic_workflows/logger.py` and emitted heavily from `src/agentic_workflows/orchestration/langgraph/graph.py`.
- Logging is concentrated at lifecycle boundaries, tool execution, mission tracking, memo/checkpoint persistence, and API error handling rather than small pure helpers.
- `console.log`-style ad hoc printing outside CLI/report code: Not detected.

## Comments

**When to Comment:**
- Most modules and many tests start with a docstring that explains purpose and operating constraints (`src/agentic_workflows/api/app.py`, `src/agentic_workflows/storage/protocol.py`, `tests/integration/test_api_service.py`).
- Inline comments are used to explain why a workaround exists, not to narrate simple assignments; examples include the reducer explanation in `src/agentic_workflows/orchestration/langgraph/graph.py` and the ASGI lifespan note in `tests/integration/test_api_service.py`.
- Section-divider comments with dashed rulers are common in larger files and tests (`src/agentic_workflows/storage/sqlite.py`, `tests/eval/conftest.py`, `tests/unit/test_tool_security.py`).

**Docstrings:**
- Python docstrings are the standard API documentation mechanism; JSDoc/TSDoc is not applicable.
- Public models, fixtures, helper builders, and many tests carry short explanatory docstrings (`src/agentic_workflows/api/models.py`, `tests/conftest.py`, `tests/unit/test_logger.py`).

**TODO Comments:**
- TODO/FIXME/XXX comments in current `src/` and `tests/`: Not detected.
- `# pragma: no cover` and `# noqa` annotations are used sparingly for optional dependency paths, broad exception boundaries, and typing edge cases (`src/agentic_workflows/orchestration/langgraph/provider.py`, `src/agentic_workflows/orchestration/langgraph/graph.py`).

## Function Design

**Size:**
- Tool `execute()` methods and storage helpers are usually short and guard-clause driven (`src/agentic_workflows/tools/write_file.py`, `src/agentic_workflows/storage/sqlite.py`).
- High-complexity orchestration modules intentionally keep larger coordinator methods in place (`src/agentic_workflows/orchestration/langgraph/graph.py`, `src/agentic_workflows/orchestration/langgraph/run.py`); there is no strict "small functions only" rule in live code.

**Parameters:**
- Type annotations are expected on public call sites and common on internals.
- Config-heavy APIs prefer keyword-only parameters or structured payloads, for example `LangGraphOrchestrator.__init__(..., provider=..., memo_store=...)` and `SQLiteRunStore.save_run(run_id, *, status, **fields)`.
- Dynamic tool/runtime boundaries often accept `dict[str, Any]` payloads (`src/agentic_workflows/tools/base.py`, `src/agentic_workflows/api/sse.py`, `src/agentic_workflows/orchestration/langgraph/state_schema.py`).

**Return Values:**
- Functions return explicit dicts, TypedDicts, Pydantic models, or `None`; implicit fallthrough behavior is uncommon.
- Early returns are preferred for validation failures and empty cases.

## Module Design

**Exports:**
- Public package surfaces are selectively re-exported via `__init__.py` modules, with `__all__` used where the package wants a narrow runtime surface (`src/agentic_workflows/orchestration/langgraph/__init__.py`).
- Most modules are still imported directly by full package path rather than only through package barrels.

**Barrel Files:**
- Python package `__init__.py` files act as limited barrel files (`src/agentic_workflows/orchestration/langgraph/__init__.py`, `src/agentic_workflows/api/routes/__init__.py`).
- Dedicated barrel-only directories or alias-based export layers: Not detected.
- Architecture boundaries are enforced primarily by folder separation and repo rules in `AGENTS.md` (`core/`, `orchestration/`, `tools/`, `api/`, `storage/`), not by a heavy export facade pattern.

*Convention analysis: 2026-03-05*
*Update when patterns change*
