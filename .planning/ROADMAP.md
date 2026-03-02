# Roadmap: Agent Phase0 — Multi-Agent Orchestration Platform

## Overview

Starting from a working single-agent LangGraph foundation (208 tests green, 4-node graph, multi-provider support), this roadmap upgrades the runtime, builds real specialist subgraph delegation, wires observability, and deploys as a production HTTP service. The constraint driving the entire ordering is one version pin: `langgraph<1.0`. Removing it first unlocks every downstream capability. The progression follows a strict dependency chain — upgrade, then harden single-agent execution, then build specialist subgraphs, then integrate multi-agent routing, then observe it, then serve it over HTTP, then containerize and automate quality gates. Phase 1 (Foundation) is already mostly complete and is not replanned here.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)
- Phase 1 (Foundation): Already complete — roadmap begins at Phase 2

- [x] **Phase 1: Foundation** - LangGraph orchestration, multi-provider support, tool registry, RunState, 208 tests (COMPLETE)
- [ ] **Phase 2: LangGraph Upgrade and Single-Agent Hardening** - Remove <1.0 pin, adopt ToolNode/tools_condition, add RunState reducers, wire observability and CI
- [ ] **Phase 3: Specialist Subgraph Architecture** - Build isolated ExecutorState/EvaluatorState TypedDicts and independently-compiled specialist StateGraphs
- [ ] **Phase 4: Multi-Agent Integration and Model Routing** - Wire _route_to_specialist() to real compiled subgraphs, stabilize multi-mission result preservation, implement real model routing
- [ ] **Phase 5: Observability Layer and Architecture Snapshot** - Wire Langfuse CallbackHandler for automatic graph tracing, produce phase progression documentation
- [ ] **Phase 6: Production Service Layer** - FastAPI HTTP service with POST /run, GET /run/{id}, and SSE streaming endpoint
- [ ] **Phase 7: Production Persistence and CI** - AsyncPostgresSaver replacing SQLite, Dockerfile + docker-compose, GitHub Actions CI pipeline

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
- [ ] 02-03-PLAN.md — Wire ToolNode + tools_condition for Anthropic provider path (LGUP-02)
- [ ] 02-04-PLAN.md — Wire @observe() on run() and establish docs/ADR/ log (OBSV-02, LRNG-02)
- [ ] 02-05-PLAN.md — Create GitHub Actions CI pipeline (success criterion #5)

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
- [ ] 03-01-PLAN.md — ExecutorState TypedDict + build_executor_subgraph() + unit tests (MAGT-01, MAGT-02)
- [ ] 03-02-PLAN.md — EvaluatorState TypedDict + build_evaluator_subgraph() + unit tests (MAGT-03, MAGT-04)
- [ ] 03-03-PLAN.md — State key isolation acceptance tests + WALKTHROUGH_PHASE3.md (LRNG-01)

### Phase 4: Multi-Agent Integration and Model Routing
**Goal**: _route_to_specialist() in graph.py invokes real compiled specialist subgraphs via TaskHandoff and merges HandoffResult back into RunState; multi-mission runs preserve all results; model router makes real routing decisions
**Depends on**: Phase 3
**Requirements**: MAGT-05, MAGT-06, OBSV-03
**Success Criteria** (what must be TRUE):
  1. A full multi-mission run through _route_to_specialist() invokes the compiled executor or evaluator subgraph (not a stub) — logs show real subgraph node transitions
  2. Multi-mission workload with 3+ missions completes without dropping any mission report or tool_history entry — MissionAuditor chain_integrity check passes
  3. Model router makes routing decisions based on task complexity signals (e.g., token_budget_remaining, mission type keyword) — two different task types demonstrably route to different model strengths in an integration test
  4. Subgraphs are compiled without checkpointer argument so parent graph propagates checkpointing — checkpoint replay after a two-mission run restores all mission reports correctly
**Plans**: TBD

### Phase 5: Observability Layer and Architecture Snapshot
**Goal**: Langfuse CallbackHandler is wired in graph invocation config for automatic node-level tracing; @observe() closes the open Phase 1 item on the provider path; a Before/After architecture snapshot documents the Phase 1 to Phase 4 progression
**Depends on**: Phase 4
**Requirements**: OBSV-01, LRNG-03
**Success Criteria** (what must be TRUE):
  1. Running a mission with LANGFUSE_PUBLIC_KEY set produces a trace in Langfuse (self-hosted or free cloud) with one span per graph node transition — no manual instrumentation of individual nodes required
  2. @observe() decorator is present on run() entrypoint and provider generate() path — spans appear in Langfuse under the parent run trace
  3. A docs/architecture/ directory contains a Phase 1-4 Before/After snapshot showing RunState schema evolution, graph topology changes, and specialist boundary introduction — readable as a standalone progression document
**Plans**: TBD

### Phase 6: Production Service Layer
**Goal**: The orchestration platform is accessible over HTTP — POST /run submits missions, GET /run/{id} retrieves results, GET /run/{id}/stream delivers step-transition events as Server-Sent Events; graph is compiled once at startup
**Depends on**: Phase 5
**Requirements**: PROD-01, PROD-02
**Success Criteria** (what must be TRUE):
  1. Developer can POST a mission JSON to /run and receive a run_id; subsequent GET /run/{run_id} returns the completed audit_report and mission_reports — validated with request/response Pydantic models
  2. GET /run/{run_id}/stream returns a text/event-stream response that emits one event per graph node transition while the run is in progress — a curl test confirms events arrive before the run completes
  3. The graph is compiled once during FastAPI lifespan startup (not per-request) — verified by a log line at startup and absence of compile calls in request handlers
  4. Concurrent POST /run requests execute without SQLite "database is locked" errors (tested with 3 concurrent requests)
**Plans**: TBD

### Phase 7: Production Persistence and CI
**Goal**: SQLite checkpointer is replaced by AsyncPostgresSaver for production; the full system (API + Postgres) starts with docker-compose up; GitHub Actions runs the complete quality gate on every push
**Depends on**: Phase 6
**Requirements**: PROD-03, PROD-04, PROD-05
**Success Criteria** (what must be TRUE):
  1. Running docker-compose up starts the FastAPI service and Postgres container; POST /run completes successfully; run results persist in Postgres across container restarts
  2. Concurrent POST /run requests under Postgres checkpointer produce no locking errors — 5 concurrent requests all complete and return distinct run_ids with correct results
  3. GitHub Actions CI workflow passes on a clean push — ruff check, mypy, and pytest all green using ScriptedProvider; no live LLM credentials required in CI
  4. SQLite checkpointer is retained for dev/test (SQLITE_URL env var) and swapped automatically for Postgres in production (DATABASE_URL env var) — no graph logic changes required to switch
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 2 → 3 → 4 → 5 → 6 → 7

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | Complete | Complete | 2026-03-02 |
| 2. LangGraph Upgrade and Single-Agent Hardening | 3/5 | In Progress|  |
| 3. Specialist Subgraph Architecture | 0/3 | Not started | - |
| 4. Multi-Agent Integration and Model Routing | 0/TBD | Not started | - |
| 5. Observability Layer and Architecture Snapshot | 0/TBD | Not started | - |
| 6. Production Service Layer | 0/TBD | Not started | - |
| 7. Production Persistence and CI | 0/TBD | Not started | - |
