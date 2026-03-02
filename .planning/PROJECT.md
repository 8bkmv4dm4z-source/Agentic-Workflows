# Agent Phase0 — Multi-Agent Orchestration Platform

## What This Is

A LangGraph-based agent orchestration platform being built from a working foundation to a production-ready multi-agent system. The system routes tasks to specialist agents (supervisor, executor, evaluator) that execute via tool chains, with a unified state machine governing plan → execute → policy → finalize flow. Target: a deployable service handling generic-to-specialized tasks by routing to the right specialist with the right context.

## Core Value

A specialist-routing multi-agent system that reliably executes multi-mission workloads end-to-end — with the architecture understood deeply enough to stress test, evolve, and deploy with confidence.

## Requirements

### Validated

- ✓ LangGraph graph-based orchestration (plan → execute → policy → finalize) — existing
- ✓ Multi-provider support (OpenAI, Groq, Ollama) via ChatProvider protocol — existing
- ✓ Tool base class + registry pattern — existing
- ✓ RunState TypedDict with ensure_state_defaults() at every node — existing
- ✓ Sub-task parsing and StructuredPlan from numbered prompts — existing
- ✓ Mission tracking (MissionReport) and post-run audit (MissionAuditor, 9 checks) — existing
- ✓ MemoizationPolicy enforcing memo-before-write invariant — existing
- ✓ 208 unit + integration tests — existing
- ✓ Specialist directives (supervisor, executor, evaluator) — existing
- ✓ Handoff schema (TaskHandoff/HandoffResult TypedDicts) — existing
- ✓ Model router stub (strong/fast routing) — existing

### Active

- [ ] Real subgraph delegation — specialists run as independent LangGraph subgraphs, not stubs
- [ ] Stable multi-mission output — parallel missions complete reliably without dropped results
- [ ] LangGraph upgrade — remove <1.0 pin, migrate to ToolNode/tools_condition patterns
- [ ] FastAPI service layer — HTTP endpoint to submit missions and retrieve results
- [ ] Observability wiring — @observe() on run/provider path, Langfuse integration
- [ ] Containerization — Dockerfile + docker-compose for local and cloud deployment
- [ ] CI pipeline — automated lint, typecheck, and test on push
- [ ] Stress testing framework — load patterns, failure injection, recovery validation
- [ ] Architecture documentation — deep walkthrough of graph flow, state lifecycle, routing decisions

### Out of Scope

- End-user UI — internal team tooling only; no frontend needed
- Public library/framework — not packaging for external developers to import
- Fine-tuning or model training — uses off-the-shelf LLM providers only

## Context

- Current branch: `p1-stable-sub-task-parsing` (208 tests green, ruff clean)
- Phase 1 (Foundation) mostly complete — two open items: `@observe()` not wired on run/provider path; README depth below target
- Phase 2 (Single-agent) not started — blocking: `langgraph<1.0` pin prevents ToolNode/tools_condition/langchain-anthropic usage
- Phase 3 (Multi-agent) scaffolded only — specialist directives exist, handoff TypedDicts exist, model-router stub in graph.py, but no real subgraph execution
- Phase 4 (Production) largely pending — no FastAPI, no containers, no CI
- This is a learning-driven build: each phase should produce deep understanding of flow and architecture, not just working code

## Constraints

- **Tech Stack**: Python 3.12 | LangGraph | Pydantic 2.12 | Anthropic/OpenAI/Groq | SQLite (dev)
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
| langgraph<1.0 pin | Was safe when set; now blocks Phase 2 migration | ⚠️ Revisit |
| Specialist routing as subgraph delegation | Enables true parallel multi-agent execution | — Pending |

---
*Last updated: 2026-03-02 after initialization*
