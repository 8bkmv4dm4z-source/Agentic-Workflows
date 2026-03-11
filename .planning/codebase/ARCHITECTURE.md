# Architecture

**Analysis Date:** 2026-03-12

## Pattern Overview

**Overall:** Plan-and-Execute Multi-Agent Orchestration with LangGraph StateGraph

**Key Characteristics:**
- LangGraph `StateGraph` compiles a deterministic node graph; all state flows through a typed `RunState` TypedDict
- Four-mixin composition pattern: `LangGraphOrchestrator` inherits from `PlannerHelpersMixin`, `PlannerNodeMixin`, `ExecutorNodeMixin`, and `LifecycleNodesMixin`
- Provider-agnostic: a `ChatProvider` Protocol decouples the planning model (OpenAI, Groq, Ollama, LlamaCpp, Anthropic) from the orchestration engine
- Tools are deterministic (no LLM calls); tool execution is side-effect-only
- Two execution paths: standard `plan→execute→policy→plan` loop, and an Anthropic-native `plan→tools→plan` ReAct loop via `ToolNode`
- Post-run auditor validates correctness deterministically, no LLM calls

## Layers

**Schemas and Errors (`src/agentic_workflows/`):**
- Purpose: Cross-cutting contracts and exception hierarchy
- Location: `src/agentic_workflows/schemas.py`, `src/agentic_workflows/errors.py`
- Contains: `ToolAction`, `FinishAction`, `ClarifyAction` (Pydantic BaseModel); `AgentError`, `RetryableAgentError`, `FatalAgentError` hierarchy
- Depends on: Pydantic only
- Used by: orchestration layer, action parser, all tool execution paths

**Tools Layer (`src/agentic_workflows/tools/`):**
- Purpose: 40+ deterministic tool implementations; no LLM calls
- Location: `src/agentic_workflows/tools/`
- Contains: Individual tool classes inheriting `Tool` base; `base.py` defines `Tool.execute(args) -> dict`; `tools_registry.py` builds the `dict[str, Tool]` registry at orchestrator init
- Depends on: Standard library, `base.py`, SQLite memo/checkpoint stores
- Used by: Executor node (`executor_node.py`), executor subgraph (`specialist_executor.py`)

**Storage Layer (`src/agentic_workflows/storage/`):**
- Purpose: Persistence backends (SQLite dev, Postgres prod)
- Location: `src/agentic_workflows/storage/`
- Contains: `SQLiteRunStore`, `PostgresRunStore` (run persistence), `artifact_store.py`, `mission_context_store.py`, `tool_result_cache.py`, `memory_consolidation.py`; protocols in `checkpoint_protocol.py`, `memo_protocol.py`
- Depends on: `sqlite3`, `psycopg` / `psycopg_pool`, `anyio`
- Used by: Orchestration layer, API layer

**Orchestration Core (`src/agentic_workflows/orchestration/langgraph/`):**
- Purpose: LangGraph graph, state management, planning, execution, auditing
- Location: `src/agentic_workflows/orchestration/langgraph/`
- Contains: `orchestrator.py` (spine), four mixin modules, `state_schema.py`, `provider.py`, `context_manager.py`, `mission_parser.py`, `mission_auditor.py`, `model_router.py`, `action_parser.py`, `handoff.py`, `checkpoint_store.py`, `memo_store.py`, `policy.py`, `reviewer.py`, and more
- Depends on: LangGraph, tools layer, storage layer, schemas, providers
- Used by: API layer, CLI entry points

**API Layer (`src/agentic_workflows/api/`):**
- Purpose: FastAPI HTTP interface; compiles graph at startup via `lifespan`
- Location: `src/agentic_workflows/api/`
- Contains: `app.py` (FastAPI app, lifespan), routes (`health.py`, `run.py`, `runs.py`, `tools.py`), `middleware/` (API key, request ID), `models.py`, `sse.py`, `stream_token.py`
- Depends on: Orchestration core, storage layer
- Used by: External HTTP clients

**CLI Layer (`src/agentic_workflows/cli/`, `run.py`, `run_audit.py`, `user_run.py`):**
- Purpose: Command-line entrypoints for demos, audits, and user-driven runs
- Location: `src/agentic_workflows/orchestration/langgraph/run.py`, `run_audit.py`, `user_run.py`; `src/agentic_workflows/cli/user_run.py`
- Contains: Argument parsing, audit panel rendering, structured output
- Depends on: Orchestration core, `run_ui.py` for Rich-style panels

**Observability (`src/agentic_workflows/observability.py` or module):**
- Purpose: Langfuse tracing, span decorators, schema compliance reporting
- Location: `src/agentic_workflows/` (imported as `agentic_workflows.observability`)
- Contains: `observe` decorator, `get_langfuse_callback_handler`, `report_schema_compliance`, `flush`
- Depends on: Langfuse SDK (optional; degrades gracefully)
- Used by: Planner node, provider adapters, run entrypoints

**Legacy Core (`src/agentic_workflows/core/`):**
- Purpose: Phase 0 baseline single-agent orchestrator (reference implementation)
- Location: `src/agentic_workflows/core/`
- Contains: `Orchestrator`, `agent_state.py`, `llm_provider.py`, `main.py`
- Depends on: Minimal (no LangGraph)
- Used by: Not used in production; preserved for regression reference

## Data Flow

**Standard Execution Loop:**

1. `run.py` or API `POST /run` calls `LangGraphOrchestrator.run(user_input)`
2. `prepare_state()` calls `new_run_state()` + `parse_missions()` to parse user input into a `StructuredPlan`; initial checkpoint saved
3. LangGraph compiled graph enters `plan` node → `_plan_next_action()` called
4. Planner calls `ChatProvider.generate(messages)` with JSON schema constraint; response parsed by `action_parser.validate_action()`
5. `_route_after_plan()` conditional edge decides: `execute`, `plan` (retry/queue pop), `finish`, or `clarify`
6. `execute` node → `_route_to_specialist()` → `_execute_action()` dispatches to `Tool.execute(args)` from registry
7. `policy` node → `_enforce_memo_policy()` checks if result requires memoization; injects system message if so
8. Loop back to `plan`; repeat until `pending_action.action == "finish"` or step budget exceeded
9. `finalize` node → `_finalize()` runs `audit_run()`, saves checkpoint, writes `Shared_plan.md`, closes provider

**Anthropic ToolNode Path:**

1. Same as above through step 3
2. `_plan_next_action()` returns Anthropic tool-call messages in LangChain format
3. `tools_condition` routes to `tools` node (LangChain `ToolNode` with dedup wrapper)
4. `tools` node executes tool, appends result to messages, returns to `plan`

**Mission Tracking:**

- `ContextManager.compact(state)` runs before every planner call; evicts old messages, injects cross-mission summaries for new missions
- `mission_tracker` module updates `mission_reports` after each tool execution
- `MissionReport` per mission: tracks `used_tools`, `tool_results`, `status`, `written_files`, `required_tools`

**State Management:**
- `RunState` TypedDict flows through every node; fields with `Annotated[list, operator.add]` use LangGraph reducers for parallel Send() compatibility
- `_sequential_node()` wrapper zeros out those fields in returned dicts to prevent doubling
- `ensure_state_defaults()` repairs missing keys before every node runs (defensive hardening)

## Key Abstractions

**`ChatProvider` Protocol:**
- Purpose: Vendor-agnostic LLM interface
- Location: `src/agentic_workflows/orchestration/langgraph/provider.py`
- Pattern: `generate(messages, response_schema=None) -> str` and `context_size() -> int`; implementations: `OllamaChatProvider`, `OpenAIChatProvider`, `GroqChatProvider`, `LlamaCppChatProvider`, `AnthropicChatProvider`

**`Tool` Base Class:**
- Purpose: Uniform tool contract
- Location: `src/agentic_workflows/tools/base.py`
- Pattern: `execute(args: dict) -> dict`; `args_schema` property; subclasses set `name`, `description`, `_args_schema`

**`RunState` TypedDict:**
- Purpose: Canonical graph state; single source of truth for all in-flight data
- Location: `src/agentic_workflows/orchestration/langgraph/state_schema.py`
- Pattern: Fully typed; `new_run_state()` constructs initial state; `ensure_state_defaults()` repairs at every node entry

**`ContextManager`:**
- Purpose: Multi-mission message lifecycle management
- Location: `src/agentic_workflows/orchestration/langgraph/context_manager.py`
- Pattern: `compact(state)` evicts old messages; `build_planner_context_injection()` injects completed-mission summaries once per mission (tracked via `policy_flags["injected_mission_ids"]`)

**`LangGraphOrchestrator` (Mixin Composition):**
- Purpose: Main orchestration engine
- Location: `src/agentic_workflows/orchestration/langgraph/orchestrator.py`
- Pattern: Multiple inheritance from four mixins; `__init__` owns all state; `_compile_graph()` returns compiled `StateGraph`; `run()` returns `RunResult`

**Specialist Subgraphs:**
- Purpose: Isolated StateGraphs for executor and evaluator roles
- Location: `src/agentic_workflows/orchestration/langgraph/specialist_executor.py`, `specialist_evaluator.py`
- Pattern: Own `ExecutorState`/`EvaluatorState` TypedDicts; compiled at orchestrator init; invoked via `_route_to_specialist()` for specialist handoffs

**`TaskHandoff` / `HandoffResult`:**
- Purpose: Typed contract for supervisor→specialist delegation
- Location: `src/agentic_workflows/orchestration/langgraph/handoff.py`
- Pattern: Pydantic `BaseModel` with `extra="forbid"`; serialized to `dict` for `RunState` storage

**`ModelRouter`:**
- Purpose: Cost-aware strong-vs-fast provider selection
- Location: `src/agentic_workflows/orchestration/langgraph/model_router.py`
- Pattern: `route_by_signals(RoutingSignals)` → `ChatProvider`; signals: retry count, token budget, mission type, intent classification

## Entry Points

**CLI Demo:**
- Location: `src/agentic_workflows/orchestration/langgraph/run.py`
- Triggers: `python -m agentic_workflows.orchestration.langgraph.run`
- Responsibilities: Parses CLI args, constructs `LangGraphOrchestrator`, calls `run()`, renders audit panel

**CLI Audit:**
- Location: `src/agentic_workflows/orchestration/langgraph/run_audit.py`
- Triggers: `python -m agentic_workflows.orchestration.langgraph.run_audit`
- Responsibilities: Cross-run audit summary from checkpoint store

**FastAPI App:**
- Location: `src/agentic_workflows/api/app.py`
- Triggers: `uvicorn agentic_workflows.api.app:app`
- Responsibilities: HTTP API; compiles graph once at startup; routes: `POST /run` (async SSE stream), `GET /runs`, `GET /health`, `GET /tools`

**Legacy Core Demo:**
- Location: `src/agentic_workflows/core/main.py`
- Triggers: `python -m agentic_workflows.core.main`
- Responsibilities: Phase 0 baseline; not used in production

## Error Handling

**Strategy:** Retry-then-fail-closed; structured error hierarchy

**Patterns:**
- `RetryableAgentError` (e.g., `InvalidJSONError`, `SchemaValidationError`): increment `retry_counts`; planner re-prompts with correction hint
- `FatalAgentError` (e.g., `UnknownToolError`): immediate stop
- `ProviderTimeoutError`: increments `retry_counts["provider_timeout"]`; after `max_provider_timeout_retries` enters `planner_timeout_mode` (deterministic fallback actions only)
- `MemoizationPolicyViolation`: raised when memoization policy retries exhausted
- JSON parse failures: `action_parser` tries two-stage parse (strict JSON → extract-first-object fallback); sets `structural_health["json_parse_fallback"]` counter
- Content validation failures: `content_validator` checks before tool execution; increments `retry_counts["content_validation"]`
- Duplicate tool calls: blocked via `seen_tool_signatures` set; `retry_counts["duplicate_tool"]` tracks occurrences

## Cross-Cutting Concerns

**Logging:** Structured logging via `src/agentic_workflows/logger.py`; `get_logger(name)` returns named logger; `setup_dual_logging()` configures file + console output; log dir configurable via `GSD_LOG_DIR`

**Validation:** Pydantic `extra="forbid"` at handoff boundaries (`TaskHandoff`, `HandoffResult`); `ToolAction`/`FinishAction` validated by `action_parser.validate_action()` at every planner step; `ensure_state_defaults()` defensive key repair at every node entry

**Authentication:** API key middleware in `src/agentic_workflows/api/middleware/` checks `X-API-Key` header; configurable via env

**Token Budget:** `token_budget_remaining` decremented via `len(text) // 4` estimation; at 0, triggers `planner_timeout_mode` in `policy_flags`; role-specific budgets in `_ROLE_TOKEN_BUDGETS` (classifier: 300, planner: 2500, executor: 300)

**Observability:** Langfuse spans via `@observe` decorator on planner and provider calls; `report_schema_compliance()` logs structural health metrics; all controlled by `agentic_workflows.observability` module (degrades gracefully without Langfuse credentials)

---

*Architecture analysis: 2026-03-12*
