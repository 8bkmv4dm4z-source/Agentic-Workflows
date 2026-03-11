# Architecture

**Analysis Date:** 2026-03-12

## Pattern Overview

**Overall:** Plan-and-Execute Graph Orchestration (LangGraph StateGraph)

**Key Characteristics:**
- Single `RunState` TypedDict flows through a compiled `StateGraph` (plan → execute → policy → finalize loop)
- Four mixin classes compose the `LangGraphOrchestrator` via multiple inheritance — each mixin owns one concern
- All state mutations happen in-place on `RunState`; Annotated list fields use `operator.add` reducers for parallel-safe merge
- Deterministic tools (no LLM calls) execute inside the `execute` node; all LLM calls happen only in the `plan` node
- Post-run auditing is deterministic (no LLM) via `mission_auditor.py`

## Layers

**Schemas / Contracts:**
- Purpose: Define all typed data shapes used across the system
- Location: `src/agentic_workflows/schemas.py`, `src/agentic_workflows/orchestration/langgraph/state_schema.py`, `src/agentic_workflows/orchestration/langgraph/handoff.py`
- Contains: `ToolAction`, `FinishAction`, `ClarifyAction` (Pydantic, `extra="forbid"`); `RunState` TypedDict; `ToolRecord`, `MissionReport`, `MemoEvent`, `RunResult`; `TaskHandoff`, `HandoffResult` (Pydantic, `extra="forbid"`)
- Depends on: nothing (leaf layer)
- Used by: all other layers

**Tools:**
- Purpose: Deterministic, pure-function tool implementations; no LLM calls
- Location: `src/agentic_workflows/tools/`
- Contains: 35+ `Tool` subclasses (one file per tool), `Tool` base class in `base.py`, output schema helpers in `output_schemas.py`, security guardrails in `_security.py`
- Depends on: `schemas.py`, `errors.py`
- Used by: `tools_registry.py`, executor node

**Storage:**
- Purpose: Abstract persistence layer via Protocols
- Location: `src/agentic_workflows/storage/`
- Contains: `RunStore` protocol (`protocol.py`), `CheckpointStore` protocol (`checkpoint_protocol.py`), `MemoStore` protocol (`memo_protocol.py`), SQLite backends (`sqlite.py`), Postgres backends (`postgres.py`), `MissionContextStore`, `ArtifactStore`, `ToolResultCache`, `MemoryConsolidation`
- Depends on: `state_schema.py`
- Used by: orchestrator, API layer

**Orchestration — LangGraph:**
- Purpose: Graph compilation, planning, execution, lifecycle management
- Location: `src/agentic_workflows/orchestration/langgraph/`
- Contains: `LangGraphOrchestrator` assembled from four mixins (`orchestrator.py`); planning loop (`planner_node.py`); execution routing (`executor_node.py`); finalization/policy (`lifecycle_nodes.py`); prompt helpers (`planner_helpers.py`); context window management (`context_manager.py`); action parsing (`action_parser.py`); mission parsing (`mission_parser.py`); post-run audit (`mission_auditor.py`); cost-aware model routing (`model_router.py`); specialist subgraphs (`specialist_executor.py`, `specialist_evaluator.py`); tool registry (`tools_registry.py`); provider adapters (`provider.py`); memo/checkpoint stores (`memo_store.py`, `checkpoint_store.py`, `memo_postgres.py`, `checkpoint_postgres.py`)
- Depends on: schemas, tools, storage, observability
- Used by: API layer, CLI entry points

**API Layer:**
- Purpose: FastAPI HTTP service with SSE streaming
- Location: `src/agentic_workflows/api/`
- Contains: route handlers (`routes/run.py`, `routes/runs.py`, `routes/tools.py`, `routes/health.py`), SSE event builders (`sse.py`), stream token HMAC auth (`stream_token.py`), middleware (`middleware/api_key.py`, `middleware/request_id.py`), Pydantic request/response models (`models.py`)
- Depends on: orchestration layer, storage protocols
- Used by: external HTTP clients

**CLI Entry Points:**
- Purpose: Interactive and scripted CLI interfaces
- Location: `src/agentic_workflows/orchestration/langgraph/run.py`, `src/agentic_workflows/orchestration/langgraph/user_run.py`, `src/agentic_workflows/orchestration/langgraph/run_audit.py`, `src/agentic_workflows/cli/user_run.py`
- Contains: demo runner with audit panel, user-facing interactive run, cross-run audit summary
- Depends on: orchestration layer

**Observability:**
- Purpose: Langfuse tracing with graceful no-op degradation
- Location: `src/agentic_workflows/observability.py`
- Contains: `observe` decorator, `get_langfuse_client`, `get_langfuse_callback_handler`, `report_schema_compliance`
- Depends on: nothing (self-contained with optional langfuse import)
- Used by: orchestrator, provider adapters

**Core (Legacy P0 baseline):**
- Purpose: Original non-LangGraph orchestrator, kept for reference
- Location: `src/agentic_workflows/core/`
- Contains: `Orchestrator` (simple loop), `AgentState`, `LLMProvider`
- Status: Excluded from coverage, superseded by the LangGraph orchestrator

## Data Flow

**Standard Run (non-Anthropic providers):**

1. Caller invokes `LangGraphOrchestrator.run(user_input)` or `POST /run`
2. `prepare_state()` calls `parse_missions()` (regex + optional spaCy) → populates `RunState.missions`, `mission_contracts`, `structured_plan`
3. LangGraph compiled graph starts at `START → plan`
4. `_plan_next_action()` (PlannerNodeMixin): compacts context via `ContextManager`, calls `ChatProvider.generate()` with timeout, parses JSON action via `action_parser.validate_action()`
5. `_route_after_plan()` conditional edge: routes to `execute`, `plan` (retry), `finalize` (finish action), or `clarify`
6. `_route_to_specialist()` (ExecutorNodeMixin): selects specialist role, optionally delegates to `specialist_executor` or `specialist_evaluator` subgraph, then calls `_execute_action()`
7. `_execute_action()`: dedup check (`seen_tool_signatures`), tool dispatch from registry, result stored in `tool_history` and `mission_contexts`
8. `_enforce_memo_policy()` (LifecycleNodesMixin): checks if memoization is required after heavy tool results
9. Loop returns to `plan`; exits when `pending_action.action == "finish"` or `step > max_steps`
10. `_finalize()`: calls `audit_run()` (deterministic 9-check auditor), writes `Shared_plan.md`, saves final checkpoint
11. `run()` returns `RunResult` TypedDict

**Anthropic Provider Path (ReAct via ToolNode):**

1. Same `prepare_state()` initialization
2. `plan` node uses Anthropic's native tool-call format
3. `tools_condition` routes to `tools` (LangGraph `ToolNode`) or `finalize`
4. `ToolNode` executes tools; `_dedup_then_tool_node()` wrapper enforces `seen_tool_signatures` before dispatch
5. Returns to `plan` for next step

**Mission Parsing Flow:**
1. `parse_missions(user_input)` runs with threading timeout
2. Tries spaCy clause segmentation → regex keyword map fallback
3. Returns `StructuredPlan` with `flat_missions` list and `parsing_method` field
4. Timeout increments `structural_health.parser_timeout_count`

**State Management:**
- Single `RunState` TypedDict passed through all graph nodes
- `ensure_state_defaults()` called at the top of every node — hardens missing keys before logic runs
- `tool_history`, `memo_events`, `mission_reports` are Annotated with `operator.add` (parallel-safe append-only)
- `_sequential_node()` wrapper zeros out these fields in returned dicts to prevent doubling in sequential runs
- `ContextManager` compacts `state["messages"]` before each planner call; uses `policy_flags["injected_mission_ids"]` for dedup

## Key Abstractions

**`LangGraphOrchestrator`:**
- Purpose: Central orchestration engine — composes four mixins
- Location: `src/agentic_workflows/orchestration/langgraph/orchestrator.py`
- Pattern: Multiple inheritance of `PlannerHelpersMixin`, `PlannerNodeMixin`, `ExecutorNodeMixin`, `LifecycleNodesMixin`; graph compiled via `_compile_graph()` in `__init__`

**`ChatProvider` Protocol:**
- Purpose: Unified LLM provider interface — all vendors behind one contract
- Location: `src/agentic_workflows/orchestration/langgraph/provider.py`
- Pattern: `Protocol` with `generate(messages, response_schema=None) -> str` and `context_size() -> int`; concrete implementations: `OllamaChatProvider`, `OpenAIChatProvider`, `GroqChatProvider`, `LlamaCppChatProvider`, `ScriptedChatProvider` (tests)

**`Tool` base class:**
- Purpose: Base contract for all tool implementations
- Location: `src/agentic_workflows/tools/base.py`
- Pattern: `name: str`, `description: str`, `execute(args: dict) -> dict`; `args_schema` property derived from description string via regex fallback

**`RunState` TypedDict:**
- Purpose: Canonical mutable state bag flowing through every graph node
- Location: `src/agentic_workflows/orchestration/langgraph/state_schema.py`
- Pattern: TypedDict with 25+ fields; initialized via `new_run_state()`, hardened via `ensure_state_defaults()`

**`ModelRouter`:**
- Purpose: Cost-aware routing between strong and fast LLM providers
- Location: `src/agentic_workflows/orchestration/langgraph/model_router.py`
- Pattern: Signal-based routing using `RoutingSignals` TypedDict; thresholds: retry >= 2 or budget < 5000 → strong; `multi_step` mission type → strong

**`ContextManager`:**
- Purpose: Context window management for multi-mission runs
- Location: `src/agentic_workflows/orchestration/langgraph/context_manager.py`
- Pattern: `compact()` called before each plan step; `proactive_compact()` against provider context size; `build_planner_context_injection()` injects prior mission summaries; dedup via `policy_flags["injected_mission_ids"]`; `large_result_threshold=3000`, `sliding_window_cap=20`

**Specialist Subgraphs:**
- Purpose: Isolated StateGraphs for delegated tool execution and evaluation
- Location: `src/agentic_workflows/orchestration/langgraph/specialist_executor.py`, `specialist_evaluator.py`
- Pattern: Separate `ExecutorState`/`EvaluatorState` Typedicts; compiled via `build_executor_subgraph()`, `build_evaluator_subgraph()`; invoked from `ExecutorNodeMixin._route_to_specialist()`

**`MissionAuditor`:**
- Purpose: Deterministic post-run correctness verification (no LLM)
- Location: `src/agentic_workflows/orchestration/langgraph/mission_auditor.py`
- Pattern: 9 keyword-driven checks; returns `AuditReport` with `AuditFinding` entries at pass/warn/fail level; `_approx_equal()` for numeric tolerance

## Entry Points

**CLI Demo Runner:**
- Location: `src/agentic_workflows/orchestration/langgraph/run.py`
- Triggers: `python -m agentic_workflows.orchestration.langgraph.run` or `make run`
- Responsibilities: Instantiate `LangGraphOrchestrator`, execute hardcoded demo missions, print structured audit panel via `run_ui.py`

**Interactive User CLI:**
- Location: `src/agentic_workflows/orchestration/langgraph/user_run.py`, `src/agentic_workflows/cli/user_run.py`
- Triggers: Direct execution or CLI command
- Responsibilities: Accept user-supplied mission text, invoke orchestrator, display results

**FastAPI Service:**
- Location: `src/agentic_workflows/api/` (app module not shown in glob but referenced)
- Triggers: `uvicorn` / `make run` with `P1_PROVIDER` set
- Responsibilities: `POST /run` → SSE stream of node-transition events; `GET /run/{id}` → run status; `GET /run/{id}/stream` → reconnect stream

**Cross-Run Audit:**
- Location: `src/agentic_workflows/orchestration/langgraph/run_audit.py`
- Triggers: `python -m agentic_workflows.orchestration.langgraph.run_audit`
- Responsibilities: Aggregate findings across multiple stored runs

## Error Handling

**Strategy:** Layered — retryable errors cause planner retry with incremented `retry_counts`; fatal errors terminate the run with a `finish` action containing the error message

**Exception Hierarchy (`src/agentic_workflows/errors.py`):**
- `AgentError` → `RetryableAgentError`: `InvalidJSONError`, `SchemaValidationError`, `MissingActionError`, `UnknownActionError`, `ToolExecutionError`, `LLMError`
- `AgentError` → `FatalAgentError`: `UnknownToolError`
- `ProviderTimeoutError` (in `provider.py`) triggers `planner_timeout_mode` in `policy_flags`

**Retry Counters (`RunState.retry_counts`):**
- `invalid_json`: incremented on JSON parse failure, up to `max_invalid_plan_retries` (default 8)
- `provider_timeout`: up to `max_provider_timeout_retries` (default 3); then `planner_timeout_mode=True`
- `content_validation`: up to `max_content_validation_retries` (default 2)
- `duplicate_tool`: up to `max_duplicate_tool_retries` (default 6)
- `finish_rejected`: up to `max_finish_rejections` (default 6)

**Fallback Planner (`src/agentic_workflows/orchestration/langgraph/fallback_planner.py`):**
- When `planner_timeout_mode=True`, `deterministic_fallback_action()` generates safe tool/finish actions from local state without LLM calls

## Cross-Cutting Concerns

**Logging:** `src/agentic_workflows/logger.py` — `get_logger(name)` returns a named Python logger; structured logging via `structlog` in API layer; dual logging to file via `setup_dual_logging()` in run.py

**Validation:** All LLM outputs parsed through `action_parser.validate_action()` → Pydantic `ToolAction`/`FinishAction` with `extra="forbid"`; handoff messages validated through `TaskHandoff`/`HandoffResult` Pydantic models; `content_validator.py` provides secondary content checks

**Authentication:** API key middleware at `src/agentic_workflows/api/middleware/api_key.py`; HMAC stream tokens via `src/agentic_workflows/api/stream_token.py` for SSE reconnect

**Observability:** `@observe(name)` decorator wraps key methods; Langfuse callback handler injected into LangGraph config per-run via `ContextVar` for thread isolation; degrades gracefully to no-op when not configured

**Duplicate Prevention:** `seen_tool_signatures` set in `RunState` blocks exact duplicate tool calls; signatures computed as SHA-256 hash of `(tool_name, args)`

**Token Budget:** `token_budget_remaining` (default 100,000) decremented via `len(text) // 4` estimation; reaches 0 → triggers `planner_timeout_mode`

---

*Architecture analysis: 2026-03-12*
