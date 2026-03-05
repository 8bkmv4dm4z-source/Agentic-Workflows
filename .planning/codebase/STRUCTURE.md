# Codebase Structure

**Analysis Date:** 2026-03-05

## Directory Layout

```text
agent_phase0/
├── .github/                 # CI workflow definitions
├── .planning/               # Project planning state, roadmap, and codebase maps
├── .tmp/                    # Runtime SQLite DBs, logs, and transient artifacts
├── docs/                    # ADRs, architecture notes, and phase walkthroughs
├── src/                     # Python package source and packaging metadata
├── tests/                   # Unit, integration, and eval test suites
├── user_runs/               # Local CLI session context and run artifacts
├── test_outputs/            # Ephemeral test output directory
├── AGENTS.md                # Repo-specific agent instructions
├── Makefile                 # Developer shortcuts
├── README.md                # Project overview
└── pyproject.toml           # Build metadata, dependencies, and tool config
```

## Directory Purposes

**.planning/:**
- Purpose: Working project-management area used by the GSD workflow.
- Contains: `PROJECT.md`, `ROADMAP.md`, `STATE.md`, phase plans, research docs,
  and generated codebase map files.
- Key files: `.planning/STATE.md`, `.planning/PROJECT.md`,
  `.planning/ROADMAP.md`.
- Subdirectories: `.planning/codebase/`, `.planning/phases/`,
  `.planning/research/`, `.planning/debug/`, `.planning/quick/`.

**src/agentic_workflows/:**
- Purpose: Main Python package.
- Contains: Runtime modules, API code, orchestration code, tools, storage, and
  package-level docs.
- Key files: `src/agentic_workflows/README.md`, `src/agentic_workflows/logger.py`,
  `src/agentic_workflows/observability.py`, `src/agentic_workflows/schemas.py`.
- Subdirectories: `api/`, `cli/`, `core/`, `directives/`,
  `orchestration/`, `storage/`, `tools/`.

**src/agentic_workflows/api/:**
- Purpose: FastAPI service surface for production-style execution.
- Contains: `app.py`, `models.py`, SSE helpers, stream-token helpers, routes,
  and middleware.
- Key files: `src/agentic_workflows/api/app.py`,
  `src/agentic_workflows/api/models.py`,
  `src/agentic_workflows/api/routes/run.py`.
- Subdirectories: `middleware/`, `routes/`.

**src/agentic_workflows/orchestration/langgraph/:**
- Purpose: Current orchestration runtime and its support modules.
- Contains: Graph wiring, state schema, provider adapters, policy logic, mission
  parsing/audit, reviewer helpers, and direct CLI runners.
- Key files: `src/agentic_workflows/orchestration/langgraph/graph.py`,
  `src/agentic_workflows/orchestration/langgraph/state_schema.py`,
  `src/agentic_workflows/orchestration/langgraph/provider.py`,
  `src/agentic_workflows/orchestration/langgraph/run.py`.
- Subdirectories: Not applicable.

**src/agentic_workflows/tools/:**
- Purpose: Deterministic execution modules used by the orchestrator.
- Contains: Tool classes such as file operations, shell execution, search,
  parsing, text analysis, and memo helpers.
- Key files: `src/agentic_workflows/tools/base.py`,
  `src/agentic_workflows/tools/read_file.py`,
  `src/agentic_workflows/tools/write_file.py`,
  `src/agentic_workflows/tools/run_bash.py`.
- Subdirectories: Not detected.

**src/agentic_workflows/storage/:**
- Purpose: Run persistence abstractions for the service layer.
- Contains: `Protocol` definitions and SQLite implementation.
- Key files: `src/agentic_workflows/storage/protocol.py`,
  `src/agentic_workflows/storage/sqlite.py`.
- Subdirectories: Not detected.

**src/agentic_workflows/directives/:**
- Purpose: Markdown SOP contracts for supervisor/executor/evaluator behavior.
- Contains: `*.md` directive files and a README.
- Key files: `src/agentic_workflows/directives/README.md`,
  `src/agentic_workflows/directives/supervisor.md`,
  `src/agentic_workflows/directives/executor.md`.
- Subdirectories: Not detected.

**src/agentic_workflows/core/:**
- Purpose: Legacy Phase 0 baseline orchestrator kept for comparison.
- Contains: Older orchestrator/runtime modules.
- Key files: `src/agentic_workflows/core/orchestrator.py`,
  `src/agentic_workflows/core/llm_provider.py`,
  `src/agentic_workflows/core/main.py`.
- Subdirectories: Not detected.

**tests/:**
- Purpose: Regression coverage for the package.
- Contains: Pytest suites, shared fixtures, and eval scenarios.
- Key files: `tests/conftest.py`, `tests/integration/test_api_service.py`,
  `tests/unit/test_run_store.py`, `tests/eval/test_eval_harness.py`.
- Subdirectories: `tests/unit/`, `tests/integration/`, `tests/eval/`.

**docs/:**
- Purpose: Human-facing design and phase documentation.
- Contains: ADRs, architecture notes, and phase walkthroughs.
- Key files: `docs/ADR/ADR-001-langgraph-version-upgrade.md`,
  `docs/architecture/PHASE_PROGRESSION.md`,
  `docs/phases/PHASE_4_PRODUCTION.md`.
- Subdirectories: `docs/ADR/`, `docs/architecture/`, `docs/phases/`.

**user_runs/:**
- Purpose: Local artifacts from interactive API-backed sessions.
- Contains: Conversation context, reports, reviews, and streaming-event output.
- Key files: `user_runs/context.json`, `user_runs/report.txt`,
  `user_runs/user_run_review.md`.
- Subdirectories: `user_runs/events/`.

## Key File Locations

**Entry Points:**
- `src/agentic_workflows/api/app.py`: FastAPI app startup and route registration.
- `src/agentic_workflows/cli/user_run.py`: Interactive CLI that talks to the API.
- `src/agentic_workflows/orchestration/langgraph/run.py`: Direct graph demo CLI.
- `src/agentic_workflows/orchestration/langgraph/run_audit.py`: Historical run
  audit/export CLI.
- `src/agentic_workflows/core/main.py`: Legacy Phase 0 demo entry.

**Configuration:**
- `pyproject.toml`: Package metadata, dependencies, Ruff, pytest, and mypy config.
- `Makefile`: Common local commands.
- `.gitignore`: Ignored runtime artifacts, caches, databases, and local env files.
- `.env`: Local environment configuration for providers and API keys; present,
  contents not inspected.

**Core Logic:**
- `src/agentic_workflows/orchestration/langgraph/graph.py`: Main orchestration
  runtime.
- `src/agentic_workflows/orchestration/langgraph/tools_registry.py`: Tool map
  construction.
- `src/agentic_workflows/orchestration/langgraph/state_schema.py`: Canonical
  run-state shape.
- `src/agentic_workflows/api/routes/`: HTTP/SSE routes for service execution.
- `src/agentic_workflows/tools/`: Deterministic tool implementations.
- `src/agentic_workflows/storage/sqlite.py`: Service run persistence backend.

**Testing:**
- `tests/unit/`: Unit-level behavior checks for tools, orchestration helpers, and
  storage modules.
- `tests/integration/`: Graph and API integration scenarios.
- `tests/eval/`: Eval-harness tests for higher-level behavior.
- `tests/conftest.py`: Shared fixtures including `ScriptedProvider`,
  temp stores, and temp directories.

**Documentation:**
- `README.md`: Project overview and quick start.
- `src/agentic_workflows/README.md`: Package/runtime architecture notes.
- `src/agentic_workflows/directives/README.md`: Directive usage guide.
- `docs/ADR/`: Architectural decision records.
- `.planning/`: Live planning and implementation state for the project.

## Naming Conventions

**Files:**
- `snake_case.py`: Standard Python module naming, for example
  `src/agentic_workflows/api/stream_token.py`.
- `test_*.py`: Pytest modules, for example `tests/unit/test_tool_security.py`.
- `UPPERCASE.md`: High-signal repo or planning docs such as `AGENTS.md`,
  `README.md`, and `.planning/STATE.md`.
- `ADR-###-*.md`: Architecture decision records in `docs/ADR/`.

**Directories:**
- `snake_case` or simple lowercase package names under `src/agentic_workflows/`,
  such as `storage/`, `tools/`, and `directives/`.
- Plural collection directories where content is grouped, such as `tests/`,
  `docs/`, `routes/`, and `phases/`.
- Dot-prefixed workspace directories for local state, such as `.planning/` and
  `.tmp/`.

**Special Patterns:**
- `__init__.py`: Package boundaries and limited re-export surfaces.
- `README.md` inside subdirectories: Localized package guidance, for example
  `src/agentic_workflows/README.md`.
- `run*.py`: CLI or operational runner modules in
  `src/agentic_workflows/orchestration/langgraph/`.

## Where to Add New Code

**New Tool:**
- Primary code: `src/agentic_workflows/tools/`.
- Registration: `src/agentic_workflows/orchestration/langgraph/tools_registry.py`.
- Tests: `tests/unit/test_<tool_name>.py`.

**New Orchestration Behavior:**
- Primary code: `src/agentic_workflows/orchestration/langgraph/`.
- Contract updates: `src/agentic_workflows/directives/`.
- Tests: `tests/unit/` for helpers plus `tests/integration/` for graph behavior.

**New API Route or Service Endpoint:**
- Definition: `src/agentic_workflows/api/routes/`.
- Models/middleware: `src/agentic_workflows/api/models.py` and
  `src/agentic_workflows/api/middleware/`.
- Tests: `tests/integration/`, usually alongside
  `tests/integration/test_api_service.py`.

**New Storage Backend or Persistence Change:**
- Implementation: `src/agentic_workflows/storage/`.
- Orchestrator touchpoints: `src/agentic_workflows/api/app.py` and
  `src/agentic_workflows/api/routes/`.
- Tests: `tests/unit/test_run_store.py` plus integration coverage where needed.

**Shared Utilities or Package-Level Helpers:**
- Shared helpers: `src/agentic_workflows/`.
- Typed runtime contracts: `src/agentic_workflows/orchestration/langgraph/state_schema.py`,
  `src/agentic_workflows/storage/protocol.py`, or `src/agentic_workflows/schemas.py`.
- Tests: `tests/unit/`.

## Special Directories

**.planning/:**
- Purpose: Human and agent planning workspace.
- Source: Maintained directly in-repo by the GSD workflow.
- Committed: Yes.

**.tmp/:**
- Purpose: Runtime DBs, logs, and temporary exports such as
  `.tmp/run_store.db`, `.tmp/memo_store.db`, and `.tmp/langgraph_checkpoints.db`.
- Source: Generated by the application and CLI tooling.
- Committed: No (`.gitignore`).

**user_runs/events/:**
- Purpose: Streaming/session event output for local runs.
- Source: Generated during interactive usage.
- Committed: No (`.gitignore`).

**test_outputs/:**
- Purpose: Ad hoc or temporary test artifacts.
- Source: Generated by local test workflows.
- Committed: No (`.gitignore`).

**src/agentic_workflows.egg-info/:**
- Purpose: Packaging metadata from editable installs/builds.
- Source: Generated by Python packaging tools.
- Committed: No (`*.egg-info/` in `.gitignore`).

**node_modules/:**
- Purpose: Local JavaScript dependency tree for workspace tooling.
- Source: Installed locally; `package.json`: Not detected.
- Committed: No (`node_modules/` in `.gitignore`).

---

*Structure analysis: 2026-03-05*
*Update when directory structure changes*
