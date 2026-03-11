# Codebase Structure

**Analysis Date:** 2026-03-12

## Directory Layout

```
agent_phase0/
├── src/
│   └── agentic_workflows/
│       ├── __init__.py
│       ├── schemas.py              # ToolAction, FinishAction, ClarifyAction (Pydantic)
│       ├── errors.py               # Exception hierarchy (AgentError tree)
│       ├── logger.py               # get_logger() factory
│       ├── observability.py        # Langfuse @observe, graceful no-op
│       ├── core/                   # Legacy P0 baseline (superseded, excluded from coverage)
│       │   ├── orchestrator.py
│       │   ├── agent_state.py
│       │   ├── llm_provider.py
│       │   └── main.py
│       ├── agents/                 # Agent variants (legacy)
│       │   └── local_agent.py
│       ├── context/                # Optional embedding provider
│       │   └── embedding_provider.py
│       ├── cli/                    # CLI wrappers
│       │   └── user_run.py
│       ├── api/                    # FastAPI service layer
│       │   ├── models.py           # RunRequest, RunStatusResponse, ErrorResponse
│       │   ├── sse.py              # SSE event builders
│       │   ├── stream_token.py     # HMAC reconnect token
│       │   ├── middleware/
│       │   │   ├── api_key.py
│       │   │   └── request_id.py
│       │   └── routes/
│       │       ├── run.py          # POST /run (SSE), GET /run/{id}
│       │       ├── runs.py         # GET /runs (listing)
│       │       ├── tools.py        # GET /tools
│       │       └── health.py       # GET /health
│       ├── directives/             # Agent SOPs (Markdown, read at runtime)
│       │   ├── supervisor.md
│       │   ├── executor.md
│       │   ├── evaluator.md
│       │   ├── planner.md
│       │   ├── phase1_langgraph.md
│       │   └── README.md
│       ├── storage/                # Persistence protocols + backends
│       │   ├── protocol.py         # RunStore Protocol
│       │   ├── checkpoint_protocol.py
│       │   ├── memo_protocol.py
│       │   ├── sqlite.py           # SQLite RunStore
│       │   ├── postgres.py         # Postgres RunStore
│       │   ├── mission_context_store.py
│       │   ├── artifact_store.py
│       │   ├── memory_consolidation.py
│       │   └── tool_result_cache.py
│       ├── tools/                  # Deterministic tool implementations
│       │   ├── base.py             # Tool base class
│       │   ├── output_schemas.py   # Typed tool output dicts
│       │   ├── _security.py        # Path/content guardrails
│       │   └── [35+ tool files]    # One file per tool
│       └── orchestration/
│           └── langgraph/          # Primary orchestration engine
│               ├── graph.py        # Backward-compat re-export shim (do not add logic here)
│               ├── orchestrator.py # LangGraphOrchestrator class + module constants
│               ├── state_schema.py # RunState TypedDict, new_run_state, ensure_state_defaults
│               ├── planner_helpers.py    # PlannerHelpersMixin
│               ├── planner_node.py       # PlannerNodeMixin (_plan_next_action)
│               ├── executor_node.py      # ExecutorNodeMixin (_route_to_specialist, _execute_action)
│               ├── lifecycle_nodes.py    # LifecycleNodesMixin (_finalize, policy, shims)
│               ├── provider.py           # ChatProvider Protocol + all vendor adapters
│               ├── tools_registry.py     # build_tool_registry(), MemoizeStoreTool
│               ├── context_manager.py    # ContextManager (compaction, injection, cascade)
│               ├── model_router.py       # ModelRouter (strong/fast routing)
│               ├── mission_parser.py     # parse_missions(), StructuredPlan
│               ├── mission_auditor.py    # audit_run(), AuditReport, AuditFinding
│               ├── mission_tracker.py    # Mission progress helpers
│               ├── action_parser.py      # validate_action(), parse_action_json()
│               ├── handoff.py            # TaskHandoff, HandoffResult (Pydantic)
│               ├── specialist_executor.py # build_executor_subgraph()
│               ├── specialist_evaluator.py # build_evaluator_subgraph()
│               ├── fallback_planner.py   # deterministic_fallback_action()
│               ├── policy.py             # MemoizationPolicy
│               ├── memo_manager.py       # Memo lifecycle helpers
│               ├── memo_store.py         # SQLiteMemoStore
│               ├── memo_postgres.py      # PostgresMemoStore
│               ├── checkpoint_store.py   # SQLiteCheckpointStore
│               ├── checkpoint_postgres.py # PostgresCheckpointStore
│               ├── directives.py         # Directive loading helpers
│               ├── content_validator.py  # Content safety checks
│               ├── text_extractor.py     # Pattern extraction utilities
│               ├── reviewer.py           # WeightedReviewer, FailOnlyReviewer
│               ├── run_ui.py             # Rich UI panel builders
│               ├── run.py                # CLI demo entrypoint
│               ├── run_audit.py          # Cross-run audit CLI
│               ├── user_run.py           # Interactive user CLI
│               ├── langgraph_orchestrator.py # Thin import shim
│               └── langgraph_orchestrator.py # Thin import shim
├── tests/
│   ├── conftest.py             # Shared fixtures (ScriptedProvider, etc.)
│   ├── unit/                   # Unit tests (~90 files)
│   ├── integration/            # Integration tests (ScriptedProvider, no live API)
│   ├── eval/                   # Eval harness tests
│   └── fixtures/               # SSE sequence fixtures
├── .planning/                  # GSD planning documents
│   ├── codebase/               # This directory
│   ├── phases/                 # Phase implementation plans and summaries
│   ├── research/               # Architecture research notes
│   ├── debug/                  # Debug session notes
│   └── todos/                  # Pending work items
├── docs/
│   ├── phases/                 # Phase progression documentation
│   ├── architecture/           # ADRs
│   └── WALKTHROUGH_PHASE*.md   # Operational phase walkthroughs
├── config/
│   └── local.env.example       # Ollama local config template
├── .github/
│   └── workflows/              # CI/CD pipelines
├── pyproject.toml              # Project metadata, deps, ruff, mypy, pytest config
├── Makefile                    # make run / test / lint / format / typecheck
├── .env.example                # Environment variable template
├── Shared_plan.md              # Written by _write_shared_plan() after each run
└── CLAUDE.md                   # Project instructions for Claude
```

## Directory Purposes

**`src/agentic_workflows/orchestration/langgraph/`:**
- Purpose: The entire operational orchestration engine lives here
- Contains: 35 Python modules covering graph compilation, planning, execution, state, persistence, providers, context management, auditing, specialist subgraphs, CLI and UI
- Key files: `orchestrator.py` (class), `state_schema.py` (contracts), `provider.py` (adapters), `tools_registry.py` (wiring)

**`src/agentic_workflows/tools/`:**
- Purpose: All deterministic tool implementations — one file per tool
- Contains: 35+ tools; each is a class inheriting `Tool` with `name`, `description`, and `execute(args) -> dict`
- Key files: `base.py` (base class), `_security.py` (path guardrails), `output_schemas.py` (typed results)

**`src/agentic_workflows/storage/`:**
- Purpose: Storage abstractions and backends
- Contains: Protocol definitions (runtime_checkable) + SQLite and Postgres implementations; also specialized stores for missions, artifacts, tool result caching, and memory consolidation
- Key files: `protocol.py`, `checkpoint_protocol.py`, `memo_protocol.py`

**`src/agentic_workflows/api/`:**
- Purpose: FastAPI service with SSE streaming
- Contains: Route handlers, Pydantic models, SSE event builders, HMAC stream tokens, middleware
- Key files: `routes/run.py` (primary endpoint), `sse.py`, `models.py`

**`src/agentic_workflows/directives/`:**
- Purpose: Agent role SOPs read at runtime during prompt construction
- Contains: Markdown files for supervisor, executor, evaluator, planner roles
- Key files: `supervisor.md`, `executor.md`, `evaluator.md`
- Note: Never overwrite without explicit request

**`src/agentic_workflows/core/`:**
- Purpose: Legacy P0 baseline orchestrator (pre-LangGraph)
- Status: Excluded from test coverage; do not extend; kept for reference only

**`tests/unit/`:**
- Purpose: Fast, isolated unit tests; no live API calls
- Key fixtures: `ScriptedChatProvider` from `conftest.py` drives deterministic LLM output

**`tests/integration/`:**
- Purpose: End-to-end tests using `ScriptedChatProvider` (no live API)
- Key files: `test_langgraph_flow.py`, `test_multi_mission_subgraph.py`, `test_mission_context_cascade.py`

**`.planning/`:**
- Purpose: GSD planning artifacts — phase plans, summaries, debug notes, codebase analysis
- Generated: No (human and agent maintained)
- Committed: Yes

## Key File Locations

**Entry Points:**
- `src/agentic_workflows/orchestration/langgraph/run.py`: `python -m agentic_workflows.orchestration.langgraph.run`
- `src/agentic_workflows/orchestration/langgraph/user_run.py`: Interactive user-facing CLI
- `src/agentic_workflows/orchestration/langgraph/run_audit.py`: Cross-run audit summary

**Configuration:**
- `pyproject.toml`: All tool config (ruff, mypy, pytest, coverage)
- `.env` / `.env.example`: Runtime provider config (`P1_PROVIDER`, API keys, model names)
- `config/local.env.example`: Ollama/local model template

**Core Logic:**
- `src/agentic_workflows/orchestration/langgraph/orchestrator.py`: `LangGraphOrchestrator` class definition
- `src/agentic_workflows/orchestration/langgraph/state_schema.py`: `RunState`, `new_run_state`, `ensure_state_defaults`
- `src/agentic_workflows/orchestration/langgraph/provider.py`: `ChatProvider` protocol + all vendor adapters
- `src/agentic_workflows/orchestration/langgraph/tools_registry.py`: `build_tool_registry()` — the single place that wires all tools

**Testing:**
- `tests/conftest.py`: Shared fixtures including `ScriptedChatProvider`
- `tests/unit/`: ~90 unit test files, one per module area
- `tests/integration/`: 4 integration test files

**Backward-Compat Shim:**
- `src/agentic_workflows/orchestration/langgraph/graph.py`: Re-exports from `orchestrator.py` so all existing import paths continue working; do not add logic here

## Naming Conventions

**Files:**
- Modules: `snake_case.py` — one concern per file
- Test files: `test_{module_name}.py` — mirrors the module being tested
- Mixin modules: `{concern}_node.py` or `{concern}_helpers.py` (e.g., `planner_node.py`, `lifecycle_nodes.py`)
- CLI scripts: `run.py`, `user_run.py`, `run_audit.py`

**Classes:**
- Orchestrator: `LangGraphOrchestrator` — full descriptive names
- Mixins: `{Concern}Mixin` (e.g., `PlannerNodeMixin`, `ExecutorNodeMixin`)
- Tools: `{CapitalizedName}Tool` (e.g., `WriteFileTool`, `DataAnalysisTool`)
- Protocols: `{Concern}Store` or `{Concern}Provider` (e.g., `RunStore`, `ChatProvider`)
- TypedDicts: PascalCase (e.g., `RunState`, `ToolRecord`, `MissionReport`)
- Pydantic models: PascalCase (e.g., `TaskHandoff`, `HandoffResult`)

**Functions:**
- Public graph methods: `_plan_next_action`, `_execute_action`, `_finalize` (underscore-prefixed even on public class)
- Module-level helpers: `snake_case` with underscore prefix for private helpers (e.g., `_build_port_url`, `_sequential_node`)
- Constants: `_SCREAMING_SNAKE_CASE` with leading underscore (e.g., `_PIPELINE_TRACE_CAP`, `_HANDOFF_QUEUE_CAP`)

**Directories:**
- `snake_case` throughout

## Where to Add New Code

**New Tool:**
- Implementation: `src/agentic_workflows/tools/{tool_name}.py` — subclass `Tool`, set `name`, `description`, implement `execute(args) -> dict`
- Registration: Add import + instantiation to `src/agentic_workflows/orchestration/langgraph/tools_registry.py` in `build_tool_registry()`
- Tests: `tests/unit/test_{tool_name}.py`
- Output schema (if complex): add to `src/agentic_workflows/tools/output_schemas.py`

**New API Route:**
- Implementation: `src/agentic_workflows/api/routes/{route_name}.py`
- Register router in the FastAPI app module
- Models: add request/response types to `src/agentic_workflows/api/models.py`
- Tests: `tests/unit/test_{route_name}.py` or `tests/integration/test_api_service.py`

**New Storage Backend:**
- Protocol: extend or implement `src/agentic_workflows/storage/{concern}_protocol.py`
- SQLite impl: `src/agentic_workflows/storage/sqlite.py` or new file
- Postgres impl: `src/agentic_workflows/storage/postgres.py` or new file
- Tests: `tests/unit/test_{store_name}.py`

**New Orchestrator Behavior:**
- If it belongs in planning: extend `PlannerNodeMixin` in `src/agentic_workflows/orchestration/langgraph/planner_node.py`
- If it belongs in execution: extend `ExecutorNodeMixin` in `src/agentic_workflows/orchestration/langgraph/executor_node.py`
- If it belongs in finalization/policy: extend `LifecycleNodesMixin` in `src/agentic_workflows/orchestration/langgraph/lifecycle_nodes.py`
- Prompt/helper utilities: extend `PlannerHelpersMixin` in `src/agentic_workflows/orchestration/langgraph/planner_helpers.py`
- Do NOT add logic to `src/agentic_workflows/orchestration/langgraph/graph.py`

**New State Field:**
- Add to `RunState` TypedDict in `src/agentic_workflows/orchestration/langgraph/state_schema.py`
- Add default in `new_run_state()` function
- Add `setdefault` guard in `ensure_state_defaults()`
- If it is an append-only list needing parallel safety, annotate with `Annotated[list[T], operator.add]` — it will be auto-detected by `_derive_annotated_list_fields()`

**New Agent Directive:**
- Add `src/agentic_workflows/directives/{role}.md`
- Load via `directives.py` helpers or `_read_directive_section()` from `planner_helpers.py`

## Special Directories

**`src/agentic_workflows/directives/`:**
- Purpose: Runtime-loaded agent role instruction files
- Generated: No
- Committed: Yes — never overwrite without explicit user request

**`.planning/codebase/`:**
- Purpose: GSD codebase analysis documents (this directory)
- Generated: Yes (by `/gsd:map-codebase` command)
- Committed: Yes

**`docs/`:**
- Purpose: Phase walkthroughs, ADRs, operational notes
- Generated: Partially (walkthrough files written during phase execution)
- Committed: Yes

**`workspace/`:**
- Purpose: Agent-generated output files from tool executions (write_file, etc.)
- Generated: Yes
- Committed: No (gitignored)

**`.tmp/`:**
- Purpose: Ephemeral log tails and temp files (e.g., Ollama server log)
- Generated: Yes
- Committed: No

---

*Structure analysis: 2026-03-12*
