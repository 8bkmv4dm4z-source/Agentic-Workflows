# Codebase Concerns

**Analysis Date:** 2026-03-12

## Tech Debt

**Anthropic Provider Missing — Graph Wiring Exists Without Provider Class:**
- Issue: `orchestrator.py` and `planner_node.py` detect `P1_PROVIDER=anthropic` and wire a LangGraph `ToolNode` path, but `provider.py`'s `build_provider()` raises `ValueError` if `P1_PROVIDER=anthropic` is set — no `AnthropicChatProvider` class exists.
- Files: `src/agentic_workflows/orchestration/langgraph/provider.py:703-736`, `src/agentic_workflows/orchestration/langgraph/orchestrator.py:357-392`
- Impact: Setting `P1_PROVIDER=anthropic` crashes at provider build, making the entire ToolNode/ReAct path dead code for the documented Anthropic use case.
- Fix approach: Implement `AnthropicChatProvider(ChatProvider)` using `langchain-anthropic` or `anthropic` SDK and register it in `build_provider()`.

**`mission_type` Hardcoded to `"multi_step"` in Routing Signals:**
- Issue: `planner_node.py:256` hardcodes `"mission_type": "multi_step"` in every call to `route_by_signals()`, bypassing the `ModelRouter`'s signal-based logic for simple vs. complex tasks. The `fast` provider is never selected by this path.
- Files: `src/agentic_workflows/orchestration/langgraph/planner_node.py:254-260`, `src/agentic_workflows/orchestration/langgraph/model_router.py:90`
- Impact: Cost savings from fast/strong routing are never realised during planning; all calls go to the strong provider.
- Fix approach: Read actual `mission_type` from `state["structured_plan"]["intent_classification"]` or pass `"unknown"` and rely on other signal thresholds.

**Legacy P0 Core Module Dead Code:**
- Issue: `src/agentic_workflows/core/` (orchestrator.py, main.py, llm_provider.py, agent_state.py) is explicitly omitted from coverage in `pyproject.toml` with comment "Legacy P0 baseline — superseded by LangGraph orchestrator", but the code still ships. `core/main.py` is only referenced from within core itself.
- Files: `src/agentic_workflows/core/orchestrator.py`, `src/agentic_workflows/core/main.py`, `src/agentic_workflows/core/llm_provider.py`
- Impact: Dead code adds maintenance surface; `core/llm_provider.py` duplicates URL resolution logic from `orchestration/langgraph/provider.py`.
- Fix approach: Delete `core/orchestrator.py`, `core/main.py`, `core/llm_provider.py`; keep `core/agent_state.py` only if still imported by tests (it is: `tests/unit/test_agent_state.py`).

**`graph.py` Is Now a Pure Re-Export Shim with an `if False:` Anchor:**
- Issue: `graph.py:30-31` contains `if False: ContextManager(large_result_threshold=3000)` as an "AST anchor" so that tests scanning this file's text still find the instantiation. This is a fragile documentation-by-dead-code pattern.
- Files: `src/agentic_workflows/orchestration/langgraph/graph.py:27-31`
- Impact: If tests are refactored to not scan AST, this dead code becomes confusing. Searching for `ContextManager(large_result_threshold=3000)` returns a misleading result.
- Fix approach: Update test grep patterns to point to `orchestrator.py` where the actual instantiation lives; remove the `if False:` block.

**Token Budget Estimation Uses Character-Count ÷ 4 Approximation:**
- Issue: Token usage is estimated as `len(text) // 4` (`planner_node.py:281,364-365`). This is inaccurate for non-ASCII content (e.g. Chinese, Japanese) and structured JSON outputs where the ratio differs significantly.
- Files: `src/agentic_workflows/orchestration/langgraph/planner_node.py:281,364-369`
- Impact: Token budget depletion (`planner_timeout_mode`) may trigger too early or too late, causing either wasted LLM calls or premature shutdown of multi-mission runs.
- Fix approach: Use `tiktoken` or provider-reported token counts (OpenAI responses include `usage`) for accurate tracking.

**`route_by_intent()` Deprecated Shim Still Present:**
- Issue: `model_router.py:104-129` marks `route_by_intent()` as deprecated with a `DeprecationWarning` and a comment "until all callers migrate (Plan 03)". No callers appear to use it in production code.
- Files: `src/agentic_workflows/orchestration/langgraph/model_router.py:104-129`
- Impact: Low — but emits runtime warnings if accidentally called. Signals incomplete migration.
- Fix approach: Grep for callers; if none remain, remove the method.

**`run.py` and `user_run.py` Excluded from Coverage:**
- Issue: Both `src/agentic_workflows/orchestration/langgraph/run.py` (1112 lines) and `src/agentic_workflows/orchestration/langgraph/user_run.py` (377 lines) are coverage-excluded as "interactive CLI scripts". They contain substantial orchestration logic (orchestrator construction, provider wiring, dual-logging setup).
- Files: `pyproject.toml:70-78`, `src/agentic_workflows/orchestration/langgraph/run.py`, `src/agentic_workflows/orchestration/langgraph/user_run.py`
- Impact: Regressions in `_build_orchestrator()`, provider fallback logic, or Postgres wiring go undetected.
- Fix approach: Extract orchestrator-construction logic into a testable factory function; keep only the `if __name__ == "__main__":` block excluded from coverage.

---

## Known Bugs

**Recursion Limit Multiplier Inconsistency Between CLAUDE.md and Code:**
- Symptoms: `CLAUDE.md` states "Recursion limit = max_steps × 3" but both `orchestrator.py:503` and `api/routes/run.py:98` use `max_steps * 9`.
- Files: `src/agentic_workflows/orchestration/langgraph/orchestrator.py:503`, `src/agentic_workflows/api/routes/run.py:98`
- Trigger: Documentation is stale relative to code. Actual limit is 9×, not 3×.
- Workaround: Accept 9× as correct (prevents LangGraph's internal recursion guard from firing before `max_steps` check fires); update CLAUDE.md.

---

## Security Considerations

**SSRF Protection Incomplete — IPv6 and DNS Rebinding Not Covered:**
- Risk: `http_request.py` blocks private IPv4 ranges via `_PRIVATE_PREFIXES` tuple and `socket.gethostbyname()` resolution, but does not block IPv6 loopback (`::1`), IPv6 private ranges (`fc00::/7`, `fe80::/10`), or IPv4-mapped IPv6 addresses (`::ffff:127.0.0.1`). DNS rebinding attacks (resolve to public IP at check time, then rebind to private) are also not mitigated.
- Files: `src/agentic_workflows/tools/http_request.py:12-17`, `src/agentic_workflows/tools/http_request.py:49-56`, `src/agentic_workflows/tools/http_request.py:103-104`
- Current mitigation: IPv4 private ranges blocked; domain allowlist via `P1_HTTP_ALLOWED_DOMAINS` (off by default).
- Recommendations: Use `ipaddress.ip_address(ip).is_private` (Python stdlib, covers IPv6) instead of startswith prefix matching; resolve all returned addresses (A + AAAA) and reject if any is private.

**All Security Guardrails Are Off by Default:**
- Risk: `validate_path_within_sandbox()`, `check_bash_command()`, `check_http_domain()`, and `check_content_size()` all return `None` (allow) when their respective env vars (`P1_TOOL_SANDBOX_ROOT`, `P1_BASH_DENIED_PATTERNS`, `P1_HTTP_ALLOWED_DOMAINS`, `P1_WRITE_FILE_MAX_BYTES`) are unset. A deployment that omits these vars has no filesystem, bash, or HTTP guardrails.
- Files: `src/agentic_workflows/tools/_security.py:59-83`, `src/agentic_workflows/tools/_security.py:90-120`, `src/agentic_workflows/tools/_security.py:127-146`
- Current mitigation: Comment in `_security.py` notes guardrails are "env-var gated and off by default".
- Recommendations: Document required production env vars in `.env.example` with recommended values; consider safe defaults (e.g. `P1_TOOL_SANDBOX_ROOT` defaulting to `AGENT_WORKDIR` when set).

**API Key Middleware Passes All Requests When `API_KEY` Env Var Unset:**
- Risk: `APIKeyMiddleware` has an explicit dev passthrough: if `API_KEY` is not set, every request is allowed through. There is no warning or log message emitted at startup when auth is disabled.
- Files: `src/agentic_workflows/api/middleware/api_key.py:22-27`
- Current mitigation: None at the framework level — operator must remember to set `API_KEY`.
- Recommendations: Emit a `WARNING` log at startup when `API_KEY` is absent. Consider a `P1_AUTH_DISABLED=true` explicit opt-in rather than implicit passthrough.

**CORS Defaults to Localhost-Only (Correct) But `allow_credentials=True`:**
- Risk: `app.py:182` sets `allow_credentials=True` alongside wildcard methods/headers. If `CORS_ORIGINS` is misconfigured to `["*"]`, credentials (cookies, auth headers) would be sent cross-origin to any domain.
- Files: `src/agentic_workflows/api/app.py:179-185`
- Current mitigation: Default origins are `localhost:3000` and `localhost:8080`. The `["*"]` wildcard is not the default.
- Recommendations: Add startup validation to reject `allow_origins=["*"]` when `allow_credentials=True` is also set.

---

## Performance Bottlenecks

**Synchronous LLM Calls Block the FastAPI Event Loop:**
- Problem: `api/routes/run.py:78` wraps `orchestrator.run()` in `anyio.to_thread.run_sync()`, but `orchestrator.run()` itself blocks inside `_generate_with_hard_timeout()` using `threading.Thread` + `queue.Queue.get(timeout=...)`. This is a synchronous blocking pattern inside an async executor thread.
- Files: `src/agentic_workflows/orchestration/langgraph/planner_helpers.py:637-656`, `src/agentic_workflows/api/routes/run.py:155-170`
- Cause: LangGraph's `invoke()` and provider SDKs (openai, groq) have no native async interface in the current integration.
- Improvement path: Use `AsyncOpenAI`/`AsyncGroq` clients and LangGraph's `ainvoke()` to eliminate thread-based blocking for these providers.

**`state["messages"]` Grows Unbounded Relative to Run Duration:**
- Problem: Every planner step appends at least one message to `state["messages"]` (tool results, progress hints, context injections). The `ContextManager.compact()` sliding window only trims the list to `sliding_window_cap=20` entries, but tool results are appended as full-content messages before they are truncated. Long runs with many tool calls and large results can produce very large message lists before compaction fires.
- Files: `src/agentic_workflows/orchestration/langgraph/executor_node.py:283,359,393,412,464`, `src/agentic_workflows/orchestration/langgraph/context_manager.py:716-730`
- Cause: Compaction only triggers when `len(messages) > sliding_window_cap`; large individual messages can still fill context windows.
- Improvement path: Truncate individual tool-result messages at the append site (currently done in `executor_node.py:726` for one path, but not all append sites).

**`_cascade_cache` / `_embed_cache` Eviction Is O(n) FIFO:**
- Problem: `context_manager.py:44` sets `_CACHE_MAX_SIZE=200`. When the limit is reached, the oldest half is evicted. Iterating over a dict to remove the first `n//2` entries is O(n) and blocks the ContextManager on each eviction event.
- Files: `src/agentic_workflows/orchestration/langgraph/context_manager.py:43-44`
- Cause: Standard dict iteration for eviction; acceptable at 200 entries but not at larger scales.
- Improvement path: Use `collections.OrderedDict` or `functools.lru_cache`; eviction is then O(1).

---

## Fragile Areas

**`_dedup_then_tool_node()` Anthropic Path Deduplication Is Stateless Across Reconnects:**
- Files: `src/agentic_workflows/orchestration/langgraph/executor_node.py:81-114`
- Why fragile: The wrapper checks `state.get("seen_tool_signatures", set())` for duplicates before calling `ToolNode`. If a client reconnects to a stream and the run is resumed, `seen_tool_signatures` must be re-hydrated from the checkpoint; if it is not, previously-executed tools can replay.
- Safe modification: Always ensure `seen_tool_signatures` is checkpointed and reloaded before invoking the dedup wrapper.
- Test coverage: No test for the reconnect-then-dedup scenario.

**`graph.py` Re-Export Shim Couples Test Patching to Module Paths:**
- Files: `src/agentic_workflows/orchestration/langgraph/graph.py:18-52`
- Why fragile: Tests that `patch("agentic_workflows.orchestration.langgraph.graph.build_provider")` depend on `graph.py` re-exporting the name. If `graph.py` is removed (the logical next refactor step), all such patches silently become no-ops unless tests update their patch targets.
- Safe modification: Run `grep -r "graph.build_provider\|graph.ContextManager"` across tests before removing any re-export; update patch targets to `orchestrator.py` or `provider.py` directly.
- Test coverage: Re-export shim is not itself tested.

**Bare `except Exception: pass` Swallows Provider Failures Silently:**
- Files: `src/agentic_workflows/orchestration/langgraph/provider.py:358,401,486,682,699`, `src/agentic_workflows/orchestration/langgraph/planner_node.py:45,228,497,622`
- Why fragile: 37 total `except Exception` clauses in source; several (marked `# noqa: BLE001`) swallow errors completely with a bare `pass`, making provider fallback failures invisible without debug logging enabled.
- Safe modification: Replace `pass` with at minimum `_LOG.debug("silent fallback: %s", exc)` so failures surface during development.
- Test coverage: Silent failure branches are untested by design in most cases.

**`SQLiteCheckpointStore` Uses a Single Shared `sqlite3.Connection`:**
- Files: `src/agentic_workflows/orchestration/langgraph/checkpoint_store.py:51,96`
- Why fragile: One `threading.Lock()` guards a single connection object. If multiple threads call `save()` and `load()` concurrently (e.g. SSE streaming + background audit), the lock contention serialises all I/O. SQLite's `check_same_thread=False` mode is required but not confirmed to be set.
- Safe modification: Use `sqlite3.connect(..., check_same_thread=False)` explicitly and consider connection-per-thread for high-concurrency FastAPI deployments.
- Test coverage: Concurrency is not tested.

---

## Scaling Limits

**SQLite Default for Checkpoint and Memo Stores:**
- Current capacity: In-process SQLite file; adequate for single-process dev use.
- Limit: Write-heavy concurrent SSE runs will contend on the single lock and hit SQLite's WAL-mode limits (~100 concurrent writers).
- Scaling path: Set `DATABASE_URL` to switch to `PostgresCheckpointStore` / `PostgresMemoStore`; already implemented in `app.py:84-85`.

**`active_streams` Dict Has No Bounded Size or TTL:**
- Current capacity: Unbounded in-memory dict in `app.state`.
- Limit: If clients start runs and disconnect without consuming the full SSE stream, `receive_stream` objects accumulate in memory until the process restarts.
- Scaling path: Add TTL eviction (e.g., pop streams older than `_SSE_MAX_DEFAULT=300s`) in the producer's `finally` block or a periodic cleanup task. Files: `src/agentic_workflows/api/routes/run.py:175`.

---

## Dependencies at Risk

**`fastembed` Optional Import with Silent Fallback:**
- Risk: `context/embedding_provider.py:80` uses `from fastembed import TextEmbedding  # type: ignore[import]` inside a try block. If `fastembed` is not installed, the embedding provider silently degrades. Downstream `query_context` tool and cascade queries silently become no-ops.
- Impact: Phase 7.3+ semantic context features become inactive with no error surfaced to the user.
- Migration plan: Add a startup warning when `DATABASE_URL` is set but `fastembed` import fails; document `fastembed` as a required extra for the `[postgres]` feature set.

---

## Test Coverage Gaps

**`run.py` and `user_run.py` (1500 lines combined) Are Coverage-Excluded:**
- What's not tested: `_build_orchestrator()`, Postgres pool setup, provider fallback chain, dual-logging setup, `P1_APPEND_LASTRUN` flag, reviewer mode selection.
- Files: `src/agentic_workflows/orchestration/langgraph/run.py`, `src/agentic_workflows/orchestration/langgraph/user_run.py`
- Risk: Provider wiring regressions (wrong model selected, env vars ignored) are invisible.
- Priority: High

**Anthropic ToolNode Path Has No Integration Test:**
- What's not tested: The `P1_PROVIDER=anthropic` code path in `orchestrator.py:357-392` and `executor_node.py:81-114` has no test that exercises the `use_tool_node=True` branch.
- Files: `src/agentic_workflows/orchestration/langgraph/orchestrator.py:357-405`, `src/agentic_workflows/orchestration/langgraph/executor_node.py:81-114`
- Risk: Any change to the ToolNode wiring is completely invisible to CI.
- Priority: High (once Anthropic provider class is implemented)

**Security Guardrail Edge Cases Not Covered:**
- What's not tested: IPv6 SSRF bypass in `http_request.py`; `P1_TOOL_SANDBOX_ROOT` path-traversal with symlinks; `check_bash_command` allowlist interaction with denied patterns.
- Files: `src/agentic_workflows/tools/http_request.py`, `src/agentic_workflows/tools/_security.py`
- Risk: Security regressions go unnoticed; a subtle change to `_is_private()` could open SSRF.
- Priority: High

**`context_manager.py` Compaction Under Concurrent Append Not Tested:**
- What's not tested: Behaviour when `compact()` is called concurrently with `append()` from the executor node thread.
- Files: `src/agentic_workflows/orchestration/langgraph/context_manager.py:716-730`
- Risk: Race condition between compaction and message append could drop context silently.
- Priority: Medium

---

*Concerns audit: 2026-03-12*
