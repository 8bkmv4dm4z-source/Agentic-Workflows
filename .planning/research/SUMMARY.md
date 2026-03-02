# Project Research Summary

**Project:** Agent Phase0 — Multi-Agent Orchestration Platform
**Domain:** Graph-based multi-agent orchestration (LangGraph specialist routing, prototype-to-production)
**Researched:** 2026-03-02
**Confidence:** MEDIUM-HIGH

## Executive Summary

This project is a production LangGraph orchestration platform currently at Phase 1.5 — a working single-agent graph with 208 passing tests, SQLite checkpointing, multi-provider support, and a post-run auditor. The primary blocker to every subsequent phase is the `langgraph<1.0` pin in `pyproject.toml`. Removing it unlocks `ToolNode`, `tools_condition`, `langchain-anthropic` native tool calling, and the `interrupt()` HITL API — all of which are required for Phases 2-4. LangGraph 1.0 is explicitly backwards-compatible with 0.2.x, making this upgrade low-risk with the existing 208-test suite as a regression safety net.

The recommended path builds four clear capabilities in sequence: upgrade and harden the single-agent layer (Phase 2), add real specialist subgraph delegation with typed boundaries (Phase 3), and wrap the result in a FastAPI service layer with PostgreSQL checkpointing and CI (Phase 4). The biggest architectural decision in Phase 3 is state boundary design: specialists must use isolated `TypedDict` schemas with narrow `HandoffResult` outputs — not shared keys with `RunState`. Sharing keys without `Annotated` reducers causes silent result dropping under parallel `Send`-based execution, and the current `RunState` has no reducers on any of its list fields.

The top production risks are: (1) plain list fields in `RunState` silently dropping results under `Send`-based parallel execution; (2) subgraph state bleeding when parent and child share keys; (3) SQLite being unsafe under concurrent FastAPI requests; and (4) `langgraph-prebuilt>=1.0.1` disabling tool error handling by default. All four are avoidable with explicit patterns identified in the research and mitigations that can be wired into the implementation before the problematic phase begins.

---

## Key Findings

### Recommended Stack

The stack requires one critical change (remove the `<1.0` pin) and adds four new layers (provider bindings, service, persistence, infra). Everything else is already correct. The full target stack is LangGraph `>=1.0.9` + `langchain-anthropic>=0.3` + FastAPI + `langgraph-checkpoint-postgres>=3.0.2` + Langfuse `>=3.0` + Docker. All existing tooling (pydantic, openai, groq, ruff, mypy, pytest, pytest-asyncio, httpx) is already pinned correctly and does not need changes.

`instructor` is explicitly not needed — `langchain-anthropic`'s `with_structured_output(PydanticModel)` covers the same use case. `langgraph-api` (LangGraph Cloud) is explicitly not recommended due to platform lock-in. The `tiangolo/uvicorn-gunicorn-fastapi` base image is deprecated; build from `python:3.12-slim` instead.

**Core technologies:**
- `langgraph>=1.0.9`: Graph runtime — only change needed is removing the `<1.0` upper bound; backwards-compatible
- `langchain-anthropic>=0.3`: Anthropic provider binding — enables `bind_tools()` and `ToolNode` dispatch, eliminating manual XML/JSON envelope parsing
- `fastapi>=0.115` + `uvicorn>=0.34`: Service layer — native async generator support via `StreamingResponse` for SSE; compile graph once in `lifespan`, not per-request
- `langgraph-checkpoint-postgres>=3.0.2`: Production persistence — swap-in for SQLite; `AsyncPostgresSaver` requires no graph logic changes
- `langfuse>=3.0`: Observability — `CallbackHandler` wires all graph node tracing without code changes; already in optional deps, needs promotion to default

### Expected Features

The eight must-have features form a strict dependency chain. The LangGraph upgrade unblocks everything. Stable multi-mission output must be fixed before real subgraph delegation. Real subgraph delegation must work before parallel map-reduce. The FastAPI layer is the deployment gate for CI and Docker.

**Must have (table stakes):**
- LangGraph `>=1.0` upgrade — unblocks `ToolNode`, HITL interrupt, `langchain-anthropic`; do this first
- Stable multi-mission output — fix `RunState` list reducers before adding parallel execution; root cause is state merge logic
- Real subgraph delegation (executor, evaluator as independent `StateGraph` compilations) — current stub is insufficient for production
- Token budget hard gate — `token_budget_remaining` field exists but is never enforced; must gate execution before Phase 3
- Observability wiring — Langfuse `CallbackHandler` + `@observe()` on graph nodes; open Phase 1 item
- CI pipeline — GitHub Actions: ruff + mypy + pytest on push; all tools already installed
- FastAPI service layer — `POST /run`, `GET /run/{id}`, `GET /run/{id}/stream` with SSE
- Docker containerization — Dockerfile + docker-compose for reproducible deployment

**Should have (differentiators):**
- Map-reduce parallel mission execution via `Send()` API — requires stable subgraph execution and `Annotated` reducers first
- Human-in-the-loop (HITL) interrupt via `interrupt()` API — requires persistent checkpointer; enables approve/edit/reject workflows
- Model-strength routing (strong/fast) — stub exists; needs real heuristics based on task type and token budget
- Streaming SSE progress — real-time step-transition events; requires FastAPI layer
- Cross-run audit trend analysis — foundation exists in `run_audit.py`; needs time-series comparison logic

**Defer (v2+):**
- HITL interrupt (valuable but not on critical path to reliability)
- Map-reduce parallel execution (optimization after single-mission stability is proven)
- Stress testing framework (after MVP is deployed and observable)
- Canary deployment support (after FastAPI layer has real traffic)
- End-user UI, public library packaging, fine-tuning, autonomous agent spawning, multi-tenancy, RAG

### Architecture Approach

The target architecture is a three-tier hierarchy: supervisor graph (existing `graph.py`) owns the run lifecycle and routes to specialist subgraphs (new `specialist_executor.py`, `specialist_evaluator.py`) via node-function invocation with isolated `TypedDict` boundaries, wrapped by a FastAPI service layer that compiles the graph once at startup. The key architectural decision is that specialists must NOT share `RunState` keys — they receive a slimmed `TaskHandoff` dict and return a `HandoffResult` dict; the supervisor translates at both boundaries. This preserves the existing `tool_history` as source of truth for args and prevents state bleeding.

**Major components:**
1. **FastAPI service layer** (`agentic_workflows/api/`) — HTTP lifecycle, request validation, SSE streaming; graph compiled once in `lifespan`; `asyncio.to_thread()` for sync graph invocation
2. **Supervisor graph** (`graph.py`) — plan/execute/policy/finalize loop; owns `RunState`, `MissionReport`, `audit_report`; routes to specialist subgraphs but does not execute their logic
3. **Specialist subgraphs** (`specialist_executor.py`, `specialist_evaluator.py`) — independent `StateGraph` with private `ExecutorState`/`EvaluatorState`; compiled once in `LangGraphOrchestrator.__init__()`
4. **Tools layer** (`tools/`) — deterministic computation, no LLM calls; registered in `tools_registry.py`
5. **Observability** (`observability.py`) — `get_langfuse_callback()` + `@observe()` on node methods; both approaches coexist

**Component build order (sequential first, then parallel):**
Steps 1-5 are purely sequential: LangGraph upgrade → SpecialistState TypedDicts → subgraph builders → RunState reducer annotations → `_route_to_specialist` refactor. After step 5, steps 6 (Send parallelism), 7 (observability), and 8 (FastAPI) can proceed in parallel.

### Critical Pitfalls

1. **Plain list fields without reducers break parallel execution** — `tool_history`, `mission_reports`, `memo_events`, `seen_tool_signatures` are plain lists; under `Send`-based parallel missions, last-writer-wins silently drops results. Add `Annotated[list[T], operator.add]` to all parallel-written fields before any `Send` usage. This is the highest-impact risk in the entire roadmap.

2. **Subgraph state bleeding from specialist into parent** — if parent and subgraph share `RunState` keys, specialist internal state floods parent history. Use isolated specialist state schemas with narrow `HandoffResult` output only. Design `_merge_specialist_output()` as the explicit translation point.

3. **LangGraph upgrade introduces silent ToolNode behavior change** — `langgraph-prebuilt>=1.0.1` disabled tool error handling by default (GitHub Issue #6486); `1.0.2` broke `ToolNode.afunc` signature (#6363). Always set `handle_tool_errors=True` explicitly; add an error-injection test that asserts recovery behavior.

4. **SQLite is unsafe for concurrent production requests** — write locking produces `database is locked` under any concurrency. Also has CVE-2025-67644 SQL injection in `<=3.0.0`. Migrate to `langgraph-checkpoint-postgres` for Phase 4; add `PRAGMA journal_mode=WAL` for dev in the interim.

5. **Orchestrator initialized before FastAPI event loop** — creating `LangGraphOrchestrator` at module level breaks async SQLite handles. Always initialize inside FastAPI `lifespan` context manager, never as a module-level singleton.

---

## Implications for Roadmap

Based on combined research, the dependency chain is unambiguous. The suggested phase structure mirrors the existing project phases but is now grounded in specific implementation steps.

### Phase 2: Single-Agent Hardening and LangGraph Upgrade

**Rationale:** The `<1.0` pin is the single blocker for all subsequent work. This phase unblocks everything and stabilizes the existing single-agent behavior before multi-agent complexity is added. Message history compaction must happen here — adding specialist delegation in Phase 3 multiplies message volume and makes compaction harder to retrofit.

**Delivers:** LangGraph 1.0 upgrade, `ToolNode`/`tools_condition` adoption, `langchain-anthropic` integration, token budget tracking wired to provider response, message compaction at 40-message threshold, `Annotated` reducers on all `RunState` list fields (prerequisite for Phase 3 `Send`), CI pipeline with GitHub Actions.

**Addresses features:** LangGraph upgrade (table stakes), CI pipeline (table stakes), stable multi-mission output (table stakes), observability wiring (open Phase 1 item)

**Avoids:** Silent ToolNode error behavior change (set `handle_tool_errors=True`), live providers in CI (enforce `ScriptedProvider`), message history overflow

**Research flag:** LOW — official migration guide exists; behavioral changes in prebuilt 1.0.1/1.0.2 are documented in GitHub issues

---

### Phase 3: Multi-Agent Specialist Delegation

**Rationale:** Only possible after Phase 2 because it requires LangGraph 1.0, `Annotated` reducers, and stable single-mission output. The state boundary design (isolated `TypedDict` per specialist, narrow `HandoffResult`) must be decided and implemented before adding any parallel execution.

**Delivers:** Real `ExecutorState`/`EvaluatorState` TypedDicts, compiled `build_executor_subgraph()`/`build_evaluator_subgraph()`, `_route_to_specialist()` refactor in `graph.py` (invoke compiled subgraph, merge via `HandoffResult`), `Send()`-based parallel mission fan-out (after sequential delegation is stable), model-strength routing with real heuristics.

**Uses:** LangGraph `Send()` API, `TaskHandoff`/`HandoffResult` TypedDicts (existing), `handoff_queue`/`handoff_results` state fields (existing), compiled subgraph pattern from `LangGraphOrchestrator.__init__()`

**Implements:** Supervisor graph (refactored), Specialist subgraphs (new files), Model router (real heuristics)

**Avoids:** State bleeding (isolated schemas), subgraph checkpoint namespace conflicts (compile subgraphs without checkpointer argument), message accumulation from specialist (store in subgraph private state only)

**Research flag:** MEDIUM — shared-vs-isolated state schema choice has downstream consequences; `Send()` + reducer interaction needs integration testing; model routing heuristics need empirical validation

---

### Phase 4: Production Infrastructure

**Rationale:** Only makes sense after Phase 3 delivers a working multi-agent system. The FastAPI layer, PostgreSQL checkpointing, Docker, and CI gates are all production hardening on top of an already-functional system. Stress testing and canary deployment are Phase 4 differentiators.

**Delivers:** FastAPI service layer (`POST /run`, `GET /run/{id}`, SSE streaming), `AsyncPostgresSaver` replacing custom SQLite store, Dockerfile + docker-compose, full CI pipeline (ruff + mypy + pytest + integration), stress testing framework, Langfuse observability wired with full span hierarchy.

**Uses:** `fastapi>=0.115`, `uvicorn>=0.34`, `gunicorn>=23.0`, `langgraph-checkpoint-postgres>=3.0.2`, `psycopg[pool]>=3.2`, `langfuse>=3.0` CallbackHandler

**Avoids:** Orchestrator at module level (use `lifespan`), SQLite under concurrent load (Postgres), `asyncio.to_thread()` for sync graph invocation in async handlers, live provider calls in CI tests

**Research flag:** LOW — all patterns are well-documented; FastAPI + LangGraph production templates exist; only stress testing framework design is custom to this codebase (HIGH research flag for that sub-component)

---

### Phase Ordering Rationale

- **Upgrade before extend:** The `<1.0` pin is a hard prerequisite for `ToolNode`, HITL, and `langchain-anthropic`. No Phase 3 or 4 work is safe without it.
- **Reducers before parallelism:** Adding `Annotated` reducers to `RunState` in Phase 2 is cheap. Not having them when `Send()` arrives in Phase 3 causes silent data loss that is hard to debug post-hoc.
- **Isolated schemas before subgraphs:** The state boundary decision (isolated TypedDicts vs. shared keys) shapes every subsequent multi-agent implementation detail. Making it explicit in Phase 3 start prevents retrofitting.
- **Service layer last:** FastAPI wraps a working system. Building it before the graph is stable inverts priorities and couples API design to an unstable internals.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 3 (subgraph delegation):** State schema choice (isolated vs. shared) has non-trivial downstream consequences; recommend `/gsd:research-phase` for the `Send()` + reducer interaction and subgraph checkpoint propagation pattern
- **Phase 3 (model routing heuristics):** Routing logic based on task complexity classification has no single authoritative pattern; needs empirical validation with real workloads
- **Phase 4 (stress testing framework):** No off-the-shelf framework fits this codebase's failure modes (duplicate tool call injection, cache poisoning, recursion loop detection); needs custom design

Phases with standard patterns (skip research-phase):
- **Phase 2 (LangGraph upgrade):** Official migration guide covers all breaking changes; GitHub issues document exact behavioral changes
- **Phase 4 (FastAPI + SSE + Docker):** Well-documented production templates exist; PostgreSQL checkpointer is documented and open-source

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM-HIGH | LangGraph upgrade path HIGH (official docs + PyPI confirmed); langchain-anthropic and Postgres checkpointer MEDIUM (confirmed on PyPI but not lab-tested against this codebase) |
| Features | MEDIUM-HIGH | Table stakes features verified from official LangGraph docs and GitHub blog; differentiator complexity estimates from practitioner sources |
| Architecture | HIGH | All major patterns from official LangGraph hierarchical agent teams docs and official subgraph docs; component build order cross-validated against pitfalls |
| Pitfalls | HIGH | All critical pitfalls verified against specific GitHub issues (#6363, #6486, #2142, #3587) and CVE records; not inference |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address

- **`langchain-anthropic` minimum version for Claude 3.5/3.7:** Exact minimum version needs validation against `langchain-anthropic` changelog during Phase 2 sprint start; risk is LOW (package is actively maintained)
- **Exact `langgraph==1.0.x` + `langgraph-prebuilt` stable combination:** Research recommends pinning `langgraph==1.0.6, langgraph-prebuilt==1.0.1` during the upgrade sprint before moving to latest; validate this combination against the 208-test suite
- **Model routing heuristics:** No empirical data on which task types benefit from strong vs. fast model; will require a small evaluation sprint in Phase 3
- **Message compaction threshold:** The 40-message threshold is a heuristic from the CLAUDE.md guidance; actual threshold should be tuned based on observed token counts per mission in Phase 2 integration runs
- **Async vs. sync graph invocation:** The current `graph.py` uses synchronous `invoke()`; Phase 4 FastAPI integration via `asyncio.to_thread()` works but `ainvoke()` migration would be cleaner; decision deferred to Phase 4 planning

---

## Sources

### Primary (HIGH confidence)
- [LangGraph v1 migration guide](https://docs.langchain.com/oss/python/migrate/langgraph-v1) — backwards compatibility guarantees, import path changes
- [LangGraph Hierarchical Agent Teams tutorial](https://langchain-ai.github.io/langgraph/tutorials/multi_agent/hierarchical_agent_teams/) — subgraph delegation patterns
- [LangGraph Subgraphs documentation](https://docs.langchain.com/oss/python/langgraph/use-subgraphs) — shared vs. isolated state decision
- [LangGraph Streaming docs (astream_events v2)](https://docs.langchain.com/oss/python/langgraph/streaming) — SSE pattern
- [Langfuse LangGraph integration guide](https://langfuse.com/guides/cookbook/integration_langgraph) — CallbackHandler wiring
- [FastAPI Lifespan Events docs](https://fastapi.tiangolo.com/advanced/events/) — orchestrator initialization pattern
- [FastAPI Docker deployment docs](https://fastapi.tiangolo.com/deployment/docker/) — python:3.12-slim base image recommendation
- [LangGraph persistence docs](https://docs.langchain.com/oss/python/langgraph/persistence) — SQLite not for production
- [GitHub Issue #6363 — ToolNode.afunc signature break in prebuilt 1.0.2](https://github.com/langchain-ai/langgraph/issues/6363)
- [GitHub Issue #6486 — Tool error handling disabled by default after prebuilt 1.0.1](https://github.com/langchain-ai/langgraph/issues/6486)
- [GitHub Issue #2142 — Subgraph state not inserted to persistence db](https://github.com/langchain-ai/langgraph/issues/2142)
- [GitHub Issue #3587 — Unexpected behavior of state reducer in subgraph](https://github.com/langchain-ai/langgraph/issues/3587)
- [CVE-2025-67644 — langgraph-checkpoint-sqlite SQL injection](https://www.cvedetails.com/cve/CVE-2025-67644/)
- [LangGraph GRAPH_RECURSION_LIMIT troubleshooting docs](https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT)
- [LangChain & LangGraph 1.0 announcement](https://blog.langchain.com/langchain-langgraph-1dot0/)
- [LangGraph map-reduce how-to](https://langchain-ai.github.io/langgraphjs/how-tos/map-reduce/)

### Secondary (MEDIUM confidence)
- [Scaling LangGraph Agents: Parallelization, Subgraphs, Map-Reduce Trade-Offs](https://aipractitioner.substack.com/p/scaling-langgraph-agents-parallelization) — parallelism complexity estimates
- [FastAPI LangGraph production template](https://github.com/wassim249/fastapi-langgraph-agent-production-ready-template) — service layer patterns
- [LangGraph best practices (Swarnendu De)](https://www.swarnendu.de/blog/langgraph-best-practices/) — node-level error handling patterns
- [9 Strategies for Stability in Dynamic Multi-Agent Systems (Galileo)](https://galileo.ai/blog/stability-strategies-dynamic-multi-agents) — observability patterns
- [Multi-agent workflows often fail (GitHub Blog)](https://github.blog/ai-and-ml/generative-ai/multi-agent-workflows-often-fail-heres-how-to-engineer-ones-that-dont/) — failure mode taxonomy
- [LangGraph forum: parallel node best practices](https://forum.langchain.com/t/best-practices-for-parallel-nodes-fanouts/1900)

### Tertiary (LOW confidence)
- [Multi-Agent AI Testing Guide 2025 (Zyrix)](https://zyrix.ai/blogs/multi-agent-ai-testing-guide-2025/) — stress testing framework patterns; single source
- [Cost Guardrails for Agent Fleets (Medium)](https://medium.com/@Micheal-Lanham/cost-guardrails-for-agent-fleets-how-to-prevent-your-ai-agents-from-burning-through-your-budget-ea68722af3fe) — token budget enforcement; single practitioner blog

---
*Research completed: 2026-03-02*
*Ready for roadmap: yes*
