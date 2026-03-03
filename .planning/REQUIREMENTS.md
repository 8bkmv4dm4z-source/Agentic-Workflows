# Requirements: Agent Phase0 — Multi-Agent Orchestration Platform

**Defined:** 2026-03-02
**Core Value:** A specialist-routing multi-agent system that reliably executes multi-mission workloads end-to-end — with the architecture understood deeply enough to stress test, evolve, and deploy with confidence.

## v1 Requirements

### LangGraph Upgrade

- [x] **LGUP-01**: Developer can remove the `langgraph<1.0` pin and upgrade to `>=1.0.9` without breaking any of the 208 existing tests
- [x] **LGUP-02**: Developer can use `ToolNode` + `tools_condition` via `langchain-anthropic` binding, replacing the manual XML/JSON envelope parser in `graph.py`
- [x] **LGUP-03**: All `RunState` list fields (`tool_history`, `mission_reports`, `memo_events`, `seen_tool_signatures`) use `Annotated[list[T], operator.add]` reducers so parallel `Send()` branches cannot silently overwrite each other
- [x] **LGUP-04**: Message history is compacted when it exceeds a configurable threshold (default 40 messages) before specialist delegation multiplies message volume

### Multi-Agent Delegation

- [x] **MAGT-01**: `ExecutorState` TypedDict exists as an isolated state schema for the executor specialist (does not share keys with `RunState`)
- [x] **MAGT-02**: `specialist_executor.py` contains a real, independently-compiled `StateGraph` for the executor role that can be invoked and tested in isolation
- [x] **MAGT-03**: `EvaluatorState` TypedDict exists as an isolated state schema for the evaluator specialist
- [x] **MAGT-04**: `specialist_evaluator.py` contains a real, independently-compiled `StateGraph` for the evaluator role that can be invoked and tested in isolation
- [x] **MAGT-05**: `_route_to_specialist()` in `graph.py` invokes the compiled specialist subgraph via `TaskHandoff` input and merges the `HandoffResult` output back into `RunState` — not stubs
- [x] **MAGT-06**: Multi-mission workloads complete without dropping results — all mission reports and tool history entries are preserved across a multi-mission run

### Observability

- [ ] **OBSV-01**: Langfuse `CallbackHandler` is wired in the graph invocation `config` so all graph node transitions are traced automatically (free Langfuse tier or self-hosted)
- [x] **OBSV-02**: `@observe()` decorator is wired on the `run()` entrypoint and provider `generate()` path (open Phase 1 item — closes it)
- [x] **OBSV-03**: Model-strength routing makes real routing decisions based on task complexity signals (not the existing stub returning a hardcoded path)

### Production Infrastructure

- [ ] **PROD-01**: FastAPI service exposes `POST /run` (submit a mission) and `GET /run/{id}` (retrieve results) with request/response validation
- [ ] **PROD-02**: FastAPI service exposes `GET /run/{id}/stream` as a Server-Sent Events endpoint that streams step-transition events during execution
- [ ] **PROD-03**: `AsyncPostgresSaver` replaces the SQLite checkpointer for production use (SQLite retained for dev/test only)
- [ ] **PROD-04**: `Dockerfile` and `docker-compose.yml` allow the full system (API + Postgres) to be started with a single `docker-compose up`
- [ ] **PROD-05**: GitHub Actions CI pipeline runs `ruff check`, `mypy`, and `pytest` on every push, using `ScriptedProvider` (no live LLM calls in CI)

### Learning System

- [x] **LRNG-01**: Every non-trivial refactor (any change touching graph.py, state_schema.py, or specialist files) is accompanied by a WALKTHROUGH update that explains: what changed, why it changed, and which LangGraph/Python classes implement the change
- [x] **LRNG-02**: An Architecture Decision Log (`docs/ADR/`) records each significant design decision with context, alternatives considered, and rationale — populated as decisions are made during each phase
- [ ] **LRNG-03**: Each completed phase produces a "Before/After" architecture snapshot showing the system state before and after the phase — making the progression of the build explicit and reviewable

## v2 Requirements

### Parallel Execution

- **PRLL-01**: Map-reduce parallel mission fan-out via `Send()` API — all missions run concurrently with reducer-safe state merge (deferred until single-mission stability is confirmed at scale)
- **PRLL-02**: Parallel mission execution preserves per-mission `tool_history` attribution — auditor correctly maps tool calls to missions under fan-out

### Human-in-the-Loop

- **HITL-01**: `interrupt()` API enables pause/approve/edit/reject workflows at configurable graph nodes
- **HITL-02**: Interrupted runs persist state across restarts via checkpointer (resume from checkpoint after human review)

### Stress Testing

- **STST-01**: Failure injection framework tests known failure modes: duplicate tool call injection, cache poisoning, recursion loop detection, provider timeout simulation
- **STST-02**: Load patterns test multi-mission workloads at 5x, 10x, 20x normal volume with measurable reliability metrics
- **STST-03**: Cross-run audit trend analysis detects regression across runs (extends existing `run_audit.py`)

### Model Routing

- **MROT-01**: Model routing heuristics are validated empirically against real Ollama workloads (data-driven, not rule-based)
- **MROT-02**: Model router supports pluggable routing strategies without changing the graph topology

## Out of Scope

| Feature | Reason |
|---------|--------|
| End-user UI | Internal team tooling only; no frontend planned |
| Public library packaging | Not building for external developer consumption |
| Fine-tuning / model training | Uses off-the-shelf providers (Ollama, OpenAI, Groq) only |
| Multi-tenancy | Single-team internal tool |
| RAG / vector store | Not required for current task domain |
| LangGraph Cloud / langgraph-api | Platform lock-in; self-hosted preferred |
| Autonomous agent spawning | Out of scope for controlled orchestration design |
| Token budget hard gate | Using Ollama locally — no API cost pressure |
| Paid observability tiers | Langfuse free/self-hosted only; LangSmith not adopted |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| LGUP-01 | Phase 2 | Complete |
| LGUP-02 | Phase 2 | Complete |
| LGUP-03 | Phase 2 | Complete (02-02) |
| LGUP-04 | Phase 2 | Complete (02-02) |
| OBSV-02 | Phase 2 | Complete |
| LRNG-02 | Phase 2 | Complete |
| MAGT-01 | Phase 3 | Complete |
| MAGT-02 | Phase 3 | Complete |
| MAGT-03 | Phase 3 | Complete |
| MAGT-04 | Phase 3 | Complete |
| LRNG-01 | Phase 3 | Complete |
| MAGT-05 | Phase 4 | Complete |
| MAGT-06 | Phase 4 | Complete |
| OBSV-03 | Phase 4 | Complete |
| OBSV-01 | Phase 5 | Pending |
| LRNG-03 | Phase 5 | Pending |
| PROD-01 | Phase 6 | Pending |
| PROD-02 | Phase 6 | Pending |
| PROD-03 | Phase 7 | Pending |
| PROD-04 | Phase 7 | Pending |
| PROD-05 | Phase 7 | Pending |

**Coverage:**
- v1 requirements: 21 total
- Mapped to phases: 21
- Unmapped: 0 (all requirements mapped)

| Phase | Requirements |
|-------|-------------|
| Phase 2 | LGUP-01, LGUP-02, LGUP-03, LGUP-04, OBSV-02, LRNG-02 (6) |
| Phase 3 | MAGT-01, MAGT-02, MAGT-03, MAGT-04, LRNG-01 (5) |
| Phase 4 | MAGT-05, MAGT-06, OBSV-03 (3) |
| Phase 5 | OBSV-01, LRNG-03 (2) |
| Phase 6 | PROD-01, PROD-02 (2) |
| Phase 7 | PROD-03, PROD-04, PROD-05 (3) |

---
*Requirements defined: 2026-03-02*
*Last updated: 2026-03-02 — traceability populated after roadmap creation*
