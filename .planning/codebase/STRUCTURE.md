# Codebase Structure

**Analysis Date:** 2026-03-12

## Directory Layout

```
agent_phase0/
├── src/
│   └── agentic_workflows/        # Main package (installed as editable)
│       ├── __init__.py
│       ├── schemas.py            # Pydantic action schemas (ToolAction, FinishAction, ClarifyAction)
│       ├── errors.py             # Exception hierarchy (AgentError, RetryableAgentError, FatalAgentError)
│       ├── logger.py             # Structured logging (get_logger, setup_dual_logging)
│       ├── observability.py      # Langfuse tracing, observe decorator, flush
│       ├── core/                 # Phase 0 baseline agent (legacy reference)
│       │   ├── main.py
│       │   ├── orchestrator.py
│       │   ├── agent_state.py
│       │   └── llm_provider.py
│       ├── agents/               # Agent variants
│       │   └── local_agent.py
│       ├── api/                  # FastAPI application
│       │   ├── app.py            # App factory, lifespan, middleware wiring
│       │   ├── models.py         # Request/response Pydantic models
│       │   ├── sse.py            # SSE streaming helpers
│       │   ├── stream_token.py
│       │   ├── routes/
│       │   │   ├── health.py
│       │   │   ├── run.py        # POST /run (SSE stream)
│       │   │   ├── runs.py       # GET /runs
│       │   │   └── tools.py      # GET /tools
│       │   └── middleware/
│       │       └── (api_key, request_id middleware)
│       ├── cli/                  # CLI interfaces
│       │   └── user_run.py
│       ├── context/              # Context/embedding support
│       │   └── embedding_provider.py
│       ├── orchestration/
│       │   └── langgraph/        # Primary orchestration engine
│       │       ├── graph.py              # Re-export shim (backward compat); do NOT add logic here
│       │       ├── orchestrator.py       # LangGraphOrchestrator class + constants (authoritative)
│       │       ├── state_schema.py       # RunState TypedDict, RunResult, new_run_state, ensure_state_defaults
│       │       ├── planner_helpers.py    # PlannerHelpersMixin: prompt builders, env helpers, timeout
│       │       ├── planner_node.py       # PlannerNodeMixin: _plan_next_action()
│       │       ├── executor_node.py      # ExecutorNodeMixin: _route_to_specialist(), _execute_action()
│       │       ├── lifecycle_nodes.py    # LifecycleNodesMixin: _finalize(), _enforce_memo_policy()
│       │       ├── provider.py           # ChatProvider Protocol + all provider implementations
│       │       ├── context_manager.py    # ContextManager, MissionContext, ArtifactRecord
│       │       ├── mission_parser.py     # StructuredPlan, parse_missions(), IntentClassification
│       │       ├── mission_auditor.py    # audit_run(), AuditReport, AuditFinding
│       │       ├── mission_tracker.py    # MissionReport update helpers
│       │       ├── model_router.py       # ModelRouter, RoutingSignals
│       │       ├── action_parser.py      # validate_action(), parse_action_json()
│       │       ├── handoff.py            # TaskHandoff, HandoffResult, create_handoff()
│       │       ├── specialist_executor.py # ExecutorState subgraph (build_executor_subgraph)
│       │       ├── specialist_evaluator.py # Evaluator subgraph (build_evaluator_subgraph)
│       │       ├── tools_registry.py     # build_tool_registry() -> dict[str, Tool]
│       │       ├── checkpoint_store.py   # SQLiteCheckpointStore
│       │       ├── checkpoint_postgres.py # PostgresCheckpointStore
│       │       ├── memo_store.py         # SQLiteMemoStore
│       │       ├── memo_postgres.py      # PostgresMemoStore
│       │       ├── memo_manager.py       # Memo lookup/write helpers
│       │       ├── policy.py             # MemoizationPolicy
│       │       ├── fallback_planner.py   # Deterministic fallback actions (timeout mode)
│       │       ├── content_validator.py  # Pre-execution content validation
│       │       ├── directives.py         # Directive loading helpers
│       │       ├── text_extractor.py     # Text extraction utilities
│       │       ├── reviewer.py           # FailOnlyReviewer, WeightedReviewer
│       │       ├── run.py                # CLI demo entrypoint
│       │       ├── run_audit.py          # CLI cross-run audit entrypoint
│       │       ├── run_ui.py             # Audit panel / rich UI helpers
│       │       ├── user_run.py           # User-driven run entrypoint
│       │       └── langgraph_orchestrator.py  # Thin alias re-export for backward compat
│       ├── storage/              # Persistence backends
│       │   ├── sqlite.py         # SQLiteRunStore (WAL mode)
│       │   ├── postgres.py       # PostgresRunStore
│       │   ├── artifact_store.py # ArtifactStore (run artifact persistence)
│       │   ├── mission_context_store.py  # Cross-run mission context (Postgres)
│       │   ├── tool_result_cache.py      # Deterministic tool result cache
│       │   ├── memory_consolidation.py   # Memory consolidation (Phase 7.9)
│       │   ├── checkpoint_protocol.py    # CheckpointStore protocol
│       │   └── memo_protocol.py          # MemoStore protocol
│       ├── tools/                # 40+ deterministic tool implementations
│       │   ├── base.py           # Tool base class (execute, args_schema, required_args)
│       │   ├── _security.py      # Security guardrails for tool execution
│       │   ├── output_schemas.py # Shared output schema helpers
│       │   └── (one file per tool: write_file.py, read_file.py, data_analysis.py, etc.)
│       └── directives/           # Specialist SOPs and instruction templates
│           ├── supervisor.md
│           ├── executor.md
│           ├── evaluator.md
│           ├── planner.md
│           └── phase1_langgraph.md
├── tests/
│   ├── conftest.py               # Shared fixtures (ScriptedProvider, orchestrator factories)
│   ├── unit/                     # Unit tests (no live API)
│   ├── integration/              # Integration tests (ScriptedProvider scripted responses)
│   ├── eval/                     # Evaluation tests
│   └── fixtures/                 # Test data, SSE sequences
│       └── sse_sequences/
├── config/
│   └── local.env.example         # Ollama local config template
├── db/
│   └── migrations/               # Database migration scripts
├── storage/
│   └── migrations/               # Storage-layer migration scripts
├── docker/                       # Docker-related configs
├── docs/
│   ├── ADR/                      # Architecture decision records
│   ├── architecture/             # Architectural diagrams and docs
│   └── phases/                   # Phase progression documentation
├── scripts/                      # Utility scripts
├── .planning/                    # GSD planning artifacts (not shipped)
│   ├── codebase/                 # Codebase map documents (this directory)
│   ├── phases/                   # Implementation phase plans
│   └── debug/                    # Debug investigations
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── Makefile
├── CLAUDE.md                     # Claude project instructions
├── AGENTS.md                     # Universal coding conventions
└── Shared_plan.md                # Auto-written structured plan (last run)
```

## Directory Purposes

**`src/agentic_workflows/orchestration/langgraph/`:**
- Purpose: The entire LangGraph orchestration engine lives here
- Contains: Graph compilation, all node mixins, provider adapters, context management, mission parsing/auditing, specialist subgraphs, storage adapters, policy enforcement
- Key files: `orchestrator.py` (authoritative class), `state_schema.py` (state contract), `provider.py` (all LLM adapters), `context_manager.py` (message lifecycle), `graph.py` (backward-compat re-export shim only)

**`src/agentic_workflows/tools/`:**
- Purpose: All tool implementations (deterministic, no LLM calls)
- Contains: One `.py` file per tool; `base.py` defines the `Tool` base class; `tools_registry.py` assembles the full registry; `_security.py` provides sandboxing for bash/file tools
- Key files: `base.py`, `write_file.py`, `read_file.py`, `data_analysis.py`, `math_stats.py`, `run_bash.py`, `memoize.py`

**`src/agentic_workflows/storage/`:**
- Purpose: Persistence protocols and implementations
- Contains: Protocol interfaces (`checkpoint_protocol.py`, `memo_protocol.py`) and SQLite/Postgres implementations; also artifact store, tool result cache, memory consolidation

**`src/agentic_workflows/api/`:**
- Purpose: HTTP interface via FastAPI
- Contains: App factory with lifespan, four route modules, middleware, SSE streaming, Pydantic request/response models

**`src/agentic_workflows/directives/`:**
- Purpose: Markdown instruction files loaded at runtime by `directives.py` into system prompts
- Contains: `supervisor.md`, `executor.md`, `evaluator.md`, `planner.md`, `phase1_langgraph.md`
- Note: Never overwrite without explicit user request (per CLAUDE.md)

**`tests/`:**
- Purpose: Full test suite (657 passing)
- Contains: `unit/` (no live API, mock providers), `integration/` (ScriptedProvider with pre-scripted LLM responses), `eval/` (evaluation harness), `fixtures/` (shared test data)

**`.planning/`:**
- Purpose: GSD planning artifacts
- Generated: No (checked in)
- Committed: Yes — planning docs committed alongside code

## Key File Locations

**Entry Points:**
- `src/agentic_workflows/orchestration/langgraph/run.py`: CLI demo (`python -m agentic_workflows.orchestration.langgraph.run`)
- `src/agentic_workflows/orchestration/langgraph/run_audit.py`: CLI audit (`python -m agentic_workflows.orchestration.langgraph.run_audit`)
- `src/agentic_workflows/api/app.py`: FastAPI application
- `src/agentic_workflows/core/main.py`: Phase 0 legacy demo (not production)

**Configuration:**
- `pyproject.toml`: Package definition, dependencies, tool config (ruff, mypy, pytest)
- `Makefile`: `run`, `test`, `lint`, `format`, `typecheck` targets
- `.env` (not committed): Provider keys and runtime config (see `.env.example`)
- `config/local.env.example`: Ollama/local model config template

**Core Logic:**
- `src/agentic_workflows/orchestration/langgraph/orchestrator.py`: LangGraphOrchestrator class (authoritative)
- `src/agentic_workflows/orchestration/langgraph/state_schema.py`: RunState, RunResult, new_run_state
- `src/agentic_workflows/orchestration/langgraph/planner_node.py`: `_plan_next_action()` — the planning loop
- `src/agentic_workflows/orchestration/langgraph/executor_node.py`: `_execute_action()` — tool dispatch
- `src/agentic_workflows/orchestration/langgraph/provider.py`: All LLM provider implementations
- `src/agentic_workflows/orchestration/langgraph/context_manager.py`: Message lifecycle management

**Testing:**
- `tests/conftest.py`: Shared fixtures including `ScriptedProvider` and orchestrator factories
- `tests/unit/`: One test file per module (naming: `test_<module_name>.py`)
- `tests/integration/test_langgraph_flow.py`: End-to-end flow tests

## Naming Conventions

**Files:**
- Snake case: `mission_parser.py`, `context_manager.py`, `state_schema.py`
- Mixin modules named by role: `planner_node.py`, `executor_node.py`, `lifecycle_nodes.py`, `planner_helpers.py`
- Provider-specific: `checkpoint_postgres.py`, `memo_postgres.py`
- Test files: `test_<module>.py` mirroring source module names

**Directories:**
- Snake case: `agentic_workflows`, `langgraph`, `tools`, `storage`
- Flat within `tools/` (no subdirectories)

**Classes:**
- PascalCase: `LangGraphOrchestrator`, `RunState`, `ToolRecord`, `MissionReport`
- Mixin suffix: `PlannerHelpersMixin`, `ExecutorNodeMixin`, `LifecycleNodesMixin`
- Tool suffix: `WriteFileTool`, `DataAnalysisTool`, `MathStatsTool`
- Store suffix: `SQLiteCheckpointStore`, `PostgresMemoStore`, `SQLiteRunStore`

**Functions and methods:**
- Public: snake_case (`run`, `prepare_state`, `build_tool_registry`)
- Private/internal: leading underscore (`_plan_next_action`, `_execute_action`, `_finalize`)
- Module-level private constants: leading underscore + CAPS (`_PIPELINE_TRACE_CAP`, `_ANNOTATED_LIST_FIELDS`)

## Where to Add New Code

**New Tool:**
- Implementation: `src/agentic_workflows/tools/<tool_name>.py` — subclass `Tool`, set `name`, `description`, `_args_schema`, implement `execute(args) -> dict`
- Registration: add import and instantiation to `src/agentic_workflows/orchestration/langgraph/tools_registry.py` in `build_tool_registry()`
- Tests: `tests/unit/test_<tool_name>.py`

**New Provider:**
- Implementation: `src/agentic_workflows/orchestration/langgraph/provider.py` — implement the `ChatProvider` Protocol (`generate`, `context_size`)
- Registration: update `build_provider()` factory in `provider.py`

**New API Route:**
- Implementation: `src/agentic_workflows/api/routes/<route_name>.py`
- Registration: import and include router in `src/agentic_workflows/api/app.py`

**New Storage Backend:**
- Protocol: extend `src/agentic_workflows/storage/checkpoint_protocol.py` or `memo_protocol.py`
- Implementation: `src/agentic_workflows/storage/<backend_name>.py`

**New Orchestrator Functionality:**
- Add to the appropriate mixin: planning logic → `planner_node.py` or `planner_helpers.py`; execution logic → `executor_node.py`; lifecycle/finalize logic → `lifecycle_nodes.py`
- Do NOT add logic to `graph.py` (shim only)

**New Directive:**
- Add markdown file to `src/agentic_workflows/directives/`
- Load via `directives.py` helpers in orchestration layer

**New Tests:**
- Unit tests: `tests/unit/test_<module>.py`
- Integration tests: `tests/integration/test_<feature>.py` — use `ScriptedProvider` from `tests/conftest.py` for deterministic LLM scripting

## Special Directories

**`src/agentic_workflows.egg-info/`:**
- Purpose: Editable install metadata
- Generated: Yes (by `pip install -e`)
- Committed: No

**`workspace/agent_files/`:**
- Purpose: Runtime file output directory for `write_file` and `file_manager` tools
- Generated: Yes (by tool execution)
- Committed: No (runtime artifacts)

**`user_runs/`:**
- Purpose: Persisted user run data and events
- Generated: Yes
- Committed: No (runtime data)

**`test_outputs/`:**
- Purpose: Test run output files
- Generated: Yes
- Committed: No

**`db/migrations/` and `storage/migrations/`:**
- Purpose: SQL migration scripts for schema evolution
- Generated: No (hand-authored)
- Committed: Yes

**`.planning/`:**
- Purpose: GSD planning artifacts (phase plans, codebase maps, debug notes)
- Generated: Partially (by GSD commands)
- Committed: Yes

---

*Structure analysis: 2026-03-12*
