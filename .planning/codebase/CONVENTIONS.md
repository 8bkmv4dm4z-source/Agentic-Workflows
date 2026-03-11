# Coding Conventions

**Analysis Date:** 2026-03-12

## Naming Patterns

**Files:**
- Snake_case for all Python modules: `sort_array.py`, `mission_parser.py`, `planner_node.py`
- Prefixed private modules with underscore: `_security.py`, `_args_schema`
- Tool implementations named after the tool: `sort_array.py` → class `SortArrayTool`

**Classes:**
- PascalCase throughout: `LangGraphOrchestrator`, `SortArrayTool`, `WriteFileTool`, `TaskHandoff`
- Tool classes suffixed with `Tool`: `SortArrayTool`, `WriteFileTool`, `MemoizeTool`
- Mixin classes suffixed with `Mixin`: `PlannerNodeMixin`, `ExecutorNodeMixin`, `LifecycleNodesMixin`
- TypedDict classes named as plain nouns: `RunState`, `ToolRecord`, `MissionReport`, `AgentMessage`
- Pydantic models named as nouns: `ToolAction`, `FinishAction`, `TaskHandoff`, `HandoffResult`
- Error classes suffixed with `Error`: `AgentError`, `ToolExecutionError`, `ProviderTimeoutError`

**Functions and Methods:**
- Snake_case: `parse_missions()`, `build_tool_registry()`, `get_logger()`
- Private helpers prefixed with underscore: `_check_shebang_guard()`, `_classify_intent()`, `_extract_missions_regex_fallback()`
- Module-level private helpers with single underscore: `_build_test_app()`, `_parse_sse_events()`
- Node methods prefixed with their graph role: `_plan_next_action()`, `_execute_action()`, `_route_to_specialist()`

**Variables:**
- Snake_case: `tool_name`, `mission_id`, `pending_action_queue`
- Module-level constants are UPPER_SNAKE_CASE: `_PIPELINE_TRACE_CAP`, `_HANDOFF_QUEUE_CAP`, `_ANNOTATED_LIST_FIELDS`, `_ADMIN_PREFIXES`
- Private module-level singletons prefixed with underscore: `_spacy_nlp`, `_setup_done`
- State dict keys use snake_case strings: `"tool_history"`, `"pending_action_queue"`, `"policy_flags"`

**Types:**
- Use `X | None` union syntax (not `Optional[X]`): `tool_scope: list[str] | None = None`
- Use `from __future__ import annotations` in all source and test files (86/80 files respectively)
- Use `Literal["success", "error", "timeout"]` for constrained string fields
- Use `NotRequired[T]` for optional TypedDict fields: `via_subgraph: NotRequired[bool]`

## Code Style

**Formatting:**
- Tool: `ruff format` (configured in `pyproject.toml`)
- Line length: 100 characters
- Target: Python 3.12

**Linting:**
- Tool: `ruff check` with rules `E`, `F`, `I`, `UP`, `B`, `SIM`
- Ignores: `E402` (module-level imports after code), `E501` (long lines — legacy strings exempt)
- Common inline suppressions: `# noqa: BLE001` (broad exception catches), `# noqa: C901` (complex methods), `# noqa: PLC0415` (inline imports in mixin methods), `# type: ignore[attr-defined]` (mixin self-references)
- `mypy` configured with `ignore_missing_imports = true`; several large modules are excluded via `[[tool.mypy.overrides]]` with `ignore_errors = true`

## Import Organization

**Order (enforced by ruff `I` rules):**
1. `from __future__ import annotations` (always first when present)
2. Standard library imports
3. Third-party imports
4. Local package imports (`from agentic_workflows.*`)

**Path Aliases:**
- None configured. All imports use full package paths: `from agentic_workflows.orchestration.langgraph.state_schema import RunState`

**Inline Imports:**
- Used inside mixin method bodies to avoid circular imports: `from agentic_workflows.orchestration.langgraph.orchestrator import ...  # noqa: PLC0415`
- `TYPE_CHECKING` guards used for type-only imports to avoid circular dependencies: `if TYPE_CHECKING: from agentic_workflows.storage.artifact_store import ArtifactStore`

**Re-export Pattern:**
- `graph.py` is a backward-compatibility shim that re-exports everything from `orchestrator.py` via explicit `__all__`

## Data Modeling

**Schema enforcement pattern:**
- Pydantic `BaseModel` with `ConfigDict(extra="forbid")` for all inter-agent contracts: `ToolAction`, `FinishAction`, `TaskHandoff`, `HandoffResult`
- `ConfigDict(extra="allow")` used only for `ClarifyAction` (allows sub-task fields)
- Factory functions with keyword-only arguments (`*` separator) for Pydantic model construction:
  ```python
  def create_handoff(*, task_id: str, specialist: Literal[...], mission_id: int, token_budget: int = 4096) -> TaskHandoff:
  ```

**State containers:**
- `TypedDict` for graph state: `RunState`, `ToolRecord`, `MissionReport`, `AgentMessage`
- `@dataclass` for auditor findings and internal structures: used in `mission_auditor.py`, `reviewer.py`, `directives.py`
- `@dataclass(frozen=True, slots=True)` for immutable configuration records: `DirectiveConfig` in `directives.py`, `ReviewResult` in `reviewer.py`

## Error Handling

**Hierarchy (`src/agentic_workflows/errors.py`):**
- Base: `AgentError(Exception)`
  - `RetryableAgentError` — errors that allow retry: `InvalidJSONError`, `SchemaValidationError`, `MissingActionError`, `UnknownActionError`, `ToolExecutionError`, `LLMError`
  - `FatalAgentError` — errors that stop execution: `UnknownToolError`
- Provider-level: `ProviderTimeoutError(RuntimeError)` in `provider.py`
- Orchestrator-level: `MemoizationPolicyViolation(RuntimeError)` in `orchestrator.py`

**Patterns:**
- Tool `execute()` methods return error dicts rather than raising: `return {"error": "items must be a list"}`
- Provider and parser code raises exceptions which the orchestrator catches and handles
- Broad `except Exception` catches are annotated with `# noqa: BLE001` for conscious decisions
- `contextlib.suppress(Exception)` used for truly optional operations (e.g., Postgres table truncation)
- Error responses from tools always use the key `"error"`: `{"error": "path is required"}`

## Logging

**Framework:** Standard library `logging` via custom wrapper `src/agentic_workflows/logger.py`

**Logger access:**
```python
from agentic_workflows.logger import get_logger
logger = get_logger("component_name")
```

**Log format:** `%(asctime)s | %(levelname)s | %(name)s | %(message)s`

**Structured log message pattern:**
```python
self.logger.info(
    "PLANNER STEP START step=%s run_id=%s queue=%s timeout_mode=%s",
    state["step"], state["run_id"], queue_len, bool(timeout_mode)
)
```

**Admin log prefixes:** Operational log messages begin with ALL_CAPS prefixes defined in `_ADMIN_PREFIXES` (e.g., `TOOL EXEC`, `CONTEXT INJECT`, `MISSION REPORT`). Messages with these prefixes are routed to `admin_log.txt`.

**Dual logging:** `setup_dual_logging()` in `logger.py` wires four file handlers: `log.txt` (verbose), `admin_log.txt` (filtered), `server_logs.txt` (INFO+), `provider_logs.txt` (DEBUG+).

## Comments

**When to Comment:**
- Module-level docstrings explain the module's purpose and key abstractions
- Class docstrings explain role within the system
- Method docstrings on public/complex methods; private helpers often have no docstring
- Inline comments explain non-obvious decisions (security rationale, circular import workarounds)

**Section separators:**
```python
# ---------------------------------------------------------------------------
# Section Name
# ---------------------------------------------------------------------------
```

**Anti-pattern annotations:**
- `# Anti-pattern:` comments in module docstrings warn future contributors of dangerous patterns (e.g., circular import risks in mixin modules)

**Suppression comments:**
- Always explain suppressed rules: `# noqa: BLE001` (broad exception), `# type: ignore[attr-defined]` (mixin self-reference)

## Function Design

**Size:** Large orchestrator methods are tolerated with explicit suppression: `def _execute_action(self, state: RunState) -> RunState:  # noqa: C901  # method is intentionally large`

**Parameters:**
- Factory functions and constructors with multiple optional parameters use keyword-only arguments (`*` separator)
- Tool `execute()` always takes `args: dict[str, Any]` and returns `dict[str, Any]`
- Default values for `None` mutable args use `or {}` / `or []` pattern: `tool_scope=tool_scope or []`

**Return Values:**
- Tool methods return `dict[str, Any]` always — errors are returned as `{"error": "..."}` dicts
- State-mutating graph node methods accept and return `RunState`

## Module Design

**Exports:**
- `graph.py` uses explicit `__all__` for re-export shim
- Most modules do not define `__all__`; public API is implicit

**Barrel Files:**
- Not used for general modules
- `graph.py` acts as a backward-compatibility barrel for the orchestrator subsystem

**Package layout:**
- `src/` layout with `setuptools.packages.find(where=["src"])`
- Each subdirectory has an `__init__.py`

---

*Convention analysis: 2026-03-12*
