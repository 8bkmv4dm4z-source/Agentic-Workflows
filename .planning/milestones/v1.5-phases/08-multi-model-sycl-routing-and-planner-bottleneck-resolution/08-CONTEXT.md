# Phase 8: Multi-Model SYCL Routing and Planner Bottleneck Resolution - Context

**Gathered:** 2026-03-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Two objectives:
1. Wire two separate llama-server processes (different ports) for planner and executor roles via `LlamaCppChatProvider`; decompose graph.py monolith into sub-modules ≤600 lines each.
2. Fix planner context overflow: when a mission produces large tool output, intercept in `ContextManager` before planner injection, store in a new `ToolResultCache` Postgres table, and replace with a compact summary pointer.

What this phase does NOT include:
- LangGraph Send() parallel execution
- New specialist subgraph capabilities
- LLM-generated summarization (deterministic extraction only)

</domain>

<decisions>
## Implementation Decisions

### graph.py Decomposition
- **Strategy: by graph node/role** — each major LangGraph node becomes its own file (e.g., `planner_node.py`, `executor_node.py`, `policy_node.py`, `finalize_node.py`). Thin wiring assembles them.
- **Helpers co-located with their node** — `_build_planner_context()` lives in `planner_node.py`, `_route_specialist_hint()` in `executor_node.py`, etc. Each file is self-contained.
- **`LangGraphOrchestrator` moves to `orchestrator.py`** — becomes the thin spine that imports all node files and assembles the StateGraph. `graph.py` becomes a re-export shim for backward compat.
- **`graph.py` kept as re-export shim** — `from .orchestrator import LangGraphOrchestrator` etc. All 657 tests pass unchanged with no import churn.
- No single file >600 lines after decomposition.

### SYCL Server Configuration
- **Two env vars:** `LLAMA_CPP_PLANNER_PORT` and `LLAMA_CPP_EXECUTOR_PORT`. If only one is set (or neither), both roles use the same server (current behavior preserved).
- Consistent with Phase 7.8's `LLAMA_CPP_STRONG_ALIAS` / `LLAMA_CPP_FAST_ALIAS` pattern.
- **`with_port(port: int) -> LlamaCppChatProvider` factory method** — returns a new instance pointing to the overridden base URL port. Symmetrical with existing `with_alias()`. No new subclass.
- **Startup behavior: warn + single-server fallback** — if a configured server is unreachable at startup, log a warning and fall back to routing both roles through the available server. System runs, role separation is best-effort. Hard fail only if NO server is reachable.

### Result Summarization Storage
- **New `ToolResultCache` Postgres table** (migration 005) — dedicated table, not MissionContextStore or ArtifactStore. Separate concern, separate table, independent evolution path.
- **Cache key: `tool_name` + `SHA-256(serialized args)`** — exact deduplication. Consistent with Phase 7.3's `goal_hash` pattern.
- **TTL + lazy eviction** — each row has `expires_at` (configurable, default 7 days via env var). On cache lookup: if expired → treat as miss, delete inline. No background worker. Prevents DB bloat for long-running API/user_run deployments.

### Truncation Injection Shape
- **Format:** `[Result truncated — {N} chars stored] Tool: {tool_name} | Key: {hash[:8]} | Summary: {first 200 chars}...`
- Uses `[Orchestrator]` prefix convention (Phase 7.1 / Phase 5 pattern). Human-readable summary + retrieval pointer.
- **Threshold:** `LARGE_RESULT_THRESHOLD` env var, default `2000` chars. Results exceeding this are cached and replaced with the compact injection.
- **Location: `ContextManager.build_planner_context_injection()`** — truncation happens before planner injection, not at tool execution time. `tool_history` retains the full result (for audit/retrieval); only the planner message sees the compact form. No graph.py changes required for this path.

### Claude's Discretion
- Exact node file naming (e.g., `planner_node.py` vs `nodes/planner.py`)
- Whether `finalize_node.py` and `policy_node.py` warrant separate files or share a `lifecycle_nodes.py`
- Internal `with_port()` client re-init strategy (new httpx client vs shared base + override)
- `ToolResultCache` migration SQL and exact column layout
- TTL default value (7 days recommended, configurable)

</decisions>

<specifics>
## Specific Ideas

- Re-export shim pattern keeps all 657 tests green with zero import churn — critical for safe refactor
- `with_port()` is symmetric with `with_alias()` from Phase 7.8 — two factory methods, composable: `provider.with_alias("planner").with_port(8081)`
- Startup warn-and-fallback mirrors how `fallback_provider=None` (Phase 7.8) degrades gracefully
- TTL lazy eviction on read is "free" — no background process, no scheduler, works identically in all deployment contexts (run.py, user_run.py, FastAPI)
- ContextManager intercept point is cleanest: `tool_history` stays intact (full result always available for audit), only planner injection is compacted

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `LlamaCppChatProvider` in `provider.py`: has `_detect_llama_cpp_model()`, `with_alias()` factory — `with_port()` follows same pattern
- `ContextManager.build_planner_context_injection()` in `context_manager.py`: existing injection entry point; truncation logic slots in here
- Phase 7.3 `goal_hash` SHA-256 pattern in `mission_context_store.py` — reuse for `tool_name + args` hashing
- Phase 07.5 `ArtifactStore` pattern: optional constructor param `| None` with backward-compat default — follow same pattern for `ToolResultCache`
- `db/migrations/` directory: 004 migrations exist; new migration 005 follows existing SQL file convention

### Established Patterns
- `build_provider()` + optional param + `| None` default (fallback_provider, mission_context_store, etc.) — all new optional components follow this
- `[Orchestrator]` prefix + `role="user"` message injection (Phase 5/7.1 convention)
- `LARGE_RESULT_THRESHOLD` threshold already exists in ContextManager (1500 default) — new env var at 2000 is a parallel but distinct knob
- `ensure_state_defaults()` for new RunState fields via `.setdefault()`
- `structural_health` counters: `tool_result_cache_hits: int` and `tool_result_truncations: int` should be added (Phase 7.8 pattern)

### Integration Points
- `orchestrator.py` (new): reads `LLAMA_CPP_PLANNER_PORT` / `LLAMA_CPP_EXECUTOR_PORT`, calls `with_port()` to build role-specific providers
- `context_manager.py build_planner_context_injection()`: checks result size against threshold, calls `ToolResultCache.store()` on overflow, replaces with compact injection
- `state_schema.py`: new `structural_health` keys for cache hits/truncations in `new_run_state()` and `ensure_state_defaults()`
- `db/migrations/005_tool_result_cache.sql`: new table `tool_result_cache` with `tool_name`, `args_hash`, `full_result`, `summary`, `result_len`, `expires_at`, `created_at`
- `run.py` + `user_run.py`: instantiate `ToolResultCache(pool=pg_pool)` when `DATABASE_URL` set; display truncation count in audit panel

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 08-multi-model-sycl-routing-and-planner-bottleneck-resolution*
*Context gathered: 2026-03-11*
