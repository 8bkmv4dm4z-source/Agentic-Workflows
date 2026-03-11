# Coding Conventions

**Analysis Date:** 2026-03-12

## Naming Patterns

**Files:**
- `snake_case.py` universally: `action_parser.py`, `mission_auditor.py`, `state_schema.py`
- Test files prefixed `test_`: `test_action_parser.py`, `test_mission_auditor.py`
- Private helpers prefixed with underscore: `_security.py`, `_TOOL_KEYWORD_MAP`, `_approx_equal`
- Module-level logger: `_LOG = get_logger("langgraph.action_parser")` or `LOGGER = get_logger(...)`

**Classes:**
- `PascalCase` throughout: `LangGraphOrchestrator`, `TaskHandoff`, `HandoffResult`, `MemoStoreTests`
- `TypedDict` subclasses named as domain concepts: `RunState`, `AgentMessage`, `ToolRecord`, `MissionReport`, `RunResult`
- `dataclass` for lightweight data containers: `AuditFinding`, `AuditReport`
- Pydantic `BaseModel` for schema-enforced contracts: `ToolAction`, `FinishAction`, `TaskHandoff`, `HandoffResult`
- Tool classes named `{Verb}{Noun}Tool`: `MathStatsTool`, `WriteFileTool`

**Functions:**
- `snake_case` universally
- Private module-level helpers: `_strip_thinking`, `_approx_equal`, `_check_tool_presence`
- Factory functions use `create_` prefix: `create_handoff()`, `create_handoff_result()`
- Builders use `build_` prefix: `build_tool_registry()`, `build_verify_gate_outcome()`
- State factory: `new_run_state()`, `ensure_state_defaults()`

**Constants:**
- `UPPER_SNAKE_CASE`: `SUPPORTED_OPS`, `LOGGER`
- Regex patterns prefixed `_` and suffixed `_RE`: `_THINKING_RE`
- Sentinel/admin prefixes as tuples: `_ADMIN_PREFIXES`

**Variables:**
- `snake_case` universally
- Private module-level state: `_setup_done: bool`, `_strict_mode`

## Code Style

**Formatter:** ruff format (enforced via `make format`)

**Linter:** ruff with rules `E, F, I, UP, B, SIM`
- Line length: 100 characters
- Target Python version: 3.12
- Ignored: `E402` (module docstrings), `E501` (long strings exempted)
- Common suppressions: `# noqa: BLE001` (broad exceptions), `# noqa: PLW0603` (global statements), `# noqa: C901` (complexity on intentionally large methods), `# noqa: ANN001` (missing type annotations on test helpers)

**Type checker:** mypy with `warn_return_any=true`, `ignore_missing_imports=true`
- Several modules in `[[tool.mypy.overrides]]` with `ignore_errors=true` (graph.py, provider.py, context_manager.py, etc.)

## Import Organization

**Order (enforced by ruff `I` rules):**
1. `from __future__ import annotations` — on every source file (86/86 detected)
2. Standard library imports
3. Third-party imports
4. Project-internal imports (`from agentic_workflows...`)

**Module docstrings:**
- Placed after `from __future__ import annotations` on most files
- Format: `"""Short summary.\n\nExpanded explanation if needed."""`

**No barrel files / `__init__.py` re-exports:** Imports go directly to the defining module (e.g., `from agentic_workflows.orchestration.langgraph.handoff import TaskHandoff`)

## Pydantic Schema Contracts

**Strict schemas use `extra="forbid"`:**
```python
class TaskHandoff(BaseModel):
    model_config = ConfigDict(extra="forbid")
```
- `ToolAction`, `FinishAction`, `TaskHandoff`, `HandoffResult` all use `extra="forbid"`
- `ClarifyAction` uses `extra="allow"` for backward compat with optional sub-task fields

**Return types are typed dicts, not bare dicts:**
- `RunResult`, `RunState`, `ToolRecord`, `MissionReport`, `AgentMessage` all use `TypedDict`
- `RunState` list fields use `Annotated[list[T], operator.add]` for LangGraph reducer wiring

## Error Handling

**Error hierarchy** in `src/agentic_workflows/errors.py`:
```
AgentError
  RetryableAgentError
    InvalidJSONError
    SchemaValidationError
    MissingActionError
    UnknownActionError
    ToolExecutionError
    LLMError
  FatalAgentError
    UnknownToolError
```

**Tool error pattern:** Return `{"error": "..."}` dict rather than raising; caller inspects result:
```python
if operation not in SUPPORTED_OPS:
    return {"error": f"unknown operation '{operation}'", "supported_operations": sorted(SUPPORTED_OPS)}
```

**Broad except with `# noqa: BLE001`:** Used in resilience-critical paths (provider retries, lifecycle hooks) where any exception must be caught to maintain graph execution. Not used in business logic.

**`contextlib.suppress(Exception)`:** Used for optional/best-effort operations (e.g., truncating optional Postgres tables).

## Logging

**Framework:** stdlib `logging` (no structlog used in practice despite dependency declared)

**Logger creation:** `get_logger(name)` from `src/agentic_workflows/logger.py`:
```python
_LOG = get_logger("langgraph.action_parser")
LOGGER = get_logger("langgraph.mission_auditor")
```

**Log format:** `"%(asctime)s | %(levelname)s | %(name)s | %(message)s"`

**Dual-logging setup** via `setup_dual_logging()` — writes 4 log files:
- `.tmp/log.txt` — verbose DEBUG+
- `.tmp/admin_log.txt` — filtered operational events by prefix (e.g., `"TOOL EXEC"`, `"MISSION REPORT"`)
- `.tmp/server_logs.txt` — INFO+
- `.tmp/provider_logs.txt` — DEBUG+ from provider/graph/tool loggers

**Log message style:** Prefix-driven uppercase markers for operational events:
```python
logger.info("TOOL EXEC %s args=%s", tool_name, args)
logger.info("MISSION REPORT mission_id=%d result=%s", mission_id, result)
```

## Comments

**When to Comment:**
- Module-level docstrings: always present on most modules
- Section separators with `# ---` dashes and a label (e.g., `# --- Two-number arithmetic ---`)
- Inline `# noqa:` suppressions with the rule code always included
- Bug fix context: `# Bug D: ...`, `# Phase 7.1 stabilization`

**No JSDoc-style argument docs:** Type annotations carry all type information; function docstrings describe behavior only.

## Function Design

**Keyword-only arguments** for factory functions with many optional params:
```python
def create_handoff(*, task_id: str, specialist: Literal[...], mission_id: int, tool_scope=None, ...):
```

**Return tuples for multi-value returns:**
```python
def parse_action_json(raw: str, step: int = 0) -> tuple[dict[str, Any], bool]:
    # Returns (parsed_dict, used_fallback)
```

**Tool `execute()` always returns `dict[str, Any]`** — never raises on bad input; uses `{"error": "..."}` pattern.

**Large orchestration methods** marked with `# noqa: C901` — `_plan_next_action` (~860 lines total in `planner_node.py`) and `_execute_action` in `executor_node.py` are intentionally monolithic.

## Module Design

**Single-responsibility modules:** Each module in `orchestration/langgraph/` has one clear role:
- `action_parser.py` — JSON parsing only
- `mission_auditor.py` — post-run audit only
- `handoff.py` — handoff schema only
- `state_schema.py` — state TypedDict + factory only

**Tool class pattern** (in `src/agentic_workflows/tools/`):
- Subclass `Tool` from `tools/base.py`
- Set `name: str` and `description: str` as class variables
- Set `_args_schema: dict[str, dict[str, str]]` as class variable for typed schema
- Implement `execute(self, args: dict[str, Any]) -> dict[str, Any]`

**Imports inside functions** with `# noqa: PLC0415` used sparingly for circular-import avoidance in large orchestration modules.

---

*Convention analysis: 2026-03-12*
