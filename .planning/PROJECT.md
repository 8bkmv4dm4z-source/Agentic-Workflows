# Agent Phase0 — Multi-Agent Orchestration Platform

## What This Is

A production-grade LangGraph multi-agent orchestration platform. The system routes missions to specialist agents (supervisor, executor, evaluator) that execute via a 15+ tool chain, with a unified state machine governing plan → execute → policy → finalize flow. Deployed as a FastAPI HTTP service with Postgres persistence, Docker Compose, GitHub Actions CI, and a 5-layer semantic context system (SHA-256 → BM25 → pgvector cosine) for cross-run mission recall.

## Core Value

A specialist-routing multi-agent system that reliably executes multi-mission workloads end-to-end — with the architecture understood deeply enough to stress test, evolve, and deploy with confidence.

## Requirements

### Validated

- ✓ LangGraph graph-based orchestration (plan → execute → policy → finalize) — existing
- ✓ Multi-provider support (OpenAI, Groq, Ollama, LlamaCpp) via ChatProvider protocol — existing
- ✓ Tool base class + registry pattern (15+ tools) — existing
- ✓ RunState TypedDict with ensure_state_defaults() at every node — existing
- ✓ Sub-task parsing and StructuredPlan from numbered prompts — existing
- ✓ Mission tracking (MissionReport) and post-run audit (MissionAuditor, 9 checks) — existing
- ✓ MemoizationPolicy enforcing memo-before-write invariant — existing
- ✓ Specialist directives (supervisor, executor, evaluator) — existing
- ✓ Handoff schema (TaskHandoff/HandoffResult Pydantic BaseModels) — existing
- ✓ LangGraph upgrade — removed <1.0 pin, ToolNode/tools_condition, Annotated reducers — v1.5
- ✓ Real subgraph delegation — executor/evaluator as independent StateGraphs with TaskHandoff — v1.5
- ✓ Stable multi-mission output — Annotated list reducers, MissionAuditor chain_integrity — v1.5
- ✓ FastAPI service layer — POST /run, GET /run/{id}, GET /run/{id}/stream (SSE) — v1.5
- ✓ Observability — Langfuse CallbackHandler, @observe() on run/provider path — v1.5
- ✓ Containerization — Dockerfile + docker-compose (API + Postgres) — v1.5
- ✓ CI pipeline — GitHub Actions: ruff/mypy/pytest with ScriptedProvider — v1.5
- ✓ Postgres persistence — AsyncPostgresSaver, PostgresMemoStore, PostgresRunStore — v1.5
- ✓ ContextManager — unified eviction, per-mission message scoping, summarization — v1.5
- ✓ Semantic context system — 5-layer cascade retrieval, ONNX fastembed, RRF fusion — v1.5
- ✓ ArtifactStore — artifact persistence to Postgres, wired to mission execution path — v1.5
- ✓ LLM output structure stabilization — two-tier prompts, GBNF grammar, Pydantic handoffs, structural_health — v1.5
- ✓ Intent classifier — LLM-based mission type classification, few-shot directives, token budgets — v1.5
- ✓ Multi-model routing — LlamaCpp alias routing, runtime signal ModelRouter, Groq cloud fallback — v1.5
- ✓ Dynamic context querying — query_context tool, memory consolidation, schema compliance metrics — v1.5
- ✓ graph.py decomposition — orchestration/langgraph/ sub-modules, no file >600 lines — v1.5
- ✓ Architecture documentation — ADR log, phase walkthroughs, Before/After progression — v1.5

### Active

- [ ] ContextManager sub-task amnesia fix — sub-tasks lose context mid-mission; need sub-task-scoped context slots
- [ ] Result-to-subtask affiliation — tool results not reliably linked to originating sub-task; affiliation schema needed
- [ ] Injection policy opacity — ContextManager injection logic is opaque; need declarative policy layer
- [ ] Scattered state mutation — ContextManager state mutated in 5+ locations; centralize to single coordinator

### Out of Scope

- End-user UI — internal team tooling only; no frontend needed
- Public library/framework — not packaging for external developers to import
- Fine-tuning or model training — uses off-the-shelf LLM providers only

## Context

- Shipped v1.5: 17 phases (1–8.1), 75 plans, 21/21 requirements, 21,861 LOC Python
- 1,620+ tests passing (unit + integration), ruff clean, mypy passing
- ContextManager architecture audit complete — 4 failure modes documented in `08.1-context-audit.md`
- Phase 8.2 will address ContextManager redesign (sub-task scoping, affiliation schema, policy layer)
- Intel Arc iGPU: SYCL/IPEX-LLM path preferred over Ollama+Vulkan (upstream broken)

## Constraints

- **Tech Stack**: Python 3.12 | LangGraph | Pydantic 2.12 | Anthropic/OpenAI/Groq/LlamaCpp | SQLite (dev) / Postgres (prod)
- **Phase isolation**: `core/` (P0) and `orchestration/` (P1) must not cross-import
- **Recursion limit**: max_steps × 3 — do not raise max_steps to fix recursion errors
- **Tool writes**: heavy deterministic writes require memoize call before write_file
- **Bug fixes**: every bug fix must include a regression test
- **Directives**: never overwrite `directives/` files without explicit request

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| LangGraph as orchestration layer | Industry-standard graph runtime with state management, retry, checkpoints | ✓ Good |
| ChatProvider Protocol pattern | Unified interface decouples orchestration from model vendor | ✓ Good |
| TypedDict for RunState (not Pydantic BaseModel) | LangGraph native; state repair via ensure_state_defaults() at each node | ✓ Good |
| tool_history as source of truth for args | tool_results in mission_reports intentionally excludes args | ✓ Good |
| LangGraph >=1.0.9 upgrade | Removed <1.0 pin; ToolNode/tools_condition replace XML envelope parser | ✓ Good |
| Specialist routing as subgraph delegation | Enables true parallel multi-agent execution via TaskHandoff/HandoffResult | ✓ Good |
| 5-layer cascade retrieval (SHA-256→BM25→pgvector) | Deterministic layers short-circuit before expensive vector search | ✓ Good |
| Two-tier compact/full prompts | Compact tier fits 8192-token contexts (phi4); full tier for quality | ✓ Good |
| graph.py decomposition into sub-modules | Eliminated 1700-line monolith; each module <600 lines | ✓ Good |
| ContextManager sliding window + injection dedup | Bounded message growth; single injection per run | ⚠️ Revisit (4 failure modes found) |

---
*Last updated: 2026-03-12 after v1.5 milestone*
