# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

---

## Milestone: v1.5 — Production-Grade Agentic Platform

**Shipped:** 2026-03-12
**Phases:** 17 (1–8.1) | **Plans:** 75 | **Commits:** 457

### What Was Built
- Full LangGraph multi-agent orchestration: supervisor/executor/evaluator specialist subgraphs with typed TaskHandoff/HandoffResult delegation
- FastAPI HTTP service (POST /run, GET /run/{id}, SSE streaming) with Postgres persistence, Dockerfile, docker-compose
- GitHub Actions CI: ruff/mypy/pytest with ScriptedProvider — zero live LLM calls in CI
- 5-layer semantic context cascade (SHA-256 → tool bitmask → BM25 → binary vector → float32 cosine) via ONNX fastembed + pgvector, fused with Reciprocal Rank Fusion
- ContextManager: unified eviction, sliding window, per-mission message scoping, injection dedup
- ArtifactStore wired to mission execution path (Postgres persistence)
- LLM output structure stabilization: two-tier compact/full prompts, GBNF grammar, Pydantic handoffs, structural_health metrics
- Hybrid intent classifier: LLM mission classification + deterministic fallback; few-shot directives; per-role token budgets
- Multi-model routing: LlamaCpp alias routing (planner/executor ports), runtime signal ModelRouter, Groq cloud fallback
- graph.py decomposition: 1700-line monolith → structured sub-modules (<600 lines each)
- ContextManager architecture audit: 4 failure modes documented with Phase 8.2 success criteria

### What Worked
- **Wave-based parallel execution**: Plans within a wave ran concurrently, cutting wall time significantly
- **TDD-first pattern**: Wave 0 failing stubs in every multi-plan phase caught integration gaps before implementation
- **Decimal phase insertions**: Urgent fixes (7.1, 7.2, 8.1) slotted cleanly without renumbering downstream phases
- **ScriptedProvider for CI**: Never needed live API keys in CI; integration tests ran deterministically
- **VERIFICATION.md goal-backward check**: Catching "tasks complete but goal not achieved" prevented false completions
- **Two-tier prompt system**: Compact/full tier selection based on `context_size()` elegantly solved phi4 8192-token overflow

### What Was Inefficient
- **ROADMAP.md plan checkbox drift**: Many plan checkboxes remained `[ ]` even after completion; manual sync required at 8.1
- **VALIDATION.md staleness**: Nyquist docs for 7.1 and 7.9 were never updated after tests passed; needed Phase 8.1 cleanup
- **Phase 7.5 ArtifactStore scope creep**: Originally 3 plans, grew to 5; walkthrough plan kept drifting
- **ContextManager complexity**: Grew to 5+ mutation sites and opaque injection policy; required a full audit (8.1) and will need a redesign (8.2)
- **Zombie thread issue (Ollama)**: Required multiple iterations — granular httpx.Timeout, force-close + reinit, provider.close() in finalize — before stabilizing

### Patterns Established
- **Wave 0 stubs**: Every multi-plan phase starts with Wave 0 failing test stubs before any implementation
- **Decimal phases for urgent work**: `X.Y` numbering preserves milestone ordering without renumbering
- **Structural health counters**: All schema/parse failures counted in `audit_report["structural_health"]` — observable after every run
- **Compact/full prompt tiers**: Provider `context_size()` drives tier selection; directives have `## COMPACT` variants
- **ContextManager audit before redesign**: Document failure modes + success criteria before rewriting infrastructure

### Key Lessons
1. **Infrastructure changes need their own audit phase**: ContextManager accumulated 4 failure modes silently over 7 phases. A dedicated audit phase (8.1) caught them before v1.6 planning.
2. **Plan checkboxes in ROADMAP.md degrade fast**: The progress table became the source of truth; plan-level checkboxes need active maintenance or should be dropped.
3. **Semantic context is expensive to get right**: 10 plans for Phase 7.3, then 4 more for dedup fix (7.4) — retrieval systems require iteration budget.
4. **Compact prompts are a first-class concern**: The phi4 8192-token blocker (7.6) should have been anticipated in 7.1 when LlamaCpp support was added.
5. **Dead code accumulates silently**: Two backward-compat shims (`_parse_action_json`, `route_by_intent`) survived 6+ phases with 0 callers. Regular dead-code sweeps save confusion.

### Cost Observations
- Model mix: ~80% sonnet, ~20% haiku (executors on haiku, verifiers/orchestrators on sonnet)
- Sessions: ~30+ across 13 days
- Notable: Parallel wave execution (2 agents simultaneously) cut per-phase wall time by ~40% on two-plan waves

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Commits | Pattern |
|-----------|--------|-------|---------|---------|
| v1.5 | 17 | 75 | 457 | Wave-based parallel, TDD-first, decimal insertions |

### Quality Trends

| Milestone | Tests at Ship | CI Status | Dead Code |
|-----------|---------------|-----------|-----------|
| v1.5 | 1,620+ | ✓ Green | Cleared in 8.1 |

### Architecture Trends

| Milestone | Key Architectural Addition |
|-----------|---------------------------|
| v1.5 | Specialist subgraphs, Postgres, semantic context, multi-model routing, modular graph |
