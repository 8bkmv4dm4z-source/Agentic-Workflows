# Roadmap: Agent Phase0 — Multi-Agent Orchestration Platform

## Overview

Starting from a working single-agent LangGraph foundation (208 tests green, 4-node graph, multi-provider support), this roadmap upgrades the runtime, builds real specialist subgraph delegation, wires observability, and deploys as a production HTTP service. The constraint driving the entire ordering is one version pin: `langgraph<1.0`. Removing it first unlocks every downstream capability. The progression follows a strict dependency chain — upgrade, then harden single-agent execution, then build specialist subgraphs, then integrate multi-agent routing, then observe it, then serve it over HTTP, then containerize and automate quality gates. Phase 1 (Foundation) is already mostly complete and is not replanned here.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)
- Phase 1 (Foundation): Already complete — roadmap begins at Phase 2

- [x] **Phase 1: Foundation** - LangGraph orchestration, multi-provider support, tool registry, RunState, 208 tests (COMPLETE)
- [x] **Phase 2: LangGraph Upgrade and Single-Agent Hardening** - Remove <1.0 pin, adopt ToolNode/tools_condition, add RunState reducers, wire observability and CI (completed 2026-03-03)
- [x] **Phase 3: Specialist Subgraph Architecture** - Build isolated ExecutorState/EvaluatorState TypedDicts and independently-compiled specialist StateGraphs (completed 2026-03-03)
- [x] **Phase 4: Multi-Agent Integration and Model Routing** - Wire _route_to_specialist() to real compiled subgraphs, stabilize multi-mission result preservation, implement real model routing (completed 2026-03-03)
- [x] **Phase 5: Observability Layer and Architecture Snapshot** - Wire Langfuse CallbackHandler for automatic graph tracing, produce phase progression documentation (completed 2026-03-04)
- [x] **Phase 6: Production Service Layer** - FastAPI HTTP service with POST /run, GET /run/{id}, and SSE streaming endpoint (completed 2026-03-04)
- [x] **Phase 7: Production Persistence and CI** - Postgres persistence replacing SQLite, Dockerfile + docker-compose, GitHub Actions CI pipeline (completed 2026-03-06)
- [ ] **Phase 7.1: Context Manipulation for Better Sub-Agent Multi-Task Handling** (INSERTED) - MissionContext model, event-driven eviction, specialist enrichment, provider-agnostic context management
- [x] **Phase 07.2: Architecture Review Implementation - Critical Bug Fixes and Systemic Hardening** (INSERTED) - Fix 2 correctness bugs, 5 critical bottlenecks, 3 structural/safety improvements + Docker agent root fix + read_file_chunk + outline_code + context rules + ruff fully clean (merged to main 2026-03-08)

## Phase Details

### Phase 1: Foundation
**Goal**: Working LangGraph orchestration platform with tool execution, multi-provider support, and auditing
**Depends on**: Nothing
**Requirements**: (Pre-existing — not tracked in this roadmap)
**Success Criteria** (what must be TRUE):
  1. 208 unit and integration tests pass with ruff clean
  2. Developer can run multi-mission workload end-to-end via CLI with audit panel
  3. MissionAuditor 9-check post-run report is produced for every run
  4. ScriptedProvider enables integration tests with no live LLM calls
**Plans**: Complete

### Phase 2: LangGraph Upgrade and Single-Agent Hardening
**Goal**: The langgraph<1.0 pin is removed, ToolNode/tools_condition replace manual envelope parsing, all RunState list fields carry Annotated reducers, observability @observe() is wired, an ADR log is established, and CI runs on every push
**Depends on**: Phase 1
**Requirements**: LGUP-01, LGUP-02, LGUP-03, LGUP-04, OBSV-02, LRNG-02
**Success Criteria** (what must be TRUE):
  1. Developer can run `pip install -e ".[dev]"` with langgraph>=1.0.6,<2.0 and all 208 existing tests pass unchanged
  2. Tool calls for the Anthropic provider path flow through ToolNode with handle_tool_errors=True — the XML/JSON envelope parser is retired for that path only (Ollama/OpenAI/Groq paths unchanged)
  3. All parallel-written RunState list fields (tool_history, mission_reports, memo_events, seen_tool_signatures) carry Annotated[list[T], operator.add] reducers — an integration test asserts both branches' records appear after a two-branch merge
  4. Message history is compacted before it exceeds 40 messages — a test triggers compaction and asserts the condensed history is smaller than the threshold
  5. GitHub Actions workflow runs ruff check, mypy, and pytest on every push using ScriptedProvider, with zero live LLM calls
  6. docs/ADR/ directory exists with at least one ADR documenting the langgraph<1.0 pin removal decision
**Plans**: 5 plans
Plans:
- [x] 02-01-PLAN.md — Upgrade langgraph version pin and verify 208 tests pass (LGUP-01)
- [x] 02-02-PLAN.md — Add Annotated reducers to RunState list fields and message compaction (LGUP-03, LGUP-04)
- [x] 02-03-PLAN.md — Wire ToolNode + tools_condition for Anthropic provider path (LGUP-02)
- [x] 02-04-PLAN.md — Wire @observe() on run() and establish docs/ADR/ log (OBSV-02, LRNG-02)
- [x] 02-05-PLAN.md — Create GitHub Actions CI pipeline (success criterion #5)

### Phase 3: Specialist Subgraph Architecture
**Goal**: Executor and evaluator specialists exist as independently-compiled LangGraph StateGraphs with isolated state schemas — testable and invokable in isolation, before any routing is wired
**Depends on**: Phase 2
**Requirements**: MAGT-01, MAGT-02, MAGT-03, MAGT-04, LRNG-01
**Success Criteria** (what must be TRUE):
  1. ExecutorState TypedDict exists in a dedicated module with no keys shared with RunState — a unit test confirms no key overlap
  2. EvaluatorState TypedDict exists in a dedicated module with no keys shared with RunState — a unit test confirms no key overlap
  3. specialist_executor.py contains a build_executor_subgraph() function that compiles to a runnable StateGraph — a unit test invokes it with a TaskHandoff input and asserts a HandoffResult output
  4. specialist_evaluator.py contains a build_evaluator_subgraph() function that compiles to a runnable StateGraph — a unit test invokes it with a TaskHandoff input and asserts a HandoffResult output
  5. Every change to graph.py, state_schema.py, or specialist files in this phase is accompanied by a WALKTHROUGH update explaining what changed, why, and which LangGraph classes implement it
**Plans**: 3 plans
Plans:
- [x] 03-01-PLAN.md — ExecutorState TypedDict + build_executor_subgraph() + unit tests (MAGT-01, MAGT-02)
- [x] 03-02-PLAN.md — EvaluatorState TypedDict + build_evaluator_subgraph() + unit tests (MAGT-03, MAGT-04)
- [x] 03-03-PLAN.md — State key isolation acceptance tests + WALKTHROUGH_PHASE3.md (LRNG-01)

### Phase 4: Multi-Agent Integration and Model Routing
**Goal**: _route_to_specialist() in graph.py invokes real compiled specialist subgraphs via TaskHandoff and merges HandoffResult back into RunState; multi-mission runs preserve all results; model router makes real routing decisions
**Depends on**: Phase 3
**Requirements**: MAGT-05, MAGT-06, OBSV-03
**Success Criteria** (what must be TRUE):
  1. A full multi-mission run through _route_to_specialist() invokes the compiled executor or evaluator subgraph (not a stub) — logs show real subgraph node transitions
  2. Multi-mission workload with 3+ missions completes without dropping any mission report or tool_history entry — MissionAuditor chain_integrity check passes
  3. Model router makes routing decisions based on task complexity signals (e.g., token_budget_remaining, mission type keyword) — two different task types demonstrably route to different model strengths in an integration test
  4. Subgraphs are compiled without checkpointer argument so parent graph propagates checkpointing — checkpoint replay after a two-mission run restores all mission reports correctly
**Plans**: 4 plans
Plans:
- [x] 04-01-PLAN.md — Cache compiled subgraphs in __init__ and wire _route_to_specialist() with exec_tool_history copy-back (MAGT-05)
- [x] 04-02-PLAN.md — Multi-mission integration tests: tool_history preservation + MissionAuditor chain_integrity + checkpoint replay (MAGT-06)
- [x] 04-03-PLAN.md — Wire ModelRouter in LangGraphOrchestrator __init__ and _generate_with_hard_timeout() (OBSV-03)
- [x] 04-04-PLAN.md — Gap closure: add _record_mission_tool_event() after exec_tool_history copy-back in _route_to_specialist(); fix 26 integration regressions (MAGT-05, MAGT-06)

### Phase 5: Observability Layer and Architecture Snapshot
**Goal**: Langfuse CallbackHandler is wired in graph invocation config for automatic node-level tracing; @observe() closes the open Phase 1 item on the provider path; a Before/After architecture snapshot documents the Phase 1 to Phase 4 progression
**Depends on**: Phase 4
**Requirements**: OBSV-01, LRNG-03
**Success Criteria** (what must be TRUE):
  1. Running a mission with LANGFUSE_PUBLIC_KEY set produces a trace in Langfuse (self-hosted or free cloud) with one span per graph node transition — no manual instrumentation of individual nodes required
  2. @observe() decorator is present on run() entrypoint and provider generate() path — spans appear in Langfuse under the parent run trace
  3. A docs/architecture/ directory contains a Phase 1-4 Before/After snapshot showing RunState schema evolution, graph topology changes, and specialist boundary introduction — readable as a standalone progression document
**Plans**: 2 plans
Plans:
- [x] 05-01-PLAN.md — Fix observability.py import, add get_langfuse_callback_handler(), wire callbacks into graph.py invoke calls, add @observe to OllamaChatProvider (OBSV-01)
- [x] 05-02-PLAN.md — Create docs/architecture/PHASE_PROGRESSION.md with Mermaid phase topology diagrams (LRNG-03)

### Phase 6: Production Service Layer
**Goal**: The orchestration platform is accessible over HTTP — POST /run submits missions, GET /run/{id} retrieves results, GET /run/{id}/stream delivers step-transition events as Server-Sent Events; graph is compiled once at startup
**Depends on**: Phase 5
**Requirements**: PROD-01, PROD-02
**Success Criteria** (what must be TRUE):
  1. Developer can POST a mission JSON to /run and receive a run_id; subsequent GET /run/{run_id} returns the completed audit_report and mission_reports — validated with request/response Pydantic models
  2. GET /run/{run_id}/stream returns a text/event-stream response that emits one event per graph node transition while the run is in progress — a curl test confirms events arrive before the run completes
  3. The graph is compiled once during FastAPI lifespan startup (not per-request) — verified by a log line at startup and absence of compile calls in request handlers
  4. Concurrent POST /run requests execute without SQLite "database is locked" errors (tested with 3 concurrent requests)
**Plans**: 3 plans
Plans:
- [x] 06-01-PLAN.md — Foundation: Pydantic models, RunStore abstraction, FastAPI app skeleton with lifespan (PROD-01)
- [x] 06-02-PLAN.md — Route handlers: POST /run (SSE), GET /run/{id}, GET /run/{id}/stream + HTTP contract tests (PROD-01, PROD-02)
- [x] 06-03-PLAN.md — Convert user_run.py to API client, eval harness, end-to-end verification (PROD-01, PROD-02)

### Phase 7: Production Persistence and CI
**Goal**: All three stores (CheckpointStore, RunStore, MemoStore) swap from SQLite to Postgres when DATABASE_URL is set; the full system starts with docker-compose up; CI runs the complete quality gate against both backends on every push
**Depends on**: Phase 6
**Requirements**: PROD-03, PROD-04, PROD-05
**Success Criteria** (what must be TRUE):
  1. Running docker-compose up starts the FastAPI service and Postgres container; POST /run completes successfully; run results persist in Postgres across container restarts
  2. Concurrent POST /run requests under Postgres checkpointer produce no locking errors — 5 concurrent requests all complete and return distinct run_ids with correct results
  3. GitHub Actions CI workflow passes on a clean push — ruff check, mypy, and pytest all green using ScriptedProvider; no live LLM credentials required in CI
  4. SQLite checkpointer is retained for dev/test (SQLITE_URL env var) and swapped automatically for Postgres in production (DATABASE_URL env var) — no graph logic changes required to switch
**Plans**: 4 plans
Plans:
- [x] 07-01-PLAN.md — Postgres store implementations: Protocol abstractions, PostgresCheckpointStore, PostgresMemoStore, PostgresRunStore, store factory wiring, SQL init scripts (PROD-03)
- [x] 07-02-PLAN.md — Postgres test suite: test fixtures, unit tests for all three stores, store factory tests, concurrency test (PROD-03)
- [x] 07-03-PLAN.md — Docker containerization + CI pipeline: Dockerfile, docker-compose.yml, CI with Postgres matrix, coverage enforcement (PROD-04, PROD-05)
- [ ] 07-04-PLAN.md — Architecture walkthrough: WALKTHROUGH_PHASE7.md covering Docker, Postgres, CI, store factory (PROD-03, PROD-04, PROD-05)

### Phase 07.2: Architecture Review Implementation - Critical Bug Fixes and Systemic Hardening (INSERTED)

**Goal:** Fix 2 correctness bugs (dual tool execution, _active_callbacks data race), 5 critical bottlenecks (SQLite WAL, seen_tool_signatures set conversion, pipeline_trace/handoff caps), and 3 structural/safety improvements (_ANNOTATED_LIST_FIELDS auto-derivation, prepare_state() extraction, run_bash guard, memoize prompt removal, tool contract tests). All changes are internal — no observable behavior change.
**Requirements**: (internal fixes, no external requirement IDs)
**Depends on:** Phase 7.1
**Plans:** 5/5 plans complete

Plans:
- [ ] 07.2-00-PLAN.md — Wave 0: Create test_tool_contracts.py stub with failing parametrized test baseline
- [ ] 07.2-01-PLAN.md — Wave 1: Remove dual-execution in _route_to_specialist; replace _active_callbacks with ContextVar (W1-1, W1-2)
- [ ] 07.2-02-PLAN.md — Wave 2: SQLiteCheckpointStore WAL + persistent conn; seen_tool_signatures set; cap pipeline_trace/handoff lists (W2-3, W2-4, W2-5)
- [ ] 07.2-03-PLAN.md — Wave 3a: Auto-derive _ANNOTATED_LIST_FIELDS; extract prepare_state() (W3-6, W3-7)
- [ ] 07.2-04-PLAN.md — Wave 3b: run_bash P1_BASH_ENABLED guard; remove memoize from prompt; implement tool contract tests (W3-8, W3-9, W3-10)

### Phase 07.1: Context Manipulation for Better Sub-Agent Multi-Task Handling (INSERTED)

**Goal:** Introduce a typed MissionContext model as a durable queryable context store, replace fragmented eviction mechanisms with a unified provider-agnostic ContextManager, enrich specialist subgraph context with mission goals and prior results, and scope planner messages per-mission with deterministic summarization
**Depends on:** Phase 7
**Requirements**: CTX-01, CTX-02, CTX-03, CTX-04, CTX-05, CTX-06, CTX-07, CTX-08, CTX-09, CTX-10, CTX-11, CTX-12
**Success Criteria** (what must be TRUE):
  1. MissionContext Pydantic model stores per-mission context with hierarchical sub-mission support, serialized as dicts on RunState
  2. Mission completion triggers deterministic summarization (no LLM calls) and message eviction, with summaries injected as role="user" [Orchestrator] messages
  3. Large tool results (>4000 chars) are replaced with compact placeholders; sliding window hard cap (30 messages) prevents unbounded growth
  4. Specialist subgraphs receive mission_goal and prior_results_summary as top-level TypedDict fields
  5. Old eviction code (_evict_tool_result_messages, _compact_messages, _mission_handoff_hint, ensure_state_defaults compaction) is fully removed
  6. Every eviction event emits both a log entry and a Langfuse trace event
  7. All 523+ existing tests pass after changes (no regressions)
**Plans**: 4 plans
Plans:
- [ ] 07.1-01-PLAN.md — MissionContext model + artifact extraction + summary generation + RunState wiring (CTX-01, CTX-02, CTX-03, CTX-09)
- [ ] 07.1-02-PLAN.md — ContextManager eviction system + observability + remove old code + test updates (CTX-04, CTX-05, CTX-06, CTX-08, CTX-10, CTX-11)
- [ ] 07.1-03-PLAN.md — Specialist context enrichment: ExecutorState/EvaluatorState fields + build_specialist_context + graph.py wiring (CTX-07, CTX-09)
- [ ] 07.1-04-PLAN.md — Full lifecycle wiring (on_tool_result, on_mission_complete) + integration test + regression verification (CTX-12)

### Phase 07.3: Hybrid Deterministic + Semantic Context System (INSERTED)

**Goal:** Add persistent cross-run mission context with 5-layer cascade retrieval (SHA-256 exact hash → tool bitmask → BM25 → binary vector → float32 cosine), fused via Reciprocal Rank Fusion. Local ONNX embeddings via fastembed (BAAI/bge-small-en-v1.5, 384-dim), no paid APIs. MockEmbeddingProvider for CI. Cross-run artifact store. Multi-replica stress test harness.
**Depends on:** Phase 7.2
**Requirements**: (context enhancement, no external requirement IDs)
**Success Criteria** (what must be TRUE):
  1. `mission_contexts` Postgres table stores completed mission context with SHA-256 hash, tool bitmask, tsvector, binary embedding, and float32 vector indexed by HNSW
  2. `MissionContextStore.query_cascade()` runs the 5-layer cascade: L0 exact hit short-circuits, L1 bitmask short-circuits, L2+L4 fuse via RRF
  3. `MockEmbeddingProvider` returns deterministic 384-dim vectors with no model download; `EMBEDDING_PROVIDER=fastembed` loads fastembed ONNX
  4. `ContextManager.build_planner_context_injection()` injects top-3 cross-run similar missions (formatted as `[Cross-run] Similar: ...`) up to 1500 chars total
  5. All 823+ existing tests pass unchanged; new unit tests cover each cascade layer independently; coverage ≥ 80%
**Plans**: 10 plans

Plans:
- [ ] 07.3-00-PLAN.md — Wave 0: Failing test stubs + conftest clean_pg extension (SCS-01 through SCS-10)
- [ ] 07.3-01-PLAN.md — Wave 1A: DB migrations 002 (vector fix) + 003 (mission_contexts) + 004 (mission_artifacts)
- [ ] 07.3-02-PLAN.md — Wave 1B: context/ package — EmbeddingProvider Protocol, MockEmbeddingProvider, FastEmbedProvider, factory + pyproject.toml
- [ ] 07.3-03-PLAN.md — Wave 2A: MissionContextStore — 5-layer cascade, RRF, encode_tool_pattern, upsert, pool=None fallback
- [ ] 07.3-04-PLAN.md — Wave 2B: ArtifactStore — upsert, semantic search, pool=None fallback
- [ ] 07.3-05-PLAN.md — Wave 3A: ContextManager wiring — optional params, _persist_mission_context, cross-run injection, 1500-char cap
- [ ] 07.3-06-PLAN.md — Wave 3B: graph.py wiring — LangGraphOrchestrator optional params forwarded to ContextManager
- [ ] 07.3-07-PLAN.md — Wave 4A: Postgres integration tests — full cascade cycle, cross-run injection, two-run smoke
- [ ] 07.3-08-PLAN.md — Wave 4B: docker-compose.stress.yml + scripts/stress_test.py
- [ ] 07.3-09-PLAN.md — Wave 4C: WALKTHROUGH_PHASE7.3.md

### Phase 07.4: Context Injection Dedup and Runtime Safety (INSERTED)

**Goal:** Fix the cross-run context injection dedup bug (same `[Cross-run] Similar:` string re-appended to `state["messages"]` on every planner step), add a timeout guard for the synchronous `query_cascade()` call in the planner hot path, bound `_cascade_cache`/`_embed_cache` to prevent memory leaks in long-lived processes, and fix the `_make_result()` test fixture that omits the required `source_layer` field.
**Depends on:** Phase 07.3
**Requirements**: (context injection correctness, no external requirement IDs)
**Success Criteria** (what must be TRUE):
  1. After N planner steps with the same goal, `state["messages"]` contains exactly one `[Cross-run] Similar:` injection (not N copies) — verified by a unit test asserting message count
  2. A slow or non-responsive Postgres cascade query does not block the planner indefinitely — `query_cascade()` is wrapped with a 2-second timeout, falling back to `[]`
  3. `_cascade_cache` and `_embed_cache` never exceed a fixed bound (200 entries) in long-lived processes — verified by a unit test calling `build_planner_context_injection` 300 times with distinct keys
  4. `_make_result()` in `test_context_manager_7_3.py` includes `source_layer` — attribution logs show a real layer label (`L0`, `L1`, etc.) instead of `?` in unit tests
  5. All existing 1198+ tests pass unchanged

**Plans:** 4/4 plans complete
Plans:
- [ ] 07.4-01-PLAN.md — Add `_injected_cross_run_keys: set[str]` to ContextManager; guard injection; regression test for once-per-run behavior
- [ ] 07.4-02-PLAN.md — Wrap `query_cascade()` in ThreadPoolExecutor with 2s timeout; fallback to `[]`; test for timeout path
- [ ] 07.4-03-PLAN.md — Bound `_cascade_cache` + `_embed_cache` to 200 entries with truncation on overflow; test for bound enforcement
- [ ] 07.4-04-PLAN.md — Fix `_make_result()` source_layer + add attribution assertion to cross-run injection tests

### Phase 07.6: LLM Output Structure Stabilization (INSERTED)

**Goal:** Mechanically enforce LLM output structure before multi-mission agent teams are deployed with weaker executor models. Fix the phi4 context overflow blocker (8192-token context), add provider-aware compact prompts, re-enable GBNF grammar for llama-cpp, instrument fallback parser, convert handoff TypedDicts to Pydantic, persist chunked-read cursors to survive context eviction, and add structural health metrics to the audit report.
**Depends on:** Phase 07.5
**Requirements**: (structural hardening, no external requirement IDs)
**Success Criteria** (what must be TRUE):
  1. phi4 (llama-cpp, 8192-token context) completes a full multi-mission run without "context length exceeded" errors — system prompt + tool list fits within n_ctx budget using compact tier
  2. `provider.context_size()` method exists on all four providers (OpenAI, Groq, Ollama, LlamaCpp) — `_select_prompt_tier()` returns "compact" for providers with ≤ 10k context
  3. `supervisor.md` contains a `## COMPACT` variant (≤ 15 lines) injected when tier=compact
  4. `action_parser.py` logs a WARNING with step/model_output prefix whenever `extract_first_json_object()` fallback is triggered
  5. `TaskHandoff` and `HandoffResult` are Pydantic BaseModels with `extra="forbid"` — malformed handoff data raises ValidationError at parse time
  6. `mission_context_store.py` has `upsert_cursor()` / `get_cursor()` / `get_active_cursors()` methods; chunked reads store progress in `sub_task_cursors` table
  7. After context eviction, cursor hints are re-injected as `[Orchestrator]` messages before the next planner call — duplicate-kill loop on chunk resume is eliminated
  8. `audit_report["structural_health"]` contains `json_parse_fallback`, `schema_mismatch` counters — visible after every run
  9. All existing tests pass unchanged (no regressions)

**Plans:** 5/5 plans complete
Plans:
- [ ] 07.6-00-PLAN.md — Wave 0: Failing test stubs for provider context_size, prompt tier, cursor persistence, structural health
- [ ] 07.6-01-PLAN.md — Wave 1: context_size() on all providers + _select_prompt_tier() + compact _build_system_prompt() + COMPACT directive (C0/C1/C2/C3)
- [ ] 07.6-02-PLAN.md — Wave 1: parse_action_json() fallback WARNING + HandoffResult/TaskHandoff Pydantic migration (A2, A3)
- [ ] 07.6-03-PLAN.md — Wave 2: upsert_cursor/get_cursor/get_active_cursors + cursor hint injection + cursor bypass (E1-E4)
- [ ] 07.6-04-PLAN.md — Wave 3: structural_health in RunState + audit_report + env.example grammar comment + regression gate (D2, A1)

**Post-phase extension (quick-5, 2026-03-10):** Tool Schema Enforcement — compact prompt now emits arg signatures (`classify_intent(text)` instead of `classify_intent`); `ChatProvider.generate()` accepts `response_schema: dict | None`; `LangGraphOrchestrator._build_action_json_schema()` generates an anyOf JSON schema from the live tool registry and passes it to providers — LlamaCpp uses it when grammar is disabled, replacing fragile GBNF. See `.planning/quick/5-tool-schema-enforcement-compact-prompt-s/`.

### Phase 07.7: Hybrid Intent Classifier + Few-Shot Prompt Refinement (INSERTED)

**Goal:** Layer an LLM-based intent classifier on top of the deterministic `mission_parser.py` to classify mission type and complexity before planning begins. Add 2-3 concrete few-shot JSON examples to each directive (supervisor, executor, evaluator). Extend compact/full tier system with per-role token budgets. Wire intent classification output into ModelRouter to replace explicit complexity params.
**Depends on:** Phase 07.6
**Success Criteria** (what must be TRUE):
  1. `mission_parser.parse_missions()` accepts optional `ChatProvider`; LLM classifies mission type + complexity into `StructuredPlan.intent_classification: dict | None`; 500ms timeout with deterministic fallback — unit test with failing mock provider
  2. supervisor.md, executor.md, evaluator.md each contain `## FEW_SHOT` section; `_build_system_prompt()` injects on "full" tier, omits on "compact" — unit test
  3. `_build_system_prompt()` enforces per-role token budgets (classifier ~300, planner ~1000, executor ~300); `_estimate_prompt_tokens()` helper truncates tool descriptions when over budget — unit test with 50-tool registry
  4. `StructuredPlan.intent_classification` complexity feeds into `ModelRouter.route()` — "complex" → strong, "simple" → fast — integration test with dual providers
  5. All existing tests pass unchanged
**Plans:** 4/4 plans complete
Plans:
- [ ] 07.7-01-PLAN.md — Typed Tool.args_schema replacing regex required_args() + migrate all 36 tools (2 batches) + update graph.py consumers (SC-7)
- [ ] 07.7-02-PLAN.md — IntentClassification dataclass + LLM classifier in parse_missions() + 500ms timeout + deterministic fallback (SC-1)
- [ ] 07.7-03-PLAN.md — FEW_SHOT sections in all directives + COMPACT for executor/evaluator + per-role token budgets + _estimate_prompt_tokens (SC-2, SC-3)
- [ ] 07.7-04-PLAN.md — Intent-driven ModelRouter wiring + format correction escalation chain + structural_health counters (SC-4, SC-6)

**Key files:**
- `src/agentic_workflows/orchestration/langgraph/mission_parser.py` — add LLM classifier
- `src/agentic_workflows/orchestration/langgraph/graph.py` — _build_system_prompt(), token budgets
- `src/agentic_workflows/directives/supervisor.md` — add FEW_SHOT section
- `src/agentic_workflows/directives/executor.md` — add FEW_SHOT section
- `src/agentic_workflows/directives/evaluator.md` — add FEW_SHOT section
- `src/agentic_workflows/orchestration/langgraph/model_router.py` — intent-driven routing

**Note:** /no_think is already wired in LlamaCppChatProvider (provider.py:564-572). No changes needed — it appends `/no_think` when `LLAMA_CPP_THINKING` is off.

---

### Phase 07.8: Multi-Model Provider Routing + Smart Cloud Fallback (INSERTED)

**Goal:** Extend LlamaCppChatProvider to support alias-based routing for multi-model llama-server instances (e.g., `--alias planner` / `--alias executor`). Upgrade ModelRouter to infer task complexity from runtime signals (token_budget_remaining, mission type, retry count) instead of caller-supplied labels. Add automatic cloud fallback: when the local llama.cpp model fails validation (schema mismatch, repeated parse failures, timeout), auto-escalate to Groq API with retry chain tracking in structural_health.
**Depends on:** Phase 07.7
**Success Criteria** (what must be TRUE):
  1. `LlamaCppChatProvider` accepts `model_alias: str | None` and has `with_alias(alias) -> LlamaCppChatProvider` factory; `generate()` passes alias as model name to llama-server — unit test asserting model field
  2. `ModelRouter.route()` accepts `signals: RoutingSignals` TypedDict (token_budget_remaining, mission_type, retry_count, step); infers complexity: multi_step/retry>=2/budget<5000 → strong, else → fast — parametrized unit tests
  3. `LangGraphOrchestrator.__init__` accepts `fallback_provider: ChatProvider | None`; on ProviderTimeoutError or 2 consecutive parse failures, retries on fallback_provider; events counted in `structural_health["cloud_fallback_count"]` — integration test with failing mock
  4. `structural_health` gains: `cloud_fallback_count`, `local_model_failures`, `routing_decisions` — visible in audit_report
  5. All existing tests pass unchanged
**Plans:** 4/4 plans complete
Plans:
- [ ] 07.8-01-PLAN.md — Multi-model LlamaCpp alias support (model_alias param, with_alias factory)
- [ ] 07.8-02-PLAN.md — Intelligent ModelRouter with RoutingSignals TypedDict + signal-based inference
- [ ] 07.8-03-PLAN.md — Smart cloud fallback (fallback_provider, retry chain, structural_health counters)
- [ ] 07.8-04-PLAN.md — Structural health expansion + WALKTHROUGH

**Key files:**
- `src/agentic_workflows/orchestration/langgraph/provider.py` — LlamaCppChatProvider alias routing
- `src/agentic_workflows/orchestration/langgraph/model_router.py` — RoutingSignals, inference logic
- `src/agentic_workflows/orchestration/langgraph/graph.py` — fallback_provider wiring, counter increments
- `src/agentic_workflows/orchestration/langgraph/state_schema.py` — new structural_health fields

---

### Phase 07.9: Dynamic Context Querying + Memory Consolidation + Compliance Observability (INSERTED)

**Goal:** Add a `query_context` tool that lets the LLM dynamically query pgvector during planning (using existing MissionContextStore infrastructure). Implement memory consolidation to cluster old episodic memories by semantic similarity and compress them. Wire schema compliance as a custom Langfuse metric using existing structural_health counters.
**Depends on:** Phase 07.8
**Success Criteria** (what must be TRUE):
  1. `query_context` tool registered with args `{query: str, max_results: int}`; calls `MissionContextStore.query_cascade()`; returns top-N formatted results; when store is None returns empty — unit tests
  2. `_TOOL_KEYWORD_MAP` maps "prior", "previous", "recall", "remember" → query_context; supervisor.md few-shot includes query_context example — unit test
  3. `consolidate_memories()` in `storage/memory_consolidation.py` clusters missions >7 days by cosine similarity (0.85 threshold), replaces clusters with summaries, deletes originals transactionally; `--consolidate` CLI flag — Postgres integration test
  4. `observability.py` gains `report_schema_compliance(role, first_attempt_success)` reporting to Langfuse; graph.py calls after each parse attempt — unit test with mock client
  5. `run_audit.py` cross-run summary shows schema compliance rate per provider — unit test with 3 mock runs
  6. All existing tests pass unchanged
**Plans:** 4 plans
Plans:
- [x] 07.9-01-PLAN.md — query_context tool + registry + keyword map + supervisor few-shot (SC-1, SC-2)
- [x] 07.9-02-PLAN.md — Memory consolidation module + cosine clustering + CLI flag (SC-3)
- [x] 07.9-03-PLAN.md — Schema compliance Langfuse metric + graph.py call sites (SC-4)
- [ ] 07.9-04-PLAN.md — Cross-run compliance dashboard in run_audit.py + WALKTHROUGH (SC-5, SC-6)

**Key files:**
- `src/agentic_workflows/tools/` — new query_context.py
- `src/agentic_workflows/orchestration/langgraph/mission_parser.py` — keyword map update
- `src/agentic_workflows/storage/memory_consolidation.py` — new module
- `src/agentic_workflows/observability.py` — compliance metric
- `src/agentic_workflows/orchestration/langgraph/run_audit.py` — compliance dashboard

---

### Phase 07.5: Wire ArtifactStore to Runtime (INSERTED)

**Goal:** Connect the currently-dead `ArtifactStore` to the live mission execution path. `MissionContext.artifacts` (already computed at `context_manager.py:492`) should be persisted to Postgres via `ArtifactStore.upsert()` inside `_persist_mission_context()`. Add `artifact_store` parameter to `LangGraphOrchestrator` and `ContextManager`, wire it in `run.py` and `user_run.py`, and add an integration test confirming artifacts appear in the DB after a mission completes.
**Depends on:** Phase 07.4
**Requirements**: (artifact persistence, no external requirement IDs)
**Success Criteria** (what must be TRUE):
  1. After a mission completes with artifacts, `SELECT * FROM mission_artifacts WHERE run_id = ?` returns the expected rows — verified by a Postgres integration test
  2. `LangGraphOrchestrator(artifact_store=None)` (default) runs without error — backward compat preserved
  3. `run.py` and `user_run.py` instantiate `ArtifactStore(pool=pg_pool)` when `DATABASE_URL` is set and pass it to the orchestrator
  4. All existing 1198+ tests pass unchanged

**Plans:** 5/5 plans complete
Plans:
- [ ] 07.5-01-PLAN.md — Add `artifact_store` param to `ContextManager.__init__`; wire `_persist_mission_context()` to call `artifact_store.upsert()` for each artifact
- [ ] 07.5-02-PLAN.md — Add `artifact_store` param to `LangGraphOrchestrator.__init__`; forward to `ContextManager`
- [ ] 07.5-03-PLAN.md — Wire `ArtifactStore(pool=pg_pool)` in `run.py` + `user_run.py` when `DATABASE_URL` set
- [ ] 07.5-04-PLAN.md — Postgres integration test: mission completes → artifacts appear in `mission_artifacts` table
- [ ] 07.5-05-PLAN.md — Update `docs/WALKTHROUGH_PHASE7.3.md` with artifact persistence flow

## Progress

**Execution Order:**
Phases execute in numeric order: 2 → 3 → 4 → 5 → 6 → 7 → 7.1 → 7.2 → 7.3 → 7.4 → 7.5 → 7.6 → 7.7 → 7.8 → 7.9

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | Complete | Complete | 2026-03-02 |
| 2. LangGraph Upgrade and Single-Agent Hardening | 5/5 | Complete | 2026-03-03 |
| 3. Specialist Subgraph Architecture | 3/3 | Complete | 2026-03-03 |
| 4. Multi-Agent Integration and Model Routing | 6/6 | Complete | 2026-03-03 |
| 5. Observability Layer and Architecture Snapshot | 2/2 | Complete | 2026-03-04 |
| 6. Production Service Layer | 3/3 | Complete | 2026-03-04 |
| 7. Production Persistence and CI | 4/4 | Complete   | 2026-03-06 |
| 7.1. Context Manipulation (INSERTED) | 3/4 | In Progress|  |
| 7.2. Architecture Review - Critical Bug Fixes (INSERTED) | 5/5 | Complete   | 2026-03-08 |
| 7.3. Hybrid Deterministic + Semantic Context System (INSERTED) | 10/10 | Complete    | 2026-03-08 |
| 7.4. Context Injection Dedup and Runtime Safety (INSERTED) | 4/4 | Complete   | 2026-03-08 |
| 7.5. Wire ArtifactStore to Runtime (INSERTED) | 2/5 | Complete    | 2026-03-08 |
| 7.6. LLM Output Structure Stabilization (INSERTED) | 2/5 | In Progress|  |
| 7.7. Hybrid Intent Classifier + Few-Shot Prompts (INSERTED) | 4/4 | Complete   | 2026-03-10 |
| 7.8. Multi-Model Routing + Cloud Fallback (INSERTED) | 3/4 | In Progress|  |
| 7.9. Dynamic Context + Compliance Observability (INSERTED) | 1/4 | In Progress|  |
