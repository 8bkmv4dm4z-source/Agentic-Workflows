# Architecture

**Analysis Date:** 2026-03-05

## Pattern Overview

**Overall:** Layered Python monolith with a FastAPI service shell around a
LangGraph orchestration core and a deterministic tool layer.

**Key Characteristics:**
- Current production path is the FastAPI app in `src/agentic_workflows/api/app.py`
  backed by `LangGraphOrchestrator` in
  `src/agentic_workflows/orchestration/langgraph/graph.py`.
- Tool execution is isolated in `src/agentic_workflows/tools/` and remains
  deterministic by design; LLM calls are routed through
  `src/agentic_workflows/orchestration/langgraph/provider.py`.
- Runtime state is explicit and typed through `RunState` in
  `src/agentic_workflows/orchestration/langgraph/state_schema.py`, then
  persisted into SQLite-backed stores.
- The same orchestration core is exposed through multiple interfaces:
  FastAPI/SSE in `src/agentic_workflows/api/`, API-backed CLI in
  `src/agentic_workflows/cli/user_run.py`, and direct demo/audit CLIs in
  `src/agentic_workflows/orchestration/langgraph/run.py` and
  `src/agentic_workflows/orchestration/langgraph/run_audit.py`.
- `src/agentic_workflows/core/` still exists as a Phase 0 baseline and
  comparison path, but `src/agentic_workflows/README.md` marks the
  LangGraph runtime as the active production path.

## Layers

**Interface Layer:**
- Purpose: Accept user input, validate requests, stream progress, and expose
  operational entry points.
- Contains: FastAPI app, HTTP routes, Pydantic API models, middleware, SSE
  event builders, and CLI frontends in `src/agentic_workflows/api/` and
  `src/agentic_workflows/cli/`.
- Depends on: Orchestration and persistence layers.
- Used by: Human operators, API clients, and terminal sessions.

**Orchestration Layer:**
- Purpose: Turn user intent into a controlled execution loop with planning,
  mission parsing, specialist routing, memo policy checks, and audit.
- Contains: `src/agentic_workflows/orchestration/langgraph/graph.py`,
  `state_schema.py`, `mission_parser.py`, `mission_auditor.py`,
  `model_router.py`, `policy.py`, `provider.py`, `reviewer.py`, and specialist
  helpers such as `specialist_executor.py` and `specialist_evaluator.py`.
- Depends on: Tool layer, directive contracts, observability, and SQLite stores.
- Used by: FastAPI routes, direct CLI runners, and tests.

**Execution Layer:**
- Purpose: Perform concrete work without model calls.
- Contains: `Tool` implementations in `src/agentic_workflows/tools/`, anchored
  by `src/agentic_workflows/tools/base.py` and assembled through
  `src/agentic_workflows/orchestration/langgraph/tools_registry.py`.
- Depends on: Standard library plus targeted infrastructure helpers such as file
  I/O, shell execution, HTTP, and data parsing.
- Used by: The orchestrator execute node and specialist subgraphs.

**Persistence Layer:**
- Purpose: Persist long-lived execution data and provide retrieval paths for
  status APIs and reruns.
- Contains: Run storage in `src/agentic_workflows/storage/protocol.py` and
  `src/agentic_workflows/storage/sqlite.py`, plus memo/checkpoint stores in
  `src/agentic_workflows/orchestration/langgraph/memo_store.py` and
  `src/agentic_workflows/orchestration/langgraph/checkpoint_store.py`.
- Depends on: SQLite and `anyio.to_thread.run_sync` for async-safe access.
- Used by: API routes, orchestration finalization, memo policy, and audit tools.

**Specification Layer:**
- Purpose: Hold behavior contracts and shared schemas that constrain the runtime.
- Contains: Directive documents in `src/agentic_workflows/directives/`,
  response/request models in `src/agentic_workflows/api/models.py`, and shared
  schema helpers in `src/agentic_workflows/schemas.py`.
- Depends on: Minimal shared types only.
- Used by: Runtime prompt construction, API validation, design review, and tests.

**Legacy Baseline Layer:**
- Purpose: Preserve the earlier single-agent loop for comparison and regression
  reference.
- Contains: `src/agentic_workflows/core/orchestrator.py`,
  `src/agentic_workflows/core/llm_provider.py`, and
  `src/agentic_workflows/core/main.py`.
- Depends on: Tools and older schema/error modules.
- Used by: Legacy demo entry point; not the primary production path.

## Data Flow

**HTTP Run Request (current production path):**

1. `uvicorn` loads `src/agentic_workflows/api/app.py`, whose lifespan handler
   creates one `LangGraphOrchestrator` and one `SQLiteRunStore`.
2. `POST /run` in `src/agentic_workflows/api/routes/run.py` validates the body
   with `RunRequest`, allocates a public `run_id`, persists the initial run row,
   and opens an SSE stream.
3. The route builds `RunState` via `new_run_state()` and
   `ensure_state_defaults()` from
   `src/agentic_workflows/orchestration/langgraph/state_schema.py`, then parses
   missions through `parse_missions()` in `mission_parser.py`.
4. `LangGraphOrchestrator._compiled.stream(...)` runs the graph. The standard
   path loops `plan -> execute -> policy -> plan` until `finalize`; the
   Anthropic-specific path can route `plan -> tools -> plan` through LangGraph
   `ToolNode`.
5. The plan node calls a `ChatProvider`; the execute node normalizes tool args,
   enforces specialist scope, runs one `Tool`, and records mission/tool history;
   the policy node may require `memoize`; the finalize node audits and saves the
   terminal checkpoint.
6. `src/agentic_workflows/api/routes/run.py` reloads the final checkpoint,
   updates `SQLiteRunStore`, and emits `node_start`, `node_end`, and
   `run_complete` SSE events to the client.

**CLI Conversation (API-backed):**

1. `src/agentic_workflows/cli/user_run.py` checks `GET /health`, optionally
   spawns `uvicorn`, and posts user text to `POST /run`.
2. SSE events are rendered in the terminal, and condensed prior turns are stored
   in `user_runs/context.json` for the next request.

**State Management:**
- Primary in-memory execution state is `RunState`.
- Durable orchestration state is split across `.tmp/langgraph_checkpoints.db`,
  `.tmp/memo_store.db`, and `.tmp/run_store.db`.
- Active reconnectable SSE streams live in `app.state.active_streams` in
  `src/agentic_workflows/api/app.py`.
- Shared plan snapshots are written to `Shared_plan.md`.

## Key Abstractions

**LangGraphOrchestrator:**
- Purpose: Compile the runtime graph and coordinate planning, execution, policy,
  specialist routing, and final audit.
- Examples: `src/agentic_workflows/orchestration/langgraph/graph.py`,
  `src/agentic_workflows/orchestration/langgraph/langgraph_orchestrator.py`.
- Pattern: Orchestration facade over a LangGraph `StateGraph`.

**RunState:**
- Purpose: Canonical typed state for a run, including messages, mission reports,
  retry counters, pending actions, and audit data.
- Examples: `src/agentic_workflows/orchestration/langgraph/state_schema.py`.
- Pattern: `TypedDict` state contract with default-repair helpers.

**Tool:**
- Purpose: Deterministic execution unit with a stable `execute(args)` contract.
- Examples: `src/agentic_workflows/tools/base.py`,
  `src/agentic_workflows/tools/write_file.py`,
  `src/agentic_workflows/tools/run_bash.py`.
- Pattern: Registry-backed command objects.

**ChatProvider / ModelRouter:**
- Purpose: Decouple orchestration from vendor-specific model APIs and choose
  strong vs fast providers when both exist.
- Examples: `src/agentic_workflows/orchestration/langgraph/provider.py`,
  `src/agentic_workflows/orchestration/langgraph/model_router.py`.
- Pattern: Protocol + adapter + routing facade.

**StructuredPlan:**
- Purpose: Represent parsed mission hierarchies before they are flattened into
  execution contracts.
- Examples: `src/agentic_workflows/orchestration/langgraph/mission_parser.py`.
- Pattern: Structured planning model with compatibility flattening.

**RunStore:**
- Purpose: Abstract persistence for API-visible run metadata and results.
- Examples: `src/agentic_workflows/storage/protocol.py`,
  `src/agentic_workflows/storage/sqlite.py`.
- Pattern: `Protocol` with SQLite implementation.

## Entry Points

**FastAPI Service:**
- Location: `src/agentic_workflows/api/app.py`
- Triggers: `uvicorn` startup or import of `agentic_workflows.api.app:app`
- Responsibilities: Construct app state, register middleware/routes, and host
  the HTTP/SSE interface.

**API-backed CLI:**
- Location: `src/agentic_workflows/cli/user_run.py`
- Triggers: `python -m agentic_workflows.cli.user_run`
- Responsibilities: Ensure service availability, stream SSE events, and persist
  local conversation context.

**Direct LangGraph Demo CLI:**
- Location: `src/agentic_workflows/orchestration/langgraph/run.py`
- Triggers: `python -m agentic_workflows.orchestration.langgraph.run`
- Responsibilities: Run the orchestrator directly, print audit panels, and
  support reviewer-driven rerun flows.

**Run Audit CLI:**
- Location: `src/agentic_workflows/orchestration/langgraph/run_audit.py`
- Triggers: `python -m agentic_workflows.orchestration.langgraph.run_audit`
- Responsibilities: Read checkpoint and memo stores and export run summaries.

**Legacy Phase 0 Demo:**
- Location: `src/agentic_workflows/core/main.py`
- Triggers: Direct module execution or developer comparison workflow
- Responsibilities: Exercise the older single-agent loop in
  `src/agentic_workflows/core/orchestrator.py`.

## Error Handling

**Strategy:** Validate aggressively at the boundaries, retry recoverable planner
errors inside the graph, and persist checkpoints/results so failures are
inspectable after the fact.

**Patterns:**
- FastAPI returns structured `ErrorResponse` payloads from
  `src/agentic_workflows/api/models.py` for `401`, `403`, `404`, `413`, `422`,
  and `500` paths.
- `src/agentic_workflows/orchestration/langgraph/provider.py` wraps vendor calls
  with timeout detection and retry/backoff behavior.
- `src/agentic_workflows/orchestration/langgraph/graph.py` tracks invalid JSON,
  duplicate tools, content validation failures, finish rejections, and memo
  policy retries inside `RunState["retry_counts"]`.
- Finalization always runs deterministic audit logic from
  `src/agentic_workflows/orchestration/langgraph/mission_auditor.py` before the
  terminal checkpoint is saved.

## Cross-Cutting Concerns

**Logging:**
- API requests use `structlog` plus request correlation in
  `src/agentic_workflows/api/middleware/request_id.py`.
- Direct CLI/orchestrator flows use `src/agentic_workflows/logger.py`, which can
  emit both verbose and admin-filtered logs into `.tmp/`.

**Validation:**
- HTTP inputs and outputs are typed with Pydantic v2 models in
  `src/agentic_workflows/api/models.py`.
- Planner actions are normalized and validated in
  `src/agentic_workflows/orchestration/langgraph/graph.py`, and tool outputs can
  be checked with `src/agentic_workflows/tools/output_schemas.py`.

**Authentication:**
- Shared API-key auth is implemented by
  `src/agentic_workflows/api/middleware/api_key.py`.
- SSE reconnects use HMAC stream tokens from
  `src/agentic_workflows/api/stream_token.py`.
- Per-user authorization or role-based access control: Not detected.

**Observability:**
- Optional Langfuse hooks live in `src/agentic_workflows/observability.py` and
  are attached by the API and direct orchestrator runs when configured.

**Configuration:**
- Runtime configuration is environment-driven through `.env` and environment
  variables consumed in `src/agentic_workflows/orchestration/langgraph/provider.py`
  and `src/agentic_workflows/api/app.py`.

---

*Architecture analysis: 2026-03-05*
*Update when major patterns change*
