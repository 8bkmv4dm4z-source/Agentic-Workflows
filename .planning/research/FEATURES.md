# Feature Landscape

**Domain:** Production multi-agent orchestration platform (LangGraph-based specialist routing)
**Researched:** 2026-03-02
**Overall confidence:** MEDIUM-HIGH (LangGraph-specific claims from official docs; ecosystem patterns from multiple verified sources)

---

## Table Stakes

Features that must exist or the system is unreliable, untestable, or undeployable. Missing any of these means the system cannot be called production-grade.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Real subgraph delegation | Without independent subgraph execution, "multi-agent" is just a name. Specialists must run as isolated LangGraph subgraphs with their own state schemas. | High | Currently stub only. This is the blocker for Phase 3. Shared-vs-different state schema choice has downstream consequences. |
| Stable multi-mission output | Parallel missions that drop results silently are worse than sequential. If the system can't reliably complete a multi-mission run, nothing else matters. | High | Known flaky in current state. Root cause in state merge/append logic for concurrent updates. |
| LangGraph >=1.0 upgrade | `ToolNode`, `tools_condition`, `interrupt()`, and `langchain-anthropic` are all blocked by the `<1.0` pin. The upgrade unlocks the modern prebuilt patterns and the HITL interrupt API. | Medium | Python 3.9 dropped in LangGraph 1.0; project already on 3.12. Import paths change. |
| Persistent state (Postgres checkpointer) | SQLite is dev-only. Production pause/resume, HITL, and crash recovery all require a durable checkpointer. PostgresSaver is the reference production backend. | Medium | `langgraph-checkpoint-postgres` is open-source and optimized. Redis is an alternative for sub-millisecond retrieval at high throughput. |
| Typed state schemas at subgraph boundaries | Without typed state, parent-to-subgraph handoffs produce silent data loss or corrupt state. TypedDicts must be explicit at every boundary. | Medium | Already using TypedDict for RunState; must extend this discipline to subgraph-level schemas. |
| Per-node error handling and retry policy | Multi-agent systems amplify failure surfaces. Any node that talks to an LLM provider can fail. Must have node-level try/except and `retry_policy` for transient errors. | Medium | LangGraph retry_policy retries only the failing branch, not the whole superstep. |
| Token budget enforcement (hard limit) | Without budget controls, token runaway and tool-call loops are inevitable. The budget field exists in RunState; it must actually gate execution. | Medium | `token_budget_remaining` field exists but is not enforced as a hard gate today. |
| Observability wiring | You cannot debug what you cannot see. `@observe()` on the run/provider path and structured trace output are prerequisites for diagnosing multi-agent failures in any non-trivial run. | Medium | Langfuse integration is the chosen path. `@observe()` not yet wired on run/provider path — this is an open Phase 1 item. |
| CI pipeline (lint, typecheck, test on push) | Without CI, the 208-test baseline has no enforcement guarantee. Any commit can silently break the system. | Low | Standard GitHub Actions. Ruff + mypy + pytest. Already have the test harness; just need the workflow file. |
| FastAPI service layer (submit + retrieve) | The system is a CLI-only tool today. A deployable service requires at minimum a POST endpoint to submit missions and a GET endpoint to retrieve results by run_id. | Medium | Server-Sent Events (SSE) streaming is the 2025 pattern for real-time agent progress. |
| Docker containerization | Without a container, "production deployment" means "it works on my machine." Dockerfile + docker-compose is the minimum reproducible deployment artifact. | Low-Medium | Standard Python 3.12 base image. Env var injection for provider keys. |
| Regression test for every bug fix | This is explicitly in the project conventions and must not slip. As multi-agent complexity grows, a test suite that doesn't track regressions becomes worthless fast. | Low | Already a stated convention; enforcement is the challenge at scale. |

---

## Differentiators

Features that provide quality or competitive advantage. Not expected by default, but meaningfully increase system value.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Map-reduce parallel mission execution | Parallel subgraph execution via LangGraph Send API yields order-of-magnitude latency improvements (observed 137x speedup in documented benchmarks). Sequential multi-mission is a baseline; parallel is a differentiator. | High | Requires stable subgraph execution first. `max_concurrency` config controls blast radius. Entire superstep is transactional — if one branch fails, no updates applied. |
| Human-in-the-loop (HITL) interrupt | The modern `interrupt()` API (LangGraph >=1.0) allows pausing mid-node on runtime conditions, not just at node boundaries. Enables approve/edit/reject workflows without polling. | High | Requires persistent checkpointer. Node re-executes from start on resume — pre-interrupt logic must be idempotent. |
| Model-strength routing (strong/fast) | Routing heavy reasoning tasks to a capable model and lightweight tasks to a fast/cheap model cuts cost without sacrificing quality. The stub exists; making it data-driven is the differentiator. | Medium | ModelRouter stub already in graph.py. Needs real routing heuristics based on task type, token budget, and specialist type. |
| Streaming progress via SSE | Real-time step-transition events and intermediate results allow meaningful progress visibility for long-running multi-mission workloads. LangGraph's `get_stream_writer()` makes clean structured progress events possible from any node. | Medium | Requires FastAPI layer first. Standard 2025-26 UX expectation for agent services. |
| Cross-run audit summary | The existing `run_audit.py` and `MissionAuditor` (9 checks) give post-run correctness validation. Extending this to cross-run trend analysis (drift detection, quality degradation) is a differentiator for production monitoring. | Medium | Foundation already exists. Needs time-series storage and comparison logic. |
| Stress testing framework | Systematic failure injection (agent termination, latency injection, corrupt messages), load pattern testing, and recovery validation. Distinguishes a hardened system from one that only works in happy-path demos. | High | AgenTracer pattern (counterfactual replay + fault injection) is the research reference. Custom for this codebase. |
| Canary deployment support | Progressive rollouts (5% traffic → 25% → 100%) catch quality degradation before it affects all traffic. Relevant once FastAPI layer exists and the system handles real load. | High | Requires load balancer, traffic splitting, and baseline metrics. Deferred until FastAPI + containers are stable. |
| Architecture documentation (deep walkthrough) | For a learning-driven build, a well-documented graph flow, state lifecycle, and routing decision explanation is an explicit project goal — not just nice-to-have. | Low-Medium | Explicitly called out in PROJECT.md as an active requirement. Includes graph visualization and state lifecycle diagrams. |

---

## Anti-Features

Features to explicitly NOT build in the current roadmap horizon. Building these prematurely creates waste, complexity, or scope risk.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| End-user UI / frontend | Explicitly out of scope per PROJECT.md. Internal team tooling only. A frontend before the backend is stable inverts priorities. | CLI for dev; SSE-streaming FastAPI endpoint is sufficient for integration consumers. |
| Public library / framework packaging | This is a service, not a reusable library. Packaging for external developers (PyPI, versioned SDK) adds maintenance surface with no current benefit. | Keep as an internal service. Document the API contract via OpenAPI schema generated by FastAPI. |
| Fine-tuning or model training | The system uses off-the-shelf providers. Custom model training is a separate discipline with separate infrastructure requirements. | Use prompt engineering, directives, and model routing to optimize quality within existing providers. |
| Autonomous multi-agent spawning (fully dynamic graphs) | Unbounded agent spawning without explicit control creates runaway cost, debugging opacity, and safety risks. Gartner warns 40%+ of agentic projects are canceled due to cost/control failures. | Use explicit subgraph registration with typed handoff schemas. Route by specialist type, not by spawning arbitrary new agents. |
| General-purpose multi-tenancy | Multi-tenant isolation (per-customer data, billing, rate limits) is a significant infrastructure investment not justified by the current use case. | Single-tenant or small-team deployment. Thread-scoped checkpoints provide sufficient isolation for internal use. |
| Vector database / RAG retrieval layer | Not in scope for any active phase. Adding RAG before the agent routing layer is stable is premature optimization. | If specialist agents need context, pass it via the handoff schema or tool inputs. Defer RAG to a future phase with explicit requirements. |
| Prompt management UI | Version-controlled directives in `directives/` are sufficient for this stage. A GUI for prompt management adds tooling overhead before the underlying system is stable. | Keep directives as markdown files in version control. Add diff review to CI if prompt drift becomes a concern. |

---

## Feature Dependencies

```
LangGraph >=1.0 upgrade
  → ToolNode / tools_condition patterns (unblocked)
  → interrupt() HITL API (unblocked)
  → langchain-anthropic integration (unblocked)

Stable multi-mission output
  → Map-reduce parallel execution (requires stable state merge first)
  → Cross-run audit trend analysis (need reliable run completion)

Persistent state (Postgres checkpointer)
  → HITL interrupt (pause/resume requires durable state)
  → Canary deployment (needs thread history across processes)

Real subgraph delegation
  → Model-strength routing (needs real subgraphs to route)
  → Map-reduce parallel mission execution
  → HITL interrupt at specialist boundary

Token budget enforcement (hard gate)
  → Cost guardrails (enforcement depends on budget gate)
  → Model-strength routing (budget signal informs routing decision)

FastAPI service layer
  → Streaming progress via SSE
  → Canary deployment support
  → Docker containerization (service to containerize)

CI pipeline
  → All other features (gate on regressions before merging)
  → Architecture documentation (publish on CI pass)
```

---

## MVP Recommendation

The MVP for "deployable specialist-routing system" must solve in priority order:

1. **LangGraph >=1.0 upgrade** — unblocks everything else; do this first as a dedicated migration step
2. **Stable multi-mission output** — fix state merge for parallel missions; verify with existing test harness
3. **Real subgraph delegation** — supervisors, executors, evaluators run as real subgraphs
4. **Token budget hard gate** — prevents runaway cost in real workloads
5. **Observability wiring** — `@observe()` on run/provider path; Langfuse or equivalent
6. **CI pipeline** — GitHub Actions: ruff + mypy + pytest on push
7. **FastAPI service layer** — POST /run + GET /run/{id} with SSE streaming
8. **Docker containerization** — Dockerfile + docker-compose

Defer to post-MVP:
- **HITL interrupt** — valuable but not on the critical path for reliability
- **Map-reduce parallel execution** — optimization after single-mission stability proven
- **Model-strength routing** — routing logic after real subgraphs work
- **Stress testing framework** — after MVP is deployed and observable
- **Canary deployment** — after FastAPI layer has real traffic

---

## Phase-Specific Guidance

| Phase Topic | Feature Group | Priority | Research Flag |
|-------------|--------------|----------|---------------|
| Phase 2: Single-agent | LangGraph >=1.0 upgrade, ToolNode migration | Blocking | LOW — official migration guide exists |
| Phase 2: Single-agent | Stable multi-mission output | Blocking | LOW — root cause likely in state merge logic |
| Phase 3: Multi-agent | Real subgraph delegation | Core | MEDIUM — shared vs. different state schema choice is non-trivial |
| Phase 3: Multi-agent | Token budget hard gate | Core | LOW — field exists, need enforcement logic |
| Phase 3: Multi-agent | Model-strength routing | Differentiator | MEDIUM — heuristics for task classification need research |
| Phase 3: Multi-agent | Map-reduce parallel execution | Differentiator | MEDIUM — Send API + max_concurrency + transactional superstep semantics |
| Phase 4: Production | Persistent state (Postgres) | Blocking | LOW — PostgresSaver is documented and open-source |
| Phase 4: Production | FastAPI + SSE streaming | Core | LOW — well-documented pattern, production templates exist |
| Phase 4: Production | CI pipeline | Core | LOW — standard GitHub Actions |
| Phase 4: Production | Docker containerization | Core | LOW — standard Python image |
| Phase 4: Production | Stress testing framework | Differentiator | HIGH — needs custom design for this codebase's failure modes |
| Phase 4: Production | Observability wiring | Table stakes | MEDIUM — Langfuse integration path exists but @observe() not yet wired |

---

## Sources

- [LangGraph Multi-Agent Orchestration (Latenode)](https://latenode.com/blog/ai-frameworks-technical-infrastructure/langgraph-multi-agent-orchestration/langgraph-multi-agent-orchestration-complete-framework-guide-architecture-analysis-2025) — MEDIUM confidence (analysis blog, references official patterns)
- [LangGraph: Agent Orchestration Framework (official)](https://www.langchain.com/langgraph) — HIGH confidence (official LangChain/LangGraph site)
- [Multi-agent workflows often fail (GitHub Blog)](https://github.blog/ai-and-ml/generative-ai/multi-agent-workflows-often-fail-heres-how-to-engineer-ones-that-dont/) — MEDIUM confidence (engineering blog from GitHub)
- [Scaling LangGraph Agents: Parallelization, Subgraphs, and Map-Reduce Trade-Offs](https://aipractitioner.substack.com/p/scaling-langgraph-agents-parallelization) — MEDIUM confidence (practitioner analysis)
- [LangGraph Subgraphs docs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs) — HIGH confidence (official docs)
- [LangGraph Best Practices (Swarnendu De)](https://www.swarnendu.de/blog/langgraph-best-practices/) — MEDIUM confidence (practitioner blog referencing official patterns)
- [Making it easier to build HITL agents with interrupt (LangChain blog)](https://blog.langchain.com/making-it-easier-to-build-human-in-the-loop-agents-with-interrupt/) — HIGH confidence (official LangChain blog)
- [LangGraph v0.2 / Checkpointer libraries](https://blog.langchain.com/langgraph-v0-2/) — HIGH confidence (official release blog)
- [Redis LangGraph Checkpoint 0.1.0](https://redis.io/blog/langgraph-redis-checkpoint-010/) — HIGH confidence (official Redis blog)
- [LangGraph v1 migration guide](https://docs.langchain.com/oss/javascript/migrate/langgraph-v1) — HIGH confidence (official migration docs; JS-focused but reflects Python changes)
- [Multi-Agent AI Testing Guide 2025 (Zyrix)](https://zyrix.ai/blogs/multi-agent-ai-testing-guide-2025/) — LOW confidence (single source, no cross-verification)
- [9 Strategies to Ensure Stability in Dynamic Multi-Agent Systems (Galileo)](https://galileo.ai/blog/stability-strategies-dynamic-multi-agents) — MEDIUM confidence (observability vendor, but content is patterns-focused)
- [Cost Guardrails for Agent Fleets (Medium)](https://medium.com/@Micheal-Lanham/cost-guardrails-for-agent-fleets-how-to-prevent-your-ai-agents-from-burning-through-your-budget-ea68722af3fe) — LOW confidence (single practitioner blog)
- [FastAPI LangGraph agent production template (GitHub)](https://github.com/wassim249/fastapi-langgraph-agent-production-ready-template) — MEDIUM confidence (community reference implementation)
- [Streaming AI Agent with FastAPI & LangGraph (DEV Community)](https://dev.to/kasi_viswanath/streaming-ai-agent-with-fastapi-langgraph-2025-26-guide-1nkn) — LOW confidence (community post, recent)
- [Guardrails and Best Practices for Agentic Orchestration (Camunda)](https://camunda.com/blog/2026/01/guardrails-and-best-practices-for-agentic-orchestration/) — MEDIUM confidence (enterprise vendor, 2026 publish date)
