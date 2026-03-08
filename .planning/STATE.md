---
gsd_state_version: 1.0
milestone: v1.5
milestone_name: milestone
status: completed
stopped_at: Completed 07.4-03-PLAN.md
last_updated: "2026-03-08T21:56:56.683Z"
last_activity: 2026-03-08 — Wave 3 final improvements (P1_BASH_ENABLED guard, memoize prompt removal, tool contract tests)
progress:
  total_phases: 12
  completed_phases: 10
  total_plans: 45
  completed_plans: 46
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-02)

**Core value:** A specialist-routing multi-agent system that reliably executes multi-mission workloads end-to-end — with the architecture understood deeply enough to stress test, evolve, and deploy with confidence.
**Current focus:** Phase 7.2 — Architecture Review Implementation: Critical Bug Fixes and Systemic Hardening

## Current Position

Phase: 7.2 (Architecture Review Implementation: Critical Bug Fixes and Systemic Hardening)
Plan: 5 of 5 in current phase (07.2-00, 07.2-01, 07.2-02, 07.2-03, 07.2-04 DONE; 07.2-05 pending)
Status: Plan 04 complete — Wave 3 final improvements (P1_BASH_ENABLED guard, memoize prompt removal, 144 tool contract tests).
Last activity: 2026-03-08 — Wave 3 final improvements (P1_BASH_ENABLED guard, memoize prompt removal, tool contract tests)

Progress: [██████████] 100% (32/32 plans complete, Phase 7.2 05/05 done)

## Test Status

- **823 unit+integration tests pass** (all passing, 0 failures); 144 tool contract stubs replaced with real assertions in Plan 04
- 0 pre-existing test_tool_contracts failures (stubs replaced); 0 test_tool_security failures (P1_BASH_ENABLED added)
- ruff check: clean on all modified files (pre-existing UP035 in app.py, B039 in graph.py, I001/B009 in test_run_helpers.py noted)
- Branch: `phase-7.2-arch-review`

## Performance Metrics

**Velocity:**
- Total plans completed: 18 (across Phases 2-6)
- Average duration: 4 min
- Total execution time: ~1 hour 11 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 02-langgraph-upgrade | 5 | 20 min | 4 min |
| 03-specialist-subgraph | 3 | 7 min | 2 min |
| 04-multi-agent-integration | 6 | 30 min | 5 min |
| 05-observability | 2 | ~10 min | 5 min |
| 06-fastapi-service-layer | 3/3 | 16 min | 5 min |
| 07-production-persistence-and-ci | 4/4 | 26 min | 7 min |
| Phase 07.1 P02 | 5min | 2 tasks | 5 files |
| Phase 07.1 P04 | 4min | 2 tasks | 6 files |
| Phase 07.2 P00 | 1min | 1 task | 1 file |
| Phase 07.2 P01 | 4min | 3 tasks | 4 files |
| Phase 07.2 P02 | 6min | 3 tasks | 6 files |
| Phase 07.2 P03 | 5min | 2 tasks | 4 files |
| Phase 07.2 P04 | 4min | 4 tasks | 6 files |
| Phase 07.2 P05 | 2min | 2 tasks | 3 files |
| Phase 07.2 P06 | 1min | ruff fix + context tooling | 5 files |
| Phase 07.3 P00 | 2min | 2 tasks | 4 files |
| Phase 07.3 P01 | 78s | 2 tasks | 3 files |
| Phase 07.3 P02 | 2min | 2 tasks | 3 files |
| Phase 07.3 P03 | 3 | 1 tasks | 1 files |
| Phase 07.3 P04 | 1 | 1 tasks | 1 files |
| Phase 07.3 P08 | 3min | 2 tasks | 3 files |
| Phase 07.3 P05 | 2min | 2 tasks | 2 files |
| Phase 07.3 P06 | 3 | 1 tasks | 2 files |
| Phase 07.3 P07 | 4min | 1 tasks | 2 files |
| Phase 07.3 P09 | 4 | 1 tasks | 1 files |
| Phase 07.4-01 P01 | 4min | 2 tasks | 2 files |
| Phase 07.4 P04 | 2min | 2 tasks | 1 files |
| Phase 07.4 P02 | 5min | 2 tasks | 2 files |
| Phase 07.4 P03 | 2min | 2 tasks | 2 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Phase 05]: Langfuse 3.x get_langfuse_callback_handler() wired into graph.py run() — callbacks passed to _active_callbacks list
- [Phase 05]: user_run.py interactive session loop with prior_context, reviewer integration, and turn-based conversation
- [Phase 05-fix]: Prior-context system messages merged into main system prompt (not inserted as consecutive system messages) — prevents Ollama JSON mode breakage
- [Phase 05-fix]: Retry/escalation hints changed from role="system" to role="user" with [Orchestrator] prefix — avoids consecutive system messages
- [Phase 05-fix]: Empty-output fallback always uses "clarify" action, never "I cannot answer" finish — user-interactive sessions should never refuse engagement
- [Phase 05-fix]: infer_requirements_from_text() expanded with tightened patterns for parse_code_structure, read_file, run_bash, search_files, http_request, hash_content, datetime_ops
- [Phase 04-03]: fast_provider=None defaults to strong_provider via ModelRouter fallback
- [Phase 04-01]: Subgraphs cached in __init__() after build_tool_registry()
- [Phase 04-05]: Parallel-invoke pattern for subgraph invocation
- [Phase 06-01]: RunStore uses typing.Protocol (not ABC) for structural subtyping with future Postgres backend
- [Phase 06-01]: SQLite sync calls wrapped in anyio.to_thread.run_sync for event-loop safety
- [Phase 06-01]: pytest asyncio_mode=auto configured globally
- [Phase 06-02]: Used _compiled.stream(stream_mode="updates") directly for real-time SSE (not wrapping run())
- [Phase 06-02]: anyio memory object stream bridges sync graph thread to async SSE via anyio.from_thread.run
- [Phase 06-02]: Test apps bypass lifespan (httpx ASGITransport does not trigger ASGI lifespan events)
- [Phase 06-03]: CLI user_run talks to FastAPI via httpx, not orchestrator directly -- single source of truth
- [Phase 06-03]: Final state retrieved from checkpoint_store.load_latest() instead of stream chunk accumulation -- avoids _sequential_node annotated list zeroing
- [Phase 06-03]: Old user_run.py kept with deprecation warning for backward compatibility
- [Phase 07-01]: psycopg[binary] + psycopg_pool instead of asyncpg -- AsyncPostgresSaver API incompatible with project's CheckpointStore interface
- [Phase 07-01]: Sync ConnectionPool shared across all 3 Postgres stores -- CheckpointStore/MemoStore called synchronously from graph nodes
- [Phase 07-01]: Lazy conditional imports in app.py lifespan -- Postgres imports only when DATABASE_URL set
- [Phase 07-01]: autocommit=True and prepare_threshold=0 in pool kwargs per RESEARCH.md pitfall findings
- [Phase 07-02]: pytest.importorskip("psycopg_pool") at module level for Postgres test files -- prevents collection errors in SQLite-only CI
- [Phase 07-02]: Session-scoped pg_pool fixture with per-test TRUNCATE via clean_pg -- one pool per session, deterministic isolation
- [Phase 07-02]: Store factory tests verify ENV detection logic only, not Postgres connections -- runs in all CI matrices
- [Phase 07-03]: Single-stage Docker build (python:3.12-slim) -- psycopg[binary] bundles libpq, no multi-stage needed
- [Phase 07-03]: Port 5433:5432 for local docker-compose -- Docker Desktop + WSL2 port binding conflict on 5432
- [Phase 07-03]: Coverage enforced only in CI (--cov-fail-under=80), not in default pytest addopts
- [Phase 07-03]: CI matrix: sqlite leg runs lint+typecheck+test, postgres leg runs init+test
- [Phase 07]: WALKTHROUGH_PHASE7.md follows learning-driven tone with Docker concepts for newcomers, psycopg rationale, and store factory pattern explanation
- [Phase 07.1]: Store MissionContext as model_dump() dicts in RunState for checkpointer serialization safety
- [Phase 07.1]: String keys str(mission_id) in mission_contexts for JSON serialization compatibility
- [Phase 07.1]: No custom reducer on mission_contexts -- plain dict replacement for sequential execution
- [Phase 07.1]: Reuse MissionContext.build_summary() for specialist prior_results_summary -- one abstraction, tested once
- [Phase 07.1]: Fallback to state["missions"] list when mission_contexts entry missing for specialist goal lookup
- [Phase 07.1]: All eviction injected messages use role=user with [Orchestrator] prefix, never role=system
- [Phase 07.1]: ContextManager is single source of truth for message lifecycle -- removed competing compaction from ensure_state_defaults
- [Phase 07.1]: ContextManager lifecycle calls wrapped in try/except for graceful degradation
- [Phase 07.2]: Module-level _build_all_tools() with in-memory stores for parametrized test scaffold
- [Phase 07.2]: Removed _executor_subgraph.invoke() from _route_to_specialist -- eliminated dual tool execution side effects
- [Phase 07.2]: _active_callbacks_var ContextVar at module level replaces self._active_callbacks instance field -- thread-isolated Langfuse callbacks
- [Phase 07.2]: SSE streaming path (routes/run.py) uses _active_callbacks_var.set() not orchestrator._active_callbacks mutation
- [Phase 07.2]: SQLiteCheckpointStore persistent connection + WAL mode — matches SQLiteRunStore pattern
- [Phase 07.2]: seen_tool_signatures as set[str] with list-to-set conversion in ensure_state_defaults for checkpoint safety
- [Phase 07.2]: Local _PIPELINE_TRACE_CAP in context_manager.py to avoid circular import with graph.py
- [Phase 07.2]: Cap constants at module level (_PIPELINE_TRACE_CAP=500, _HANDOFF_QUEUE_CAP=50, _HANDOFF_RESULTS_CAP=50)
- [Phase 07.2]: Auto-derive _ANNOTATED_LIST_FIELDS via typing.get_type_hints(RunState, include_extras=True) at import time
- [Phase 07.2]: prepare_state() public method on LangGraphOrchestrator as single source of truth for state initialization
- [Phase 07.2]: Callback setup (ContextVar) remains in callers since it is per-request, not per-state
- [Phase 07.2]: P1_BASH_ENABLED guard uses != 'true' pattern (ruff SIM201 compliant) at top of run_bash.execute()
- [Phase 07.2]: Memoize tool kept in registry for internal auto-memoize use, only removed from planner prompt's tool arg reference
- [Phase 07.2]: Tool contract test accepts KeyError/ValueError/TypeError as valid responses to empty args
- [Phase 07.2-05]: _build_system_prompt() uses AGENT_ROOT for readable context and AGENT_WORKDIR for write workspace; shown separately in prompt when they differ
- [Phase 07.2-05]: update_file_section.py adds AGENT_WORKDIR fallback after P1_RUN_ARTIFACT_DIR (matches write_file.py pattern)
- [Phase 07.2-06]: read_file_chunk tool (150-line chunks, has_more/next_offset) added for context-safe large file processing
- [Phase 07.2-06]: outline_code (renamed from parse_code_structure) caps results at 30 items per category with truncation hint
- [Phase 07.2-06]: Context management rules added to system prompt and executor.md directive
- [Phase 07.2-06]: _active_callbacks_var ContextVar default=[] removed (B039); .get([]) used at call sites — ruff now fully clean
- [Phase 07.2-06]: E741 ambiguous variable l renamed to line in _build_codebase_context — ruff now fully clean
- [Phase 07.2-06]: Phase 7.2 merged to main; all 839 tests passing, ruff clean
- [Phase 07.3]: All 3 new test stubs fail at collection time (ImportError) — correct RED state before Wave 1B/2A implementations
- [Phase 07.3]: clean_pg fixture extended with per-table try/except for mission_contexts/mission_artifacts — graceful before migrations 003/004
- [Phase 07.3]: vector(384) dimension matches BAAI/bge-small-en-v1.5 — all three tables updated
- [Phase 07.3]: HNSW index chosen for mission_contexts.embedding over IVFFlat — no training needed on empty table
- [Phase 07.3]: DO migration guard uses USING NULL::vector(384) — safe because file_chunks/solved_tasks columns never written
- [Phase 07.3]: SHA-256 seed into random.Random for MockEmbeddingProvider — deterministic unit-norm 384-dim vectors, CI-safe
- [Phase 07.3]: fastembed import deferred to FastEmbedProvider.__init__ body — context package importable in CI without optional dep
- [Phase 07.3]: fastembed placed in [context] optional dep group (not [dev]) — production opt-in without polluting base install
- [Phase 07.3]: encode_tool_pattern uses TOOL_BITS dict with append-only policy — preserves existing bitmask encodings when new tools added
- [Phase 07.3]: pool=None no-op on both upsert and query_cascade — MissionContextStore safe to instantiate without live DB
- [Phase 07.3]: ArtifactStore search() double-layer degradation: pool=None and exception-catch both return [] for graceful Postgres failure handling
- [Phase 07.3]: nginx:alpine as L7 LB for stress compose — deploy.replicas can't bind same host port across replicas without external LB
- [Phase 07.3]: pgBouncer transaction mode in stress env matches project psycopg autocommit=True pool pattern
- [Phase 07.3]: P1_PROVIDER=scripted in stress compose for LLM-free deterministic load testing without provider cost
- [Phase 07.3]: ContextManager optional store+provider params with TYPE_CHECKING imports; _persist_mission_context() called at end of on_mission_complete(); cross-run cascade injection in build_planner_context_injection() with 1500-char cap
- [Phase 07.3]: TYPE_CHECKING import guard used for EmbeddingProvider + MissionContextStore in graph.py — no runtime import overhead, no circular imports
- [Phase 07.3]: pg_pool fixture extended to apply all migrations (001-004) sorted — was applying only 001, causing UndefinedTable for mission_contexts in integration tests
- [Phase 07.3]: Integration tests for Postgres stores use pytest.importorskip + requires_postgres marker + pg_pool/clean_pg fixtures as project-standard pattern
- [Phase 07.3]: WALKTHROUGH_PHASE7.3.md written covering 5-layer cascade, RRF fusion, fastembed embedding stack, BIT(384) quantization, HNSW index choice, and ContextManager integration — portfolio knowledge artifact
- [Phase 07.4]: Guard in build_planner_context_injection() added after hits loop — only fires when cross_run_lines non-empty; empty cascade results do NOT mark key as injected
- [Phase 07.4]: _injected_cross_run_keys is instance attribute (not class variable) — no cross-test or cross-run contamination
- [Phase 07.4]: Used caplog pytest fixture to capture CONTEXT INJECT log output for attribution assertion — most direct approach without mocking internal logic
- [Phase 07.4]: source_layer='L0' added to _make_result() test fixture so attribution log emits real layer label instead of '?' placeholder
- [Phase 07.4]: shutdown(wait=False) instead of context manager with ThreadPoolExecutor — prevents blocking __exit__ when thread still sleeping after timeout
- [Phase 07.4]: _CASCADE_TIMEOUT_SECONDS = 2.0 as module constant, plain TimeoutError catch (not alias) in Python 3.12
- [Phase 07.4]: _CACHE_MAX_SIZE=200 + _cache_put() FIFO half-eviction bounds both caches; list(cache.keys())[:n] snapshot pattern avoids RuntimeError on dict mutation

### Roadmap Evolution

- Phase 7.1 inserted after Phase 7: context manipulation for better sub-agent multi-task handling (URGENT)
- Phase 7.2 inserted after Phase 7.1: Architecture Review Implementation - Critical Bug Fixes and Systemic Hardening (URGENT)

### Pending Todos

- Validate run.py and user_run.py work end-to-end with live provider
- Update ROADMAP.md Phase 2 checkbox status (plans 02-03 through 02-05 are done but unchecked)

### Phase Features

| Phase | Feature | Mode | Date | Commit | Status |
|-------|---------|------|------|--------|--------|
| 6 | API security, input validation, public UUIDs, GET /runs, CORS, stream tokens | Extend | 2026-03-05 | 669ec5c | ✓ Complete |
| 6 | Stabilize error handling, context eviction, SQLite thread safety | Stabilize | 2026-03-06 | d30bb22 | ✓ Complete |
| 7 | Postgres persistence layer: stores, protocols, migrations, store factory | Implement | 2026-03-06 | 3734881 | ✓ Complete |
| 7 | Postgres test suite: 25 tests, store factory, concurrency validation | Test | 2026-03-06 | 13fdedd | ✓ Complete |
| 7 | Docker containerization + CI with sqlite/postgres matrix, 80% coverage | Infra | 2026-03-06 | 3fb6923 | ✓ Complete |
| 7 | WALKTHROUGH_PHASE7.md: Docker, Postgres, CI architecture walkthrough | Docs | 2026-03-06 | 1fdf29d | ✓ Complete |
| 7.1 | Data-access log visibility in user_run.py: _DATA_ACCESS_TOOLS panel + run log section | Enhance | 2026-03-07 | (quick-3) | ✓ Complete |
| 7.2 | Tool contract test scaffold: 144 parametrized stubs for 36 tools | Test | 2026-03-08 | e4c7c33 | ✓ Complete |
| 7.2 | Wave 1: dual-execution removal + ContextVar callback isolation | Fix | 2026-03-08 | b6a42df | ✓ Complete |
| 7.2 | Wave 2: persistent WAL connection + set dedup + bounded list caps | Fix | 2026-03-08 | 55e1922 | ✓ Complete |
| 7.2 | Wave 3: auto-derived annotated fields + prepare_state single source of truth | Refactor | 2026-03-08 | 6ed752b | ✓ Complete |
| 7.2 | Wave 3 final: P1_BASH_ENABLED guard, memoize prompt removal, 144 tool contract tests | Security+Test | 2026-03-08 | e3f3214 | ✓ Complete |

### Blockers/Concerns

- [Phase 2 LGUP-02]: ~~ToolNode routing not wired~~ — wired via add_conditional_edges at graph.py:361 for Anthropic path (RESOLVED)
- [Phase 5 ACTIVE]: run.py and user_run.py need live provider (ollama/groq/openai) to test interactively — ScriptedProvider only used in tests
- [Phase 5 ACTIVE]: Prior-context consecutive system messages broke Ollama JSON mode — fix applied but uncommitted

## Session Continuity

Last session: 2026-03-08T21:56:56.680Z
Stopped at: Completed 07.4-03-PLAN.md
Resume file: None
