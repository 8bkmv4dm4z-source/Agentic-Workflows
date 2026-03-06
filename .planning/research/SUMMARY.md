# Project Research Summary

**Project:** Agent Phase0 — Multi-Agent Orchestration Platform
**Domain:** Production graph-based multi-agent orchestration (LangGraph specialist routing, prototype-to-production)
**Researched:** 2026-03-02
**Confidence:** HIGH (core LangGraph/pitfall claims from official docs and verified GitHub issues; stack packages confirmed on PyPI)

## Executive Summary

This project is a LangGraph-based multi-agent orchestration platform at Phase 1.5: a working foundation with 208 passing tests, a 4-node plan/execute/policy/finalize graph, multi-provider support, SQLite checkpointing, and a 9-check post-run auditor. The single most important finding from all four research streams is that one pin — `langgraph<1.0` — is the master blocker for every subsequent phase. Removing it to `>=1.0.9` is explicitly documented as backwards-compatible, the existing 208-test suite serves as the regression harness, and the upgrade unlocks `ToolNode`, `tools_condition`, `langchain-anthropic` native tool calling, and the `interrupt()` HITL API simultaneously. This must be the first, atomic, standalone step before any other work proceeds.

The recommended build sequence is strict: upgrade and harden single-agent execution (Phase 2), then implement real specialist subgraph delegation with typed boundaries (Phase 3), then build the HTTP service layer and production infrastructure (Phase 4). The most dangerous architectural risk across all four files is the same pattern described two different ways: in PITFALLS.md as "subgraph state bleeding" and "plain list fields without reducers," and in ARCHITECTURE.md as "Anti-Pattern 3." The practical consequence is that mission results from parallel runs are silently dropped with no error — tests pass, the auditor may show false positives, but data is gone. Both root causes must be resolved in Phase 2 (add `Annotated[list, operator.add]` reducers to all parallel-written `RunState` fields) before Phase 3 adds any `Send()`-based parallel execution.

The secondary architectural imperative is extracting specialist logic out of `graph.py` (currently ~1700 lines doing everything inline) into isolated `StateGraph` modules before attempting real subgraph delegation. Research is unanimous: the supervisor should orchestrate, not execute. Every target pattern — subgraph delegation, `Send()` map-reduce, `ToolNode` dispatch — depends on the supervisor/specialist boundary being clean and enforced before it is crossed. Establish that boundary in Phase 2 refactoring work, not during Phase 3 feature work.

---

## Key Findings

### Recommended Stack

The existing stack is largely correct and needs only targeted additions. The `langgraph<1.0` upper bound is the only required removal. All other existing pinned packages (`pydantic>=2.12,<3.0`, `openai>=2.0`, `groq>=1.0`, `httpx>=0.28`, `pytest>=8.0`, `ruff>=0.11`, `mypy>=1.10`, `pytest-asyncio>=0.24`) remain unchanged. New packages needed to unlock the full roadmap:

**Core technologies:**
- `langgraph>=1.0.9`: Graph runtime — remove `<1.0` pin; backwards-compatible; confirmed on PyPI
- `langchain-anthropic>=0.3`: Claude provider binding — `ChatAnthropic.bind_tools()` + `ToolNode` eliminates the XML/JSON envelope parsing hacks currently in `graph.py`; the `ScriptedProvider` and existing Groq/Ollama paths are not affected
- `fastapi>=0.115` + `uvicorn>=0.34` + `gunicorn>=23.0`: HTTP service layer — `StreamingResponse` integrates natively with LangGraph's `astream_events()`; compile graph once in `lifespan`, not per-request
- `langgraph-checkpoint-postgres>=3.0.2` + `psycopg[pool]>=3.2`: Production persistence — direct swap for SQLite checkpointer; `AsyncPostgresSaver` requires no graph logic changes; eliminates CVE-2025-67644 and concurrent write locking
- `langfuse>=3.0`: Observability — already in optional deps; promote to default; wire via `CallbackHandler` in graph `invoke()` config for automatic graph-level tracing without code changes to nodes

**Explicitly do not add:** `langchain` (30+ transitive deps, not needed), `instructor` (redundant with `with_structured_output()`), `langgraph-api` / LangGraph Cloud (platform lock-in), `langgraph-swarm` (experimental), LangSmith (SaaS-only), `tiangolo/uvicorn-gunicorn-fastapi` Docker base image (deprecated by its author).

For multi-agent reference only: `langgraph-supervisor>=0.0.5` can be installed as a reference implementation, but the project's existing `TaskHandoff`/`HandoffResult` TypedDicts should be built out directly rather than adopting the library.

### Expected Features

**Must have (table stakes) — in priority order:**
- LangGraph `>=1.0` upgrade — unblocks all downstream capabilities; do as a dedicated, atomic step
- Stable multi-mission output — fix `RunState` list field reducers; root cause of current result dropping
- Real specialist subgraph delegation — executor and evaluator as independent compiled `StateGraph` modules; current inline stub is not production-viable
- Token budget hard gate — `token_budget_remaining` field exists in `RunState` but is never updated or enforced; wire to provider response `usage` before Phase 3 adds specialist subgraph token consumption
- Observability wiring — Langfuse `CallbackHandler` in graph config + `@observe()` on node methods; open Phase 1 item
- CI pipeline — GitHub Actions: ruff + mypy + pytest on push; all tooling installed, only workflow file missing
- FastAPI service layer — POST /run + GET /run/{id} minimum; GET /run/{id}/stream for SSE progress
- Docker containerization — Dockerfile from `python:3.12-slim` + docker-compose; not the deprecated tiangolo image

**Should have (differentiators):**
- Map-reduce parallel mission execution via `Send()` API — requires stable subgraphs and `Annotated` reducers first; documented 137x latency improvement at scale
- Human-in-the-loop (HITL) interrupt via `interrupt()` API — LangGraph >=1.0 feature; requires persistent checkpointer; enables approve/edit/reject mid-run
- Model-strength routing (strong/fast) — `ModelRouter` stub exists; needs real heuristics based on task type, token budget remaining, and specialist type
- Streaming SSE progress — `astream_events(version="v2")`; real-time step-transition events for long runs
- Cross-run audit trend analysis — extends existing `run_audit.py` and `MissionAuditor` (9 checks) to time-series comparison and drift detection
- Architecture documentation — graph visualization, state lifecycle diagrams; explicitly called out as an active project requirement in PROJECT.md

**Defer (v2+):**
- Stress testing framework (build after MVP is deployed and observable)
- Canary deployment support (after FastAPI layer has real traffic and a load balancer)
- End-user UI / frontend (explicitly out of scope per PROJECT.md)
- RAG / vector database retrieval layer (not in scope for any active phase)
- Public library packaging (this is a service, not a reusable framework)
- Autonomous agent spawning / fully dynamic graphs (cost/control risk; use explicit subgraph registration)
- General-purpose multi-tenancy (not justified by current use case)

### Architecture Approach

The target is a three-tier hierarchy: supervisor graph (`graph.py`) owns run lifecycle and routes to specialist subgraphs (new `specialist_executor.py`, `specialist_evaluator.py`) via node-function invocation with isolated `TypedDict` state boundaries, wrapped by a FastAPI service layer that compiles the graph once at startup. The critical invariant is that specialists never write directly to `RunState`: they receive a slimmed `TaskHandoff` dict input, execute within their own private `ExecutorState`/`EvaluatorState`, and return a `HandoffResult` dict. The supervisor translates at both boundaries, preserving the existing convention that `tool_history` (with full args) lives only in `RunState` and is the source of truth.

**Major components:**
1. **FastAPI service layer** (`agentic_workflows/api/`, new) — HTTP lifecycle, request validation, SSE streaming; graph compiled once in `lifespan` context manager; `asyncio.to_thread()` for sync graph invocation in async handlers
2. **Supervisor graph** (`graph.py`, refactored) — plan/execute/policy/finalize loop; owns `RunState`, `MissionReport`, `audit_report`; routes to specialist subgraphs but does not execute their logic
3. **Specialist subgraphs** (`specialist_executor.py`, `specialist_evaluator.py`, new) — independent `StateGraph` with private state schemas (`ExecutorState`, `EvaluatorState`); compiled once in `LangGraphOrchestrator.__init__()`, stored in `self._subgraphs: dict[str, CompiledGraph]`
4. **Tools layer** (`tools/`) — deterministic Python only; no changes required; registered in `tools_registry.py`
5. **Model router** (`model_router.py`) — strong/fast dispatch; stub exists; needs real routing heuristics wired to `token_budget_remaining`
6. **Observability** (`observability.py`) — `get_langfuse_callback()` function returning `CallbackHandler | None`; `@observe()` decorator on graph node methods for provider-level spans with custom metadata

**Component build order — steps 1-5 are purely sequential; steps 6+ can overlap:**

| Step | Component | Prerequisite | Unlocks |
|------|-----------|-------------|---------|
| 1 | LangGraph `>=1.0` pin removal | None | ToolNode, interrupt(), langchain-anthropic |
| 2 | `SpecialistState` TypedDicts (ExecutorState, EvaluatorState) | Step 1 | Subgraph definitions |
| 3 | Specialist subgraph builders | Step 2 + tools_registry | Real delegation |
| 4 | `RunState` reducer annotations (`Annotated[list, operator.add]`) | Step 1 | Safe parallel execution |
| 5 | `_route_to_specialist` refactor in `graph.py` | Steps 2, 3, 4 | Specialist delegation live |
| 6 | `Send()` fan-out for multi-mission parallelism | Step 5 | True parallel missions |
| 7 | Observability wiring (CallbackHandler + @observe) | Step 5 | Full trace visibility |
| 8 | FastAPI lifespan + POST /run + GET /run/{id} | Step 5 | HTTP access |
| 9 | SSE streaming endpoint | Step 8 + ainvoke migration | Real-time progress |
| 10 | Dockerfile + docker-compose | Step 8 | Deployable artifact |
| 11 | GitHub Actions CI | Step 10 | Automated quality gates |
| 12 | Stress testing framework | Step 10 | Load + failure validation |

### Critical Pitfalls

Research identified 5 critical pitfalls (rewrites or production outages if triggered), 7 moderate pitfalls (debugging time or quality degradation), and 2 minor pitfalls. All 5 critical pitfalls are verified against specific GitHub issues, CVE records, or official documentation — not inferred.

1. **Subgraph state bleeding** (Phase 3) — When parent graph and specialist subgraph share `RunState` keys, specialist internal state floods parent history: wrong `tool_history` entries, wrong `active_specialist`, cross-mission data contamination. The existing `RunState` flat TypedDict with no `Annotated` reducers makes this the default failure mode. Prevention: isolated specialist state schemas with `TaskHandoff` input and `HandoffResult` output; never add specialist to parent graph with shared keys. Detection: `len(state["tool_history"])` smaller than expected after multi-agent run; auditor `chain_integrity` failures on runs where logs look correct.

2. **Plain list fields without reducers break parallel execution** (Phase 3) — `tool_history`, `mission_reports`, `memo_events`, `seen_tool_signatures` are plain `list` fields in `RunState` with no reducer annotation. Under `Send()`-based parallel missions, LangGraph uses last-writer-wins; earlier branches' results are silently dropped. Prevention: annotate with `Annotated[list[T], operator.add]` before any `Send()` usage; add integration test asserting both branches' records appear in merged state. This is the root cause of the current "dropped results" flakiness.

3. **LangGraph prebuilt tool error handling behavior change** (Phase 2) — `langgraph-prebuilt>=1.0.1` disabled tool error handling by default (GitHub Issue #6486); `1.0.2` broke `ToolNode.afunc` signature (GitHub Issue #6363). Tool errors that were silently recovered in 0.2 now crash the graph without explicit `handle_tool_errors=True`. Prevention: set `handle_tool_errors=True` on every `ToolNode` instance; add an error-injection test asserting recovery behavior not crash; pin exact prebuilt version during upgrade sprint.

4. **Subgraph checkpoints not persisted unless parent propagates checkpointer** (Phase 3) — Compiling specialist subgraphs with their own `checkpointer` argument causes namespace conflicts; subgraph state is invisible to parent checkpoint stream (GitHub Issue #2142). Checkpoint replay and HITL resume lose specialist-level tool calls. Prevention: compile subgraphs without checkpointer argument (`subgraph.compile()`, not `subgraph.compile(checkpointer=...)`); let parent graph propagate automatically.

5. **SQLite unsafe for concurrent production requests + CVE** (Phase 4) — SQLite write locking produces `OperationalError: database is locked` under any concurrent FastAPI load. `langgraph-checkpoint-sqlite<=3.0.0` also has confirmed SQL injection via metadata filter keys (CVE-2025-67644). Prevention: migrate to `langgraph-checkpoint-postgres` for Phase 4; set `PRAGMA journal_mode=WAL` for dev-only concurrent reads; never share a single SQLite connection across request handlers.

**Top moderate pitfalls to resolve before Phase 3:**
- Message history grows unbounded — implement compaction at 40-message threshold before multi-agent scale multiplies message volume; Groq llama-3.1-8b context window is 8192 tokens
- Token budget fields exist but are never enforced — wire `usage` from provider API responses to `token_budget_used`/`token_budget_remaining` in Phase 2; model router cannot make cost-aware decisions without this signal
- `GraphRecursionError` masks infinite loops — add loop detector: if `step` counter unchanged for 3 consecutive executions, route to `finalize` with `status=failed`; never raise `max_steps` to fix a recursion error (CLAUDE.md convention is correct)

---

## Implications for Roadmap

Research produces a clear, opinionated phase structure. Dependencies are not assumptions — they are documented in the architecture component build order and confirmed by pitfall phase tags. The phases below map directly to the existing Phase 2/3/4 structure in CLAUDE.md.

### Phase 2: Single-Agent Hardening and LangGraph Upgrade

**Rationale:** The `<1.0` pin is the single gate to everything else. This phase must be both the upgrade and the hardening sprint — message compaction, reducer annotations, token budget wiring, loop detection, and CI must all land before Phase 3, because Phase 3's parallel execution will immediately expose any missing mitigations. Attempting multi-agent work with unbounded message history, unreducered list fields, and no CI is a rewrite guarantee.

**Delivers:** LangGraph 1.0 upgrade with `ToolNode`/`tools_condition` adoption and `langchain-anthropic` integration; `Annotated[list, operator.add]` reducers on all parallel-written `RunState` fields; token budget wired to provider response `usage`; message compaction at 40-message threshold; loop detector in graph cycle logic; GitHub Actions CI (ruff + mypy + pytest on push); observability `CallbackHandler` wired in graph config.

**Addresses (from FEATURES.md):** LangGraph `>=1.0` upgrade (table stakes), stable multi-mission output (table stakes — root cause fix), token budget hard gate (table stakes — wiring step), observability wiring (open Phase 1 item), CI pipeline (table stakes)

**Avoids (from PITFALLS.md):** ToolNode error handling behavior change (Pitfall 3 — set `handle_tool_errors=True`), live provider calls in CI (Pitfall 10 — enforce `ScriptedProvider`), message history overflow (Pitfall 7), recursion limit masking loops (Pitfall 8)

**Research flag:** LOW — official migration guide covers all changes; GitHub issues #6363 and #6486 document exact behavioral changes; 208-test suite is the regression harness

---

### Phase 3: Multi-Agent Specialist Delegation

**Rationale:** Only viable after Phase 2 delivers LangGraph 1.0, `Annotated` reducers, and stable single-mission execution. The correct internal order within Phase 3 is: TypedDict design first, subgraph builders second, `_route_to_specialist` refactor third, `Send()` map-reduce last. Attempting `Send()` before sequential single-subgraph delegation is proven correct will trigger the reducer and state bleeding pitfalls simultaneously and produce undiagnosable failures. Model-strength routing is also Phase 3 work but comes after real subgraphs exist to route.

**Delivers:** `ExecutorState`/`EvaluatorState` TypedDicts; compiled `build_executor_subgraph()`/`build_evaluator_subgraph()` stored in `self._subgraphs`; `_route_to_specialist()` refactored to invoke compiled subgraph and merge via `HandoffResult`; `Send()`-based parallel mission fan-out (after sequential delegation is stable and tested); model-strength routing with real heuristics wired to `token_budget_remaining`.

**Uses (from STACK.md):** LangGraph `Send()` API, `TaskHandoff`/`HandoffResult` TypedDicts (existing in `handoff.py`), `handoff_queue`/`handoff_results` state fields (existing), pre-compiled subgraph pattern at `__init__` time

**Implements (from ARCHITECTURE.md):** Supervisor graph (refactored to orchestrate-only), Specialist subgraphs (new files), Model router (real heuristics)

**Avoids (from PITFALLS.md):** State bleeding (Pitfall 1 — isolated schemas), plain list reducers (Pitfall 2 — already added in Phase 2), subgraph checkpoint propagation (Pitfall 4 — compile subgraphs without checkpointer), specialist message accumulation in parent (Pitfall 7 — store specialist messages in subgraph private state only)

**Research flag:** MEDIUM — shared-vs-isolated state schema choice has downstream consequences; `Send()` + reducer interaction requires integration test with parallel branches before declaring stable; model routing heuristics need empirical validation with real workload traces

---

### Phase 4: Production Service Layer

**Rationale:** FastAPI service, PostgreSQL persistence, Docker containerization, and CI quality gates are all production hardening applied to an already-functional multi-agent system. Building the service layer before Phase 3 stabilizes couples API design to unstable internals. The SQLite-to-Postgres migration is the Phase 4 entry gate for safety — any concurrent load testing before this migration will hit `database is locked` errors.

**Delivers:** FastAPI HTTP service (`POST /run`, `GET /run/{id}`, `GET /run/{id}/stream` SSE); `AsyncPostgresSaver` replacing custom SQLite store; Docker containerization (`python:3.12-slim` base); full CI pipeline; Langfuse observability with complete node-level span hierarchy (`@observe()` on all graph node methods, `run_id`/`mission_id` as trace metadata); stress testing framework for cache poisoning, duplicate tool call injection, and recursion loop detection.

**Uses (from STACK.md):** `fastapi>=0.115`, `uvicorn>=0.34`, `gunicorn>=23.0`, `langgraph-checkpoint-postgres>=3.0.2`, `psycopg[pool]>=3.2`, `langfuse>=3.0` `CallbackHandler`, `asyncio.to_thread()` for sync graph invocation in async handlers (or `ainvoke()` migration)

**Avoids (from PITFALLS.md):** Orchestrator at module level (Pitfall 9 — initialize in `lifespan`), SQLite under concurrent load (Pitfall 5 — Postgres), flat Langfuse traces without node hierarchy (Pitfall 6 — `@observe()` on all nodes with `langfuse_context.update_current_trace(metadata={"run_id": ...})`), live provider calls in CI (Pitfall 10)

**Research flag:** LOW for FastAPI + Postgres + Docker (well-documented; production templates exist); HIGH for stress testing framework (custom design required for this codebase's specific failure modes — no standard framework applies directly)

---

### Phase Ordering Rationale

- **Upgrade before extend:** The `<1.0` pin is a hard prerequisite for `ToolNode`, HITL, and `langchain-anthropic`. No Phase 3 or 4 work is safe without this unblock.
- **Reducers before parallelism:** Adding `Annotated` reducers to `RunState` in Phase 2 is cheap; not having them when `Send()` arrives in Phase 3 causes silent data loss that is extremely hard to diagnose post-hoc. This is the highest-impact preparatory step in the entire roadmap.
- **Isolated schemas before subgraphs:** The state boundary decision (isolated TypedDicts vs. shared keys) shapes every subsequent multi-agent implementation detail. Deciding and enforcing it at Phase 3 start prevents expensive retrofitting later.
- **Service layer last:** FastAPI wraps a working system. Building it before the graph internals are stable inverts priorities and creates API-to-unstable-internals coupling. The async event loop initialization pitfall (Pitfall 9) also only matters when there is a service to initialize.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 3 (subgraph state schema design):** The `TaskHandoff`/`HandoffResult` TypedDicts in `handoff.py` are a starting sketch. The exact fields, what the supervisor copies vs. derives, and how `_merge_specialist_output()` updates `RunState` without triggering the reducer issues need careful design before implementation. Recommend a design review against the official LangGraph subgraph docs before writing code.
- **Phase 3 (model routing heuristics):** Routing by task complexity has no single authoritative pattern; needs empirical evaluation with real workload traces from Phase 2 integration runs. Defer the routing logic to late Phase 3 after real subgraphs generate actual token usage data.
- **Phase 4 (stress testing framework):** AgenTracer-style fault injection (counterfactual replay, cache poisoning scenario, duplicate tool call injection, recursion loop detection validation) is custom to this codebase. No standard framework applies. Needs a design spike before implementation.

Phases with standard patterns (research-phase not required):
- **Phase 2 (LangGraph upgrade):** Official migration guide is comprehensive; GitHub issues document exact behavioral changes in specific prebuilt versions; existing 208-test suite is the complete regression harness.
- **Phase 2 (CI pipeline):** GitHub Actions + ruff + mypy + pytest is a standard, well-documented pattern; all tooling already installed and configured.
- **Phase 4 (FastAPI + Postgres + Docker):** All patterns are well-documented with production reference implementations. `AsyncPostgresSaver` checkpointer swap requires no graph logic changes — it is a constructor argument change only.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM-HIGH | LangGraph 1.0.9 upgrade path is HIGH confidence (PyPI-confirmed, officially backwards-compatible). `langchain-anthropic` MEDIUM: package is active but exact minimum version for Claude 3.5/claude-opus-4-6 needs changelog validation. FastAPI + Postgres patterns MEDIUM: industry standard but not lab-tested against this specific codebase. |
| Features | MEDIUM-HIGH | Table stakes features derived from official LangGraph docs and GitHub blog (HIGH). Differentiator complexity estimates (137x map-reduce speedup, routing heuristics) from practitioner sources (MEDIUM). Anti-features validated against PROJECT.md scope statements (HIGH). |
| Architecture | HIGH | All major patterns verified against official LangGraph hierarchical agent teams docs, subgraph docs, streaming docs, and FastAPI lifespan docs. Component build order cross-validated against pitfall phase tags — no conflicts found. |
| Pitfalls | HIGH | All 5 critical pitfalls verified against named GitHub issues (with issue numbers), CVE records, or official docs. Not inference — these are documented bugs in exact versions in play. |

**Overall confidence:** HIGH

### Gaps to Address

- **`langchain-anthropic` minimum version for Claude models:** Research recommends `>=0.3` but the exact minimum for Claude 3.5 / claude-opus-4-6 compatibility needs validation against the `langchain-anthropic` changelog at Phase 2 sprint start. Risk is LOW — package is actively maintained.
- **Exact `langgraph-prebuilt` stable version combination:** PITFALLS.md recommends pinning `langgraph==1.0.6, langgraph-prebuilt==1.0.1` during the upgrade sprint before moving to latest to avoid the `afunc` signature break in 1.0.2. Validate this combination against the 208-test suite before unpinning.
- **`RunState` reducer migration impact on sequential tests:** Adding `Annotated[list, operator.add]` reducers changes how LangGraph merges state even in sequential runs (should be identity for single-branch execution, but this must be confirmed). Run the full test suite after each reducer annotation is added individually, not all at once.
- **Async vs. sync graph invocation for FastAPI:** The current `graph.py` uses synchronous `invoke()`; Phase 4 integration via `asyncio.to_thread()` is the short-path; `ainvoke()` migration would be cleaner for SSE streaming. Decision deferred to Phase 4 planning — both approaches are valid.
- **Message compaction threshold tuning:** The 40-message threshold referenced in CLAUDE.md guidance is a heuristic. Actual token counts per mission depend on provider and mission complexity. Measure token usage in Phase 2 integration runs and tune the threshold before Phase 3 multiplies message volume.

---

## Sources

### Primary (HIGH confidence)
- [LangGraph v1 migration guide](https://docs.langchain.com/oss/python/migrate/langgraph-v1) — backwards compatibility guarantees, import changes
- [LangChain & LangGraph 1.0 announcement](https://blog.langchain.com/langchain-langgraph-1dot0/) — official version confirmation
- [LangGraph Hierarchical Agent Teams tutorial](https://langchain-ai.github.io/langgraph/tutorials/multi_agent/hierarchical_agent_teams/) — supervisor/specialist patterns
- [LangGraph Subgraphs documentation](https://docs.langchain.com/oss/python/langgraph/use-subgraphs) — shared vs. isolated state decision
- [LangGraph persistence docs — SQLite not for production](https://docs.langchain.com/oss/python/langgraph/persistence) — checkpointer guidance
- [LangGraph streaming docs — astream_events v2](https://docs.langchain.com/oss/python/langgraph/streaming) — SSE streaming pattern
- [LangGraph GRAPH_RECURSION_LIMIT troubleshooting](https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT) — loop detection guidance
- [LangGraph map-reduce how-to](https://langchain-ai.github.io/langgraphjs/how-tos/map-reduce/) — Send() API and reducer requirement
- [LangGraph Command for multi-agent routing](https://blog.langchain.com/command-a-new-tool-for-multi-agent-architectures-in-langgraph/) — routing patterns
- [LangGraph interrupt() HITL blog](https://blog.langchain.com/making-it-easier-to-build-human-in-the-loop-agents-with-interrupt/) — HITL interrupt pattern
- [Langfuse LangGraph integration guide](https://langfuse.com/guides/cookbook/integration_langgraph) — CallbackHandler wiring
- [FastAPI lifespan events](https://fastapi.tiangolo.com/advanced/events/) — orchestrator initialization pattern
- [FastAPI Docker deployment docs](https://fastapi.tiangolo.com/deployment/docker/) — python:3.12-slim, deprecated base image warning
- [langgraph-checkpoint-postgres PyPI — v3.0.2](https://pypi.org/project/langgraph-checkpoint-postgres/) — production checkpointer confirmation
- [langchain-anthropic PyPI](https://pypi.org/project/langchain-anthropic/) — package activity confirmation
- [GitHub Issue #6363 — ToolNode.afunc signature break in langgraph-prebuilt 1.0.2](https://github.com/langchain-ai/langgraph/issues/6363)
- [GitHub Issue #6486 — tool error handling disabled by default in prebuilt 1.0.1](https://github.com/langchain-ai/langgraph/issues/6486)
- [GitHub Issue #2142 — Subgraph state not inserted to persistence DB](https://github.com/langchain-ai/langgraph/issues/2142)
- [GitHub Issue #3587 — Unexpected behavior of state reducer in subgraph](https://github.com/langchain-ai/langgraph/issues/3587)
- [CVE-2025-67644 — langgraph-checkpoint-sqlite SQL injection](https://www.cvedetails.com/cve/CVE-2025-67644/)
- [LangGraph forum: best practices for parallel nodes (fanouts)](https://forum.langchain.com/t/best-practices-for-parallel-nodes-fanouts/1900)

### Secondary (MEDIUM confidence)
- [Scaling LangGraph Agents: Parallelization, Subgraphs, Map-Reduce Trade-Offs](https://aipractitioner.substack.com/p/scaling-langgraph-agents-parallelization) — parallel mission patterns, 137x speedup claim
- [FastAPI LangGraph production-ready template](https://github.com/wassim249/fastapi-langgraph-agent-production-ready-template) — service layer reference implementation
- [Multi-agent workflows often fail (GitHub Blog)](https://github.blog/ai-and-ml/generative-ai/multi-agent-workflows-often-fail-heres-how-to-engineer-ones-that-dont/) — failure mode analysis
- [9 Strategies for Stability in Dynamic Multi-Agent Systems (Galileo)](https://galileo.ai/blog/stability-strategies-dynamic-multi-agents) — observability and stability patterns
- [Guardrails for agentic orchestration (Camunda 2026)](https://camunda.com/blog/2026/01/guardrails-and-best-practices-for-agentic-orchestration/) — cost and control guardrails
- [Managing context history in agentic systems (Medium)](https://medium.com/@thakur.rana/managing-context-history-in-agentic-systems-with-langgraph-3645610c43fe) — message compaction patterns
- [LangGraph map-reduce with Send API in Python (Medium)](https://medium.com/ai-engineering-bootcamp/map-reduce-with-the-send-api-in-langgraph-29b92078b47d) — Send() usage patterns
- [LangGraph forum: parallel message merge issues](https://forum.langchain.com/t/seeking-help-with-some-merge-message-issues-when-langgraph-is-called-in-parallel/3007) — reducer behavior confirmation

### Tertiary (LOW confidence)
- [Multi-Agent AI Testing Guide 2025 (Zyrix)](https://zyrix.ai/blogs/multi-agent-ai-testing-guide-2025/) — stress testing framework patterns; single source, not cross-verified
- [Cost guardrails for agent fleets (Medium)](https://medium.com/@Micheal-Lanham/cost-guardrails-for-agent-fleets-how-to-prevent-your-ai-agents-from-burning-through-your-budget-ea68722af3fe) — token budget enforcement; single practitioner blog
- [Streaming AI agent with FastAPI & LangGraph (DEV Community)](https://dev.to/kasi_viswanath/streaming-ai-agent-with-fastapi-langgraph-2025-26-guide-1nkn) — async lifecycle pitfall; needs validation against current FastAPI version

---
*Research completed: 2026-03-02*
*Ready for roadmap: yes*
