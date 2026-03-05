# Codebase Structure

**Analysis Date:** 2026-03-05

## Directory Layout

```text
agent_phase0/
├── .claude/                 # Claude agent definitions, memories, and local skills
├── .github/                 # CI and automation workflows
├── .planning/               # Project planning, phase records, research, and codebase maps
├── .tmp/                    # Runtime SQLite databases and transient logs (ignored)
├── docs/                    # ADRs and phase walkthrough documentation
├── node_modules/            # JavaScript dependency cache for local tooling (ignored)
├── src/                     # Installable Python package source
│   └── agentic_workflows/   # Application package
├── test_outputs/            # Ephemeral test artifacts (ignored)
├── tests/                   # Unit, integration, and eval test suites
├── user_runs/               # Local CLI session artifacts and saved reviews
├── AGENTS.md                # Repo-specific working instructions
├── README.md                # Project overview and quick start
├── pyproject.toml           # Python package and tool configuration
└── .env.example             # Example environment configuration
```

## Directory Purposes

**`src/agentic_workflows/`:**
- Purpose: Main Python package.
- Contains: Application modules, entry points, directives, storage, and deterministic tools.
- Key files: `src/agentic_workflows/__init__.py`, `src/agentic_workflows/README.md`, `src/agentic_workflows/logger.py`, `src/agentic_workflows/observability.py`.
- Subdirectories: `api/`, `cli/`, `core/`, `directives/`, `orchestration/`, `storage/`, `tools/`.

**`src/agentic_workflows/api/`:**
- Purpose: FastAPI service boundary.
- Contains: `app.py`, Pydantic request/response models, SSE helpers, and route modules.
- Key files: `src/agentic_workflows/api/app.py`, `src/agentic_workflows/api/models.py`, `src/agentic_workflows/api/sse.py`.
- Subdirectories: `routes/` with `health.py`, `run.py`, and `tools.py`.

**`src/agentic_workflows/orchestration/langgraph/`:**
- Purpose: Active orchestration runtime.
- Contains: Graph compilation, planning/retry logic, mission parsing, provider adapters, reviewer/auditor logic, tool registry, and checkpoint/memo helpers.
- Key files: `src/agentic_workflows/orchestration/langgraph/graph.py`, `src/agentic_workflows/orchestration/langgraph/provider.py`, `src/agentic_workflows/orchestration/langgraph/state_schema.py`, `src/agentic_workflows/orchestration/langgraph/tools_registry.py`.
- Subdirectories: None detected below this level in the current source tree.

**`src/agentic_workflows/tools/`:**
- Purpose: Deterministic execution primitives.
- Contains: One module per tool plus supporting helpers like `src/agentic_workflows/tools/_security.py` and `src/agentic_workflows/tools/output_schemas.py`.
- Key files: `src/agentic_workflows/tools/base.py`, `src/agentic_workflows/tools/read_file.py`, `src/agentic_workflows/tools/run_bash.py`, `src/agentic_workflows/tools/query_sql.py`, `src/agentic_workflows/tools/write_file.py`.
- Subdirectories: None detected.

**`src/agentic_workflows/storage/`:**
- Purpose: Run persistence abstraction.
- Contains: Protocol and SQLite implementation for run records.
- Key files: `src/agentic_workflows/storage/protocol.py`, `src/agentic_workflows/storage/sqlite.py`.
- Subdirectories: None detected.

**`src/agentic_workflows/core/`:**
- Purpose: Legacy pre-LangGraph orchestration path kept for compatibility and comparison.
- Contains: Older orchestrator loop, provider wrapper, state helper, and demo entry point.
- Key files: `src/agentic_workflows/core/orchestrator.py`, `src/agentic_workflows/core/llm_provider.py`, `src/agentic_workflows/core/main.py`.
- Subdirectories: None detected.

**`src/agentic_workflows/directives/`:**
- Purpose: Markdown role/specification documents for supervisor, executor, evaluator, and phase-wide SOPs.
- Contains: `*.md` directive files plus `README.md`.
- Key files: `src/agentic_workflows/directives/supervisor.md`, `src/agentic_workflows/directives/executor.md`, `src/agentic_workflows/directives/evaluator.md`, `src/agentic_workflows/directives/phase1_langgraph.md`.
- Subdirectories: None detected.

**`tests/`:**
- Purpose: Automated regression coverage.
- Contains: Shared fixtures, unit tests, integration tests, and eval harness tests.
- Key files: `tests/conftest.py`, `tests/unit/test_state_schema.py`, `tests/integration/test_api_service.py`, `tests/eval/test_eval_harness.py`.
- Subdirectories: `tests/unit/`, `tests/integration/`, `tests/eval/`.

**`.planning/`:**
- Purpose: Project-management state and historical planning artifacts.
- Contains: Current project docs, research, phase directories, quick tasks, and the codebase mapping directory.
- Key files: `.planning/PROJECT.md`, `.planning/ROADMAP.md`, `.planning/STATE.md`, `.planning/config.json`.
- Subdirectories: `codebase/`, `debug/`, `phases/`, `quick/`, `research/`.

**`docs/`:**
- Purpose: Supplemental architecture and phase documentation outside the `.planning/` workflow.
- Contains: ADRs, phase walkthroughs, and architecture notes.
- Key files: `docs/ADR/ADR-001-langgraph-version-upgrade.md`, `docs/WALKTHROUGH_PHASE4.md`, `docs/architecture/PHASE_PROGRESSION.md`.
- Subdirectories: `ADR/`, `architecture/`, `phases/`.

**`.tmp/`:**
- Purpose: Local runtime databases and logs.
- Contains: `*.db`, `log.txt`, `admin_log.txt`, and analysis artifacts.
- Key files: `.tmp/run_store.db`, `.tmp/langgraph_checkpoints.db`, `.tmp/memo_store.db`.
- Subdirectories: None detected in the current scan.

**`user_runs/`:**
- Purpose: Local CLI session state and ad hoc run artifacts.
- Contains: Session context, run reports, and streamed event files.
- Key files: `user_runs/context.json`, `user_runs/graph_review.md`, `user_runs/user_run.txt`.
- Subdirectories: `events/`.

## Key File Locations

**Entry Points:**
- `src/agentic_workflows/api/app.py`: FastAPI application startup and route registration.
- `src/agentic_workflows/api/routes/run.py`: Streaming run endpoint and run-status retrieval.
- `src/agentic_workflows/cli/user_run.py`: Interactive terminal client for the FastAPI service.
- `src/agentic_workflows/orchestration/langgraph/run.py`: Direct orchestration demo entry point.
- `src/agentic_workflows/orchestration/langgraph/run_audit.py`: Audit-focused orchestration entry point.
- `src/agentic_workflows/core/main.py`: Legacy demo entry point.

**Configuration:**
- `pyproject.toml`: Package metadata, dependencies, Ruff, pytest, and mypy settings.
- `.env`: Local environment configuration. Contents were not inspected.
- `.env.example`: Example environment variables for local setup.
- `.pre-commit-config.yaml`: Developer hook configuration.
- `.github/workflows/ci.yml`: CI pipeline definition.
- `.planning/config.json`: Planning workflow configuration.

**Core Logic:**
- `src/agentic_workflows/orchestration/langgraph/graph.py`: Main graph orchestration logic.
- `src/agentic_workflows/orchestration/langgraph/provider.py`: LLM provider adapters.
- `src/agentic_workflows/orchestration/langgraph/mission_parser.py`: Structured mission extraction.
- `src/agentic_workflows/orchestration/langgraph/tools_registry.py`: Tool wiring.
- `src/agentic_workflows/storage/sqlite.py`: Run persistence backend.
- `src/agentic_workflows/tools/`: Deterministic tool implementations.

**Testing:**
- `tests/unit/`: Fine-grained unit coverage for tools and orchestration helpers.
- `tests/integration/`: End-to-end and service integration coverage.
- `tests/eval/`: Eval harness scenarios.
- `tests/conftest.py`: Shared fixtures and the scripted provider test double.

**Documentation:**
- `README.md`: Top-level project overview.
- `src/agentic_workflows/README.md`: Package/runtime architecture notes.
- `src/agentic_workflows/directives/README.md`: Directive usage guide.
- `docs/ADR/`: Architecture decision records.
- `.planning/PROJECT.md`: Current milestone-level project context.

## Naming Conventions

**Files:**
- `snake_case.py`: Standard pattern for Python modules under `src/agentic_workflows/`.
- `test_*.py`: Standard pattern for pytest modules under `tests/`.
- `UPPERCASE.md`: Project-control and high-signal docs such as `README.md`, `AGENTS.md`, `.planning/PROJECT.md`, and `.planning/STATE.md`.
- `NN-NN-PLAN.md` / `NN-NN-SUMMARY.md`: Phase-plan artifacts under `.planning/phases/`.

**Directories:**
- `snake_case`: Python package directories such as `src/agentic_workflows/orchestration/` and `src/agentic_workflows/storage/`.
- `lowercase` or dotted hidden dirs: Repo support directories such as `.planning/`, `.github/`, and `.claude/`.
- `NN-name` phase directories: Sequenced planning folders such as `.planning/phases/06-fastapi-service-layer/`.

**Special Patterns:**
- `__init__.py`: Package boundaries and re-export points throughout `src/agentic_workflows/`.
- `*_store.py`: Persistence modules such as `checkpoint_store.py` and `memo_store.py`.
- `*_review.md` and `*_events.txt`: Human review and stream artifact naming under `user_runs/`.
- `routes/*.py`: One FastAPI route group per module in `src/agentic_workflows/api/routes/`.

## Where to Add New Code

**New Feature:**
- Primary code: `src/agentic_workflows/orchestration/langgraph/` for orchestration features, or `src/agentic_workflows/api/` for service-surface features.
- Tests: `tests/unit/` for component behavior and `tests/integration/` for runtime/API behavior.
- Config if needed: `pyproject.toml`, `.env.example`, or `.planning/` docs, depending the change.

**New Component/Module:**
- Implementation: The closest package subdirectory under `src/agentic_workflows/`.
- Types: `src/agentic_workflows/api/models.py`, `src/agentic_workflows/orchestration/langgraph/state_schema.py`, or `src/agentic_workflows/storage/protocol.py`, depending boundary.
- Tests: Matching `tests/unit/test_*.py` module near the affected domain.

**New Route/Command:**
- Definition: `src/agentic_workflows/api/routes/` for HTTP routes, `src/agentic_workflows/cli/` for CLI client additions.
- Handler: `src/agentic_workflows/api/app.py` for route registration or the relevant CLI module for terminal commands.
- Tests: `tests/integration/test_api_service.py` or a new integration test module for route behavior.

**Utilities:**
- Shared helpers: `src/agentic_workflows/logger.py`, `src/agentic_workflows/observability.py`, or a focused helper module beside the owning package.
- Type definitions: `src/agentic_workflows/schemas.py` or `src/agentic_workflows/orchestration/langgraph/state_schema.py`.

## Special Directories

**`.planning/`:**
- Purpose: Long-lived planning and milestone history.
- Source: Maintained manually by the GSD workflow and repo contributors.
- Committed: Yes.

**`.tmp/`:**
- Purpose: Runtime databases, logs, and transient analysis output.
- Source: Generated by local runs and tests.
- Committed: No, ignored by `.gitignore`.

**`user_runs/events/`:**
- Purpose: Streamed run event captures from interactive sessions.
- Source: Generated by local CLI/API usage.
- Committed: No, ignored by `.gitignore`.

**`test_outputs/`:**
- Purpose: Ephemeral test artifacts.
- Source: Generated by tests or manual checks.
- Committed: No, ignored by `.gitignore` except for placeholder files already in the repo.

**`src/agentic_workflows.egg-info/`:**
- Purpose: Editable-install package metadata.
- Source: Generated by packaging tools during install/build.
- Committed: No, ignored by `.gitignore`.

**`node_modules/`:**
- Purpose: JavaScript dependency tree for local tooling support.
- Source: Generated by package manager install.
- Committed: No, ignored by `.gitignore`.

**`.ruff_cache/`:**
- Purpose: Ruff cache data.
- Source: Generated by local lint runs.
- Committed: No, ignored by `.gitignore`.

*Structure analysis: 2026-03-05*
*Update when directory structure changes*
