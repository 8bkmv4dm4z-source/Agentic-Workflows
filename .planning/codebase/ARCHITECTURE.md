# Architecture

**Analysis Date:** 2026-03-05

## Pattern Overview

**Overall:** Layered Python application with a stateful LangGraph orchestration core, exposed through CLI and FastAPI service entry points.

**Key Characteristics:**
- Active runtime is a typed state-graph orchestrator in `src/agentic_workflows/orchestration/langgraph/graph.py`.
- Deterministic tool execution is isolated under `src/agentic_workflows/tools/`, with no LLM calls in that layer.
- Runtime state and artifacts are persisted locally through SQLite-backed stores in `src/agentic_workflows/orchestration/langgraph/checkpoint_store.py`, `src/agentic_workflows/orchestration/langgraph/memo_store.py`, and `src/agentic_workflows/storage/sqlite.py`.
- The repo still carries a legacy pre-LangGraph compatibility path in `src/agentic_workflows/core/`.
- Planning and specialist behavior are documented as markdown directives in `src/agentic_workflows/directives/`, but prompt assembly currently happens in code.

## Layers

**Interface Layer:**
- Purpose: Accept user input, start runs, stream progress, and render results.
- Contains: FastAPI app and routes in `src/agentic_workflows/api/app.py` and `src/agentic_workflows/api/routes/*.py`, API client in `src/agentic_workflows/cli/user_run.py`, direct demo CLIs in `src/agentic_workflows/orchestration/langgraph/run.py`, `src/agentic_workflows/orchestration/langgraph/run_audit.py`, and `src/agentic_workflows/core/main.py`.
- Depends on: Orchestration layer, API models, storage layer.
- Used by: HTTP clients, terminal users, and local demo scripts.

**Orchestration Layer:**
- Purpose: Convert natural-language input into mission plans, tool actions, retries, audits, and final answers.
- Contains: `LangGraphOrchestrator` and graph node logic in `src/agentic_workflows/orchestration/langgraph/graph.py`, mission parsing in `src/agentic_workflows/orchestration/langgraph/mission_parser.py`, routing in `src/agentic_workflows/orchestration/langgraph/model_router.py`, content/action validation helpers, reviewer logic, and checkpoint/memo coordination modules.
- Depends on: Provider adapters, tool registry, typed state schema, persistence helpers, directives metadata.
- Used by: API routes, CLI/demo entry points.

**Specialist Subgraph Layer:**
- Purpose: Isolate executor and evaluator responsibilities behind explicit handoff contracts.
- Contains: Handoff schemas in `src/agentic_workflows/orchestration/langgraph/handoff.py`, executor subgraph in `src/agentic_workflows/orchestration/langgraph/specialist_executor.py`, evaluator subgraph in `src/agentic_workflows/orchestration/langgraph/specialist_evaluator.py`, and directive/tool-scope metadata in `src/agentic_workflows/orchestration/langgraph/directives.py`.
- Depends on: Orchestration layer, tool registry, mission auditor.
- Used by: `LangGraphOrchestrator._route_to_specialist()` in `src/agentic_workflows/orchestration/langgraph/graph.py`.

**Execution Layer:**
- Purpose: Perform deterministic work against files, text, shell, HTTP, SQL, and utility tasks.
- Contains: Base tool contract in `src/agentic_workflows/tools/base.py`, concrete tools in `src/agentic_workflows/tools/*.py`, and output validation in `src/agentic_workflows/tools/output_schemas.py`.
- Depends on: Local Python/runtime libraries only; no provider abstraction is used here.
- Used by: Tool registry in `src/agentic_workflows/orchestration/langgraph/tools_registry.py`, legacy `src/agentic_workflows/core/orchestrator.py`.

**Persistence and Runtime State Layer:**
- Purpose: Keep run metadata, memoized values, and checkpointed graph state durable across requests and sessions.
- Contains: Run store protocol in `src/agentic_workflows/storage/protocol.py`, SQLite run store in `src/agentic_workflows/storage/sqlite.py`, checkpoint store in `src/agentic_workflows/orchestration/langgraph/checkpoint_store.py`, memo store in `src/agentic_workflows/orchestration/langgraph/memo_store.py`, and typed run state in `src/agentic_workflows/orchestration/langgraph/state_schema.py`.
- Depends on: SQLite, JSON serialization, AnyIO thread offloading for async-safe access.
- Used by: API layer, orchestration layer, CLI session persistence in `src/agentic_workflows/cli/user_run.py`.

**Legacy Compatibility Layer:**
- Purpose: Preserve the original single-agent loop for comparison, walkthroughs, and regression context.
- Contains: `src/agentic_workflows/core/orchestrator.py`, `src/agentic_workflows/core/llm_provider.py`, `src/agentic_workflows/core/agent_state.py`, and `src/agentic_workflows/core/main.py`.
- Depends on: Tool layer and legacy schemas in `src/agentic_workflows/schemas.py`.
- Used by: `src/agentic_workflows/core/main.py`; not the active production service path.

## Data Flow

**HTTP/SSE Run:**

1. A client calls `POST /run` in `src/agentic_workflows/api/routes/run.py`.
2. The FastAPI lifespan in `src/agentic_workflows/api/app.py` initializes one `LangGraphOrchestrator` and one `SQLiteRunStore`.
3. The route builds initial run state from `RunRequest`, merges any `prior_context`, and persists a `running` record through `src/agentic_workflows/storage/sqlite.py`.
4. Mission parsing in `src/agentic_workflows/orchestration/langgraph/mission_parser.py` produces `StructuredPlan` plus per-mission contracts.
5. The compiled graph in `src/agentic_workflows/orchestration/langgraph/graph.py` executes the loop `plan -> execute -> policy -> plan`, with terminal routing to `finalize`.
6. The execute step routes work through specialist handoffs; the executor subgraph dispatches registered tools from `src/agentic_workflows/orchestration/langgraph/tools_registry.py`.
7. The finalize step writes checkpoints, derives snapshots, runs deterministic audit logic, and prepares the final result payload.
8. The API route streams node lifecycle events via helpers in `src/agentic_workflows/api/sse.py`, stores the completed result, and makes it retrievable through `GET /run/{run_id}`.

**CLI Session Flow:**

1. A user starts `python -m agentic_workflows.cli.user_run`.
2. `src/agentic_workflows/cli/user_run.py` checks `GET /health`, auto-starts `uvicorn` if needed, and loads prior chat history from `user_runs/context.json`.
3. Each prompt is posted to `POST /run`, then SSE events are rendered in the terminal.
4. On completion, the CLI appends the user/assistant turns back into `user_runs/context.json`.

**Direct Demo Flow:**

1. A user runs `python -m agentic_workflows.orchestration.langgraph.run`.
2. The script constructs `LangGraphOrchestrator`, invokes `.run()`, and prints audit/review panels from `src/agentic_workflows/orchestration/langgraph/run_ui.py`.
3. This bypasses FastAPI but still uses the same graph, state schema, memo store, and checkpoint store.

**State Management:**
- Primary in-flight state is the `RunState` TypedDict in `src/agentic_workflows/orchestration/langgraph/state_schema.py`.
- Durable execution state is persisted per node in `src/agentic_workflows/orchestration/langgraph/checkpoint_store.py`.
- Memo-before-write enforcement uses `src/agentic_workflows/orchestration/langgraph/policy.py` with persisted values in `src/agentic_workflows/orchestration/langgraph/memo_store.py`.
- Service-level run records are stored in `src/agentic_workflows/storage/sqlite.py`.
- CLI conversation continuity is file-based in `user_runs/context.json`.

## Key Abstractions

**LangGraphOrchestrator:**
- Purpose: Central application service that compiles and runs the LangGraph workflow.
- Examples: `src/agentic_workflows/orchestration/langgraph/graph.py`, re-exported by `src/agentic_workflows/orchestration/langgraph/langgraph_orchestrator.py`.
- Pattern: Stateful orchestrator/facade around a compiled `StateGraph`.

**RunState:**
- Purpose: Canonical typed state shared across graph nodes and persisted checkpoints.
- Examples: `RunState`, `RunResult`, `MissionReport`, and `AgentMessage` in `src/agentic_workflows/orchestration/langgraph/state_schema.py`.
- Pattern: TypedDict-based workflow state contract with reducer-annotated list fields.

**StructuredPlan:**
- Purpose: Structured decomposition of user input into ordered missions and dependencies.
- Examples: `StructuredPlan` and `MissionStep` in `src/agentic_workflows/orchestration/langgraph/mission_parser.py`.
- Pattern: Parser-produced domain model with backward-compatible flat mission list.

**ChatProvider and ModelRouter:**
- Purpose: Hide vendor-specific LLM clients behind a single `generate(messages)` contract and choose provider tier by task type.
- Examples: `ChatProvider` and provider implementations in `src/agentic_workflows/orchestration/langgraph/provider.py`, `ModelRouter` in `src/agentic_workflows/orchestration/langgraph/model_router.py`.
- Pattern: Protocol plus adapter/router abstraction.

**Tool:**
- Purpose: Stable deterministic execution contract for all callable tools.
- Examples: `Tool` in `src/agentic_workflows/tools/base.py`, registry assembly in `src/agentic_workflows/orchestration/langgraph/tools_registry.py`, concrete implementations like `src/agentic_workflows/tools/read_file.py` and `src/agentic_workflows/tools/query_sql.py`.
- Pattern: Simple command object interface with registry lookup by name.

**RunStore:**
- Purpose: Abstract persistence contract for run metadata independent of backend.
- Examples: `RunStore` in `src/agentic_workflows/storage/protocol.py`, `SQLiteRunStore` in `src/agentic_workflows/storage/sqlite.py`.
- Pattern: Protocol-backed repository abstraction.

**DirectiveConfig:**
- Purpose: Versioned role metadata for supervisor, executor, and evaluator responsibilities.
- Examples: `DirectiveConfig` and `DIRECTIVE_BY_SPECIALIST` in `src/agentic_workflows/orchestration/langgraph/directives.py`, markdown sources in `src/agentic_workflows/directives/*.md`.
- Pattern: Configuration object linked to checked-in markdown contracts.

## Entry Points

**FastAPI Service:**
- Location: `src/agentic_workflows/api/app.py`
- Triggers: `uvicorn`, direct module execution, or the CLI auto-start path.
- Responsibilities: Create app state, compile orchestrator once, register routes, return structured API errors.

**Streaming Run Endpoint:**
- Location: `src/agentic_workflows/api/routes/run.py`
- Triggers: `POST /run`
- Responsibilities: Persist run start, execute the graph in a worker thread, stream SSE events, and store final results.

**Interactive API Client:**
- Location: `src/agentic_workflows/cli/user_run.py`
- Triggers: `python -m agentic_workflows.cli.user_run`
- Responsibilities: Ensure the service is live, post user turns, render SSE output, persist local context.

**Direct Graph Demo:**
- Location: `src/agentic_workflows/orchestration/langgraph/run.py`
- Triggers: `python -m agentic_workflows.orchestration.langgraph.run`
- Responsibilities: Execute the orchestrator without HTTP and print review/audit panels.

**Audit Demo:**
- Location: `src/agentic_workflows/orchestration/langgraph/run_audit.py`
- Triggers: `python -m agentic_workflows.orchestration.langgraph.run_audit`
- Responsibilities: Audit-oriented CLI workflow. Concrete runtime behavior was not inspected in this pass.

**Legacy Demo:**
- Location: `src/agentic_workflows/core/main.py`
- Triggers: Direct script execution or import-time demo usage.
- Responsibilities: Exercise the old `core/` orchestrator loop against a hardcoded multi-task prompt.

## Error Handling

**Strategy:** Fail closed inside the orchestration loop, persist checkpoints for post-mortem inspection, and expose structured API errors at the service boundary.

**Patterns:**
- Planner invalid JSON, empty outputs, provider timeouts, and premature finish attempts are retried or downgraded to deterministic fallback behavior inside `src/agentic_workflows/orchestration/langgraph/graph.py`.
- Memoization policy violations are enforced after execution by `src/agentic_workflows/orchestration/langgraph/policy.py` before the graph is allowed to continue.
- Tool-level failures are returned as result payloads and recorded in run history rather than hidden.
- API validation and unexpected server errors are translated to `ErrorResponse` in `src/agentic_workflows/api/app.py`.
- SQLite-backed checkpoints in `src/agentic_workflows/orchestration/langgraph/checkpoint_store.py` and run records in `src/agentic_workflows/storage/sqlite.py` preserve failure context.

## Cross-Cutting Concerns

**Logging:**
- Standard logging is centralized in `src/agentic_workflows/logger.py`.
- The project writes both verbose and admin-filtered logs into `.tmp/` through `setup_dual_logging()`.
- API/service logs additionally use `structlog` in `src/agentic_workflows/api/app.py` and `src/agentic_workflows/api/routes/run.py`.

**Validation:**
- Request and response schemas are defined with Pydantic v2 in `src/agentic_workflows/api/models.py`.
- Planner output and tool output validation are enforced in `src/agentic_workflows/orchestration/langgraph/graph.py` and `src/agentic_workflows/tools/output_schemas.py`.
- State-shape repair and defaulting are handled in `src/agentic_workflows/orchestration/langgraph/state_schema.py`.

**Authentication:**
- Not detected.

**Observability:**
- Optional Langfuse integration is wrapped in `src/agentic_workflows/observability.py`.
- The runtime degrades to no-op instrumentation when Langfuse is absent or unconfigured.

**Configuration:**
- Runtime selection and provider credentials are environment-driven via `.env` and `.env.example`; actual secret values were not inspected.
- Package/test/tooling configuration lives in `pyproject.toml`, `.pre-commit-config.yaml`, and `.github/workflows/ci.yml`.

*Architecture analysis: 2026-03-05*
*Update when major patterns change*
