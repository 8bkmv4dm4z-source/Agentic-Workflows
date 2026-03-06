# Domain Pitfalls

**Domain:** Multi-agent LangGraph orchestration — single-agent to multi-agent transition, prototype to production
**Researched:** 2026-03-02
**Overall Confidence:** HIGH (all major claims verified against official LangGraph docs, GitHub issues, and recent community reports)

---

## Critical Pitfalls

Mistakes that cause rewrites, lost state, or production outages.

---

### Pitfall 1: Subgraph State Bleeding — Missing Key Isolation Between Parent and Subgraph

**What goes wrong:** When a parent graph and subgraph share state keys (e.g., both have `messages`, `tool_history`, or `active_specialist`), LangGraph merges updates from the subgraph back into the parent's matching keys. The subgraph's internal conversation history floods the parent graph's `messages` list. Specialist agents see each other's tool history. Reducer functions on `tool_history` (currently a plain list) cause last-write-wins semantics, silently dropping parallel specialist outputs.

**Why it happens:** This project's `RunState` uses a flat TypedDict with no `Annotated` reducers on mutable list fields. When specialist subgraphs are added with the same state schema (the "shared state" pattern), every key they touch merges into parent state by default overwrite, not append.

**Consequences:** Mission reports from one specialist silently overwrite another's. `tool_history` shows only the last specialist's calls. The existing MissionAuditor's `_map_tool_history_to_missions()` cursor logic breaks because call order is no longer monotonically sequential across missions. The 208 existing tests pass but the auditor reports false "chain_integrity" failures on real multi-agent runs.

**Prevention:**
- Use isolated state pattern for specialist subgraphs: each specialist gets its own TypedDict with private fields; invoke the subgraph inside a regular node function and manually extract only the outputs you need back into `RunState`.
- If shared state is required, annotate every list field that parallel agents write: `tool_history: Annotated[list[ToolRecord], operator.add]` and `mission_reports: Annotated[list[MissionReport], operator.add]`.
- Design specialist subgraphs to return a narrow output TypedDict (`HandoffResult`) rather than the full `RunState` — this is already sketched in `handoff.py` and should be enforced at subgraph boundary.

**Detection (warning signs):**
- Auditor reports `chain_integrity` failures on runs where tool calls look correct in logs
- `len(state["tool_history"])` after a multi-agent run is smaller than expected
- `mission_reports` list has fewer entries than missions submitted
- `active_specialist` field contains the wrong specialist name after handoff returns

**Phase:** Phase 3 (Multi-agent subgraph delegation)

---

### Pitfall 2: Plain List Fields Without Reducers Break Parallel Mission Execution

**What goes wrong:** LangGraph's default state merge behavior for TypedDict fields is last-write-wins overwrite. `RunState` currently stores `tool_history`, `mission_reports`, `memo_events`, `pending_action_queue`, and `seen_tool_signatures` as plain `list` fields with no reducer annotation. When two parallel mission branches (using `Send`) both return state updates, the second branch's list overwrites the first's entirely — tool records from Mission 1 vanish.

**Why it happens:** The `Send` API in LangGraph requires reducer functions on any state key that multiple branches write concurrently. Without `Annotated[list, operator.add]` (or a custom merge reducer), the framework performs last-write-wins on list fields. The current single-agent sequential execution hides this bug because only one branch executes at a time.

**Consequences:** Dropped mission results. The `seen_tool_signatures` deduplication set loses entries from earlier branches, allowing duplicate tool calls. The MemoizationPolicy's tracking in `policy_flags` (also a plain dict) gets overwritten. Checkpoint replay produces incorrect state.

**Prevention:**
- Before implementing `Send`-based parallel missions, annotate all list and dict fields in `RunState` that parallel branches update:
  ```python
  from typing import Annotated
  import operator
  tool_history: Annotated[list[ToolRecord], operator.add]
  mission_reports: Annotated[list[MissionReport], operator.add]
  memo_events: Annotated[list[MemoEvent], operator.add]
  ```
- For dict fields like `retry_counts` and `tool_call_counts`, write a custom merge reducer that sums values rather than overwrites.
- For `seen_tool_signatures`, convert to a set-union reducer or deduplicate post-merge.
- Add an integration test that runs two `Send` branches and asserts both branches' tool records appear in the merged state.

**Detection (warning signs):**
- Any `Send`-based test where the total `len(state["tool_history"])` equals only one branch's call count, not the sum
- Duplicate tool call alerts that disappear under parallel execution
- `audit_report["failed"]` increases only when running parallel missions

**Phase:** Phase 3 (Parallel mission execution with `Send`)

---

### Pitfall 3: LangGraph Version Upgrade Introduces Silent Behavioral Changes in ToolNode Error Handling

**What goes wrong:** The project is pinned at `langgraph>=0.2.67,<1.0`. Removing this pin to enable `ToolNode`, `tools_condition`, and `langchain-anthropic` is necessary for Phase 2, but the upgrade path has at least two confirmed behavioral landmines: (1) `langgraph-prebuilt==1.0.2` changed `ToolNode.afunc` signature, breaking subclasses; (2) `langgraph-prebuilt>=1.0.1` disabled tool error handling by default — previously errors were caught and returned as tool messages, now they propagate and crash the graph unless `handle_tool_errors=True` is set explicitly.

**Why it happens:** The LangChain team declared "no breaking changes" for the 1.0 release but introduced behavioral defaults changes in subsequent patch versions. The gap between 0.2 and 1.0 also includes removal of some prebuilt components and renaming of imports (e.g., `create_react_agent` is deprecated in favor of `langchain.agents.create_agent`).

**Consequences:** Tool execution errors that were silently recovered in 0.2 now crash the entire graph run in 1.0 without explicit `handle_tool_errors=True`. Any test that relied on error recovery behavior passes locally on the old pin but fails on upgraded versions. The existing custom `_route_to_specialist()` in `graph.py` uses manual tool dispatch, not `ToolNode`, so the upgrade primarily affects Phase 2's new `ToolNode` adoption.

**Prevention:**
- Pin exact langgraph versions during the upgrade sprint: `langgraph==1.0.6, langgraph-prebuilt==1.0.1` (known stable combination) before moving to latest.
- Explicitly set `handle_tool_errors=True` on every `ToolNode` instance.
- Add a test that deliberately triggers a tool error and asserts it is handled (returned as error message) not raised.
- Upgrade langgraph and langgraph-prebuilt in the same commit with a locked `requirements-dev.txt` so the CI environment matches development.
- Do not rely on `from langgraph.prebuilt import create_react_agent` — use `from langchain.agents import create_agent` instead.

**Detection (warning signs):**
- Test failures referencing `afunc` signature after upgrading `langgraph-prebuilt`
- Graphs that passed error injection tests on 0.2 crash without warning on 1.0
- Import errors from `langgraph.prebuilt` for symbols that moved

**Phase:** Phase 2 (LangGraph upgrade and ToolNode migration) — must be fully resolved before Phase 3

---

### Pitfall 4: Subgraph Checkpoints Not Persisted Unless Explicitly Propagated

**What goes wrong:** When specialist subgraphs are added and compiled independently, their state is not saved to the SQLite checkpoint store unless the parent graph passes the checkpointer down correctly. The known pattern is: compile the parent graph with a checkpointer; LangGraph automatically propagates it to child subgraphs. Compiling subgraphs with their own separate `checkpointer` argument causes namespace conflicts and the child state is saved under a different thread_id, invisible to the parent's checkpoint stream.

**Why it happens:** Early LangGraph subgraph docs showed compiling subgraphs with `checkpointer=True` independently. This was changed in v0.2.64 to the propagation model. Projects that follow older tutorials or the pre-fix pattern silently lose subgraph state on replay.

**Consequences:** On interrupt/resume (human-in-the-loop), specialist subgraph state is lost — the subgraph replays from scratch on resume. Post-run audits that traverse checkpoint history see only parent-level checkpoints, not specialist-level tool calls. The `run_audit.py` cross-run audit summary will be incomplete.

**Prevention:**
- Compile specialist subgraphs with no checkpointer argument; let the parent graph propagate its checkpointer: `subgraph.compile()` (not `subgraph.compile(checkpointer=parent_checkpointer)`).
- Add an integration test that invokes a run with a subgraph, reads back checkpoints, and asserts subgraph state appears in the checkpoint history.
- The existing `SQLiteCheckpointStore` in `checkpoint_store.py` should be extended to verify subgraph namespace entries after a multi-agent run.

**Detection (warning signs):**
- Replaying a run from checkpoint produces different tool call sequences than the original
- `checkpoint_store.load()` returns fewer entries than expected for multi-agent runs
- `run_audit.py` shows empty tool histories for specialist-executed missions

**Phase:** Phase 3 (Subgraph delegation)

---

### Pitfall 5: SQLite Checkpoint Store Is Unsafe for Concurrent Production Requests

**What goes wrong:** The current `SQLiteCheckpointStore` works correctly for single-threaded sequential runs. Under concurrent HTTP requests (Phase 4's FastAPI layer), SQLite's write locking will cause `database is locked` errors when two simultaneous requests both try to write checkpoints. This is a known SQLite limitation, not a LangGraph bug. Additionally, CVE-2025-67644 documents an SQL injection vulnerability in `langgraph-checkpoint-sqlite<=3.0.0` via metadata filter keys.

**Why it happens:** SQLite serializes all writes through a single file lock. FastAPI with async handlers and multiple uvicorn workers will exhaust the lock timeout within seconds of load. The custom `SQLiteCheckpointStore` in this project also does not use the official `langgraph-checkpoint-sqlite` package, so it won't benefit from upstream security patches automatically.

**Consequences:** Under load testing (Phase 4), simultaneous mission submissions will produce intermittent `OperationalError: database is locked`. State is not corrupted (SQLite is ACID), but requests time out. At production scale, this blocks all concurrent agent work.

**Prevention:**
- For Phase 4 production, replace the custom SQLite checkpoint store with a Postgres-backed store (`langgraph-checkpoint-postgres`) — this is the LangGraph team's explicit recommendation for production.
- For development and single-user stress testing, keep SQLite but set `PRAGMA journal_mode=WAL;` to allow concurrent reads with serialized writes.
- Do not share a single `SQLiteCheckpointStore` instance across FastAPI request handlers — use per-request or per-thread connections.
- Upgrade `langgraph-checkpoint-sqlite` to >=3.0.1 if you adopt the official package (patches CVE-2025-67644).

**Detection (warning signs):**
- `OperationalError: database is locked` in logs under any concurrent load
- Load test with 2 simultaneous requests fails but serial requests pass
- Checkpoint entries missing for some runs when concurrency > 1

**Phase:** Phase 4 (Production infrastructure)

---

## Moderate Pitfalls

Mistakes that cause debugging time loss, degraded output quality, or test fragility.

---

### Pitfall 6: Observability Decorator Applied at Wrong Granularity — Traces Are Too Coarse or Missing Context

**What goes wrong:** The `@observe` decorator exists in `observability.py` and is already applied to `provider.generate.*` methods. However, it is not yet applied to the graph's node functions (`_plan_next_action`, `_route_to_specialist`, `_finalize`). Without node-level tracing, Langfuse shows one span per provider call but cannot attribute which graph node triggered which LLM call, what state entered the node, or which mission the call served.

**Why it happens:** The `@observe` decorator is a no-op when Langfuse is unconfigured, making it easy to defer wiring. But the deferral means that when Langfuse is finally configured in production, traces arrive with no node-level context — the root span contains all provider calls flat, with no hierarchy.

**Consequences:** Debugging a failed multi-agent run requires cross-referencing raw logs with Langfuse traces manually. The `run_id` and `mission_id` that exist in `RunState` are not propagated to trace metadata. Langfuse shows provider latency but not which missions were slow.

**Prevention:**
- Apply `@observe(name="node.plan")`, `@observe(name="node.execute")`, etc. to each graph node method.
- Pass `run_id` and `mission_id` as custom Langfuse attributes inside each node's `@observe` wrapper using `langfuse_context.update_current_trace(metadata={"run_id": ...})`.
- In Phase 4, add a test fixture that configures a test Langfuse client and asserts that a completed run produces a trace with the expected span hierarchy (plan → execute → policy → finalize).
- Ensure `flush()` is called at the end of every FastAPI request handler — otherwise buffered events are lost on worker shutdown.

**Detection (warning signs):**
- Langfuse dashboard shows flat list of `provider.generate` spans with no parent node spans
- `run_id` field is absent from Langfuse trace metadata
- Long-running runs show no in-progress spans — all spans appear only after run completion (buffering without flush)

**Phase:** Phase 1 open item (observe wiring); Phase 4 (full trace hierarchy)

---

### Pitfall 7: Message History Grows Unbounded — Context Window Overflow in Long Multi-Agent Runs

**What goes wrong:** `RunState.messages` accumulates every `AgentMessage` (system, user, assistant, tool) for the entire run. In a multi-mission run with 5 missions and 10 tool calls each, the message list grows to 60+ messages before the final mission's planning call. Each planning call sends the full history to the provider. Long histories cause: (a) context window overflow for smaller models (Groq llama-3.1-8b: 8192 tokens); (b) "lost in the middle" degradation where the model ignores early mission context; (c) token cost that scales quadratically with steps.

**Why it happens:** The current `new_run_state` initializes `messages` as a plain list and every plan/response pair is appended. No summarization or trimming is applied. The CLAUDE.md guidance mentions a 50-message compaction threshold but it is not yet implemented.

**Consequences:** Runs with many missions and long tool outputs will hit provider token limits or produce degraded plans. The planner starts hallucinating tool names or ignoring mission-specific context because the relevant instruction is "lost" in the middle of a 4000-token history.

**Prevention:**
- Implement a message compaction strategy before Phase 3 adds specialist delegation (which multiplies message volume): when `len(messages) > 40`, summarize the middle section using a fast provider call (or rule-based extraction), replace summarized messages with a single `{"role": "system", "content": "Summary: ..."}` message.
- Store specialist agent messages in the subgraph's private state, not in the parent `RunState.messages`. Only the handoff task and result need to enter parent state.
- Add a test that simulates a 50-message run and asserts the provider is called with fewer than 30 messages (after compaction).

**Detection (warning signs):**
- Provider calls show token counts approaching model limits in logs
- Planner begins calling wrong tools or ignoring mission text in later missions
- `ProviderTimeoutError` frequency increases as runs get longer (timeouts correlate with large payloads)

**Phase:** Phase 2 (before multi-mission scale) — critical to implement before Phase 3

---

### Pitfall 8: Recursion Limit Hit as a Symptom, Not the Cause — Masking Infinite Loops

**What goes wrong:** The current convention `recursion_limit = max_steps * 3` prevents crashes but can mask infinite loops. When a graph node re-enters `plan` without advancing `step` (e.g., because the planner produces a duplicate tool call that the deduplication guard rejects, and no fallback advances the step counter), the graph cycles until the recursion limit is hit. The error surface is `GraphRecursionError`, which looks like a configuration issue rather than a control flow bug.

**Why it happens:** The duplicate-call guard in `seen_tool_signatures` blocks the action but currently returns to `plan` without incrementing `step`. If the planner re-emits the same duplicate for N retries, the system loops N times and uses N recursion slots. This is already partially mitigated by `max_duplicate_tool_retries`, but the interaction between the fallback planner, the deduplication guard, and the policy node creates non-obvious cycle paths.

**Consequences:** Increasing `max_steps` to fix a `GraphRecursionError` hides the underlying loop. The run appears to complete but produces incorrect results (the looping step contributed no useful work). Tests that mock the provider can't easily detect this because mock providers return valid actions.

**Prevention:**
- Do not raise `max_steps` to fix a `GraphRecursionError` — the existing CLAUDE.md convention is correct.
- Add a loop detector: if `step` has not increased in 3 consecutive node executions (same step number), treat it as an infinite loop and route to `finalize` with a `status=failed` sentinel.
- In stress testing, inject a provider that returns the same tool call repeatedly and assert the graph terminates cleanly within `max_duplicate_tool_retries * 2` steps.

**Detection (warning signs):**
- `GraphRecursionError` appears in logs — always investigate the node execution trace before raising the limit
- `retry_counts["duplicate_tool"]` reaches `max_duplicate_tool_retries` in normal runs
- Step counter in logs shows repeated step numbers without advancing

**Phase:** Phase 2 (stability hardening); Phase 4 (stress testing)

---

### Pitfall 9: FastAPI Async Context — LangGraph Lifecycle Objects Initialized Before App Startup

**What goes wrong:** `LangGraphOrchestrator` instantiates `SQLiteMemoStore`, `SQLiteCheckpointStore`, and the provider at `__init__` time. When used inside a FastAPI application, if the orchestrator is created at module import time (not inside FastAPI's `lifespan` context manager), the database connections and provider clients are initialized before the app's async event loop starts. This causes `aiosqlite` handles to belong to the wrong event loop and context managers to receive incomplete initialization.

**Why it happens:** A common FastAPI pattern creates service objects as module-level globals. This works for synchronous objects but breaks async resources (including any SQLite async variants) because they must be created inside the running event loop.

**Consequences:** Intermittent `RuntimeError: Event loop is closed` or `asyncio: no current event loop` errors in production. The errors appear non-deterministically under load, making them hard to reproduce in unit tests.

**Prevention:**
- Initialize `LangGraphOrchestrator` inside FastAPI's `lifespan` context manager, not at module level:
  ```python
  @asynccontextmanager
  async def lifespan(app: FastAPI):
      app.state.orchestrator = LangGraphOrchestrator()
      yield
      # cleanup
  ```
- Never store the orchestrator as a module-level singleton if the project uses async SQLite.
- For Phase 4, test the FastAPI endpoint with at least 2 concurrent requests before declaring the service production-ready.

**Detection (warning signs):**
- `RuntimeError: Event loop is closed` in uvicorn logs
- Works correctly with `uvicorn --workers 1` but fails with `--workers N`
- Errors appear only after the first request, not on startup

**Phase:** Phase 4 (FastAPI service layer)

---

### Pitfall 10: Integration Tests Hitting Live Providers in CI — Flaky Tests and Token Cost Leakage

**What goes wrong:** The existing `ScriptedProvider` pattern in `tests/integration/test_langgraph_flow.py` correctly avoids live API calls. However, Phase 2 and Phase 3 will introduce new integration tests for ToolNode behavior and multi-agent handoffs. Without a deliberate policy, it is easy to write tests that import the real `build_provider()` and accidentally exercise the live API when `P1_PROVIDER` and API keys are set in the environment (which they are on developer machines).

**Why it happens:** Python test discovery runs all tests in all environments. If CI has `OPENAI_API_KEY` set (e.g., for a live eval job), test files that call `build_provider()` will consume tokens. This has cost implications and makes tests flaky when provider rate limits or network issues occur.

**Consequences:** CI green on token-rich environments, red on token-poor (other contributors, PR CI). Token costs accumulate silently. Test failures appear to be "flaky" but are actually provider rate limit errors.

**Prevention:**
- Gate all integration tests that use `ScriptedProvider` with a `pytest.mark` (e.g., `@pytest.mark.integration`) and configure CI to run only that mark by default.
- Add a `conftest.py` fixture that asserts `isinstance(provider, ScriptedProvider)` or `MockProvider` in all integration tests, failing immediately if a live provider is detected.
- Create a separate CI job (manually triggered or nightly) for live provider smoke tests with explicit budget limits.
- Never call `build_provider()` in test setup without patching it.

**Detection (warning signs):**
- Test runtime spikes from 5s to 30+ seconds on the integration suite — indicates live API calls
- Tests pass locally but fail in PR CI with `ProviderTimeoutError` or rate limit errors
- Token usage appears in provider dashboards after CI runs

**Phase:** Phase 2 and Phase 4 (CI pipeline)

---

## Minor Pitfalls

---

### Pitfall 11: Cache Poisoning Survives Upgrades — Hardcoded Invalidation Is Fragile

**What goes wrong:** `graph.py` has a `_invalidate_known_poisoned_cache_entries()` method that deletes two specific known-bad cache entries by value hash. This is a workaround that works exactly once per poisoned entry. If the memo store accumulates additional poisoned entries in the future (e.g., a planner writes wrong fibonacci content), the invalidation list must be manually updated — there is no automated detection or self-healing.

**Why it happens:** The current design validates write input only for fibonacci paths (`content_validator.py`). Other write paths skip validation before caching. A planner that writes incorrect content to `pattern_report.txt` will cache the wrong content and reuse it on every subsequent run.

**Prevention:**
- In Phase 2 and 3, extend `content_validator.py` to validate all `write_file` calls against mission expectations before the result enters the cache.
- Add a `cache_poison_score` field to `MemoEvent` that is set by the auditor if a post-run check finds the cached value was wrong. Use this to auto-invalidate on the next run.
- The stress testing phase should include a cache poisoning scenario: inject wrong content, verify the auditor detects it, verify the next run invalidates and re-generates correctly.

**Detection (warning signs):**
- Auditor `output_content_mismatch` check fires on the same mission across multiple runs
- Memo store `retrieve` hits on a key that should have been invalidated
- `policy_flags["cache_reuse_hits"]` increases but mission results worsen over time

**Phase:** Phase 2 (content validation extension); Phase 4 (stress testing)

---

### Pitfall 12: Token Budget Fields Exist in State But Are Never Enforced

**What goes wrong:** `RunState` has `token_budget_remaining` (default 100,000) and `token_budget_used` fields. These are never updated by the provider or the policy node. Any specialist routing decision based on the token budget will read stale data. When specialist subgraphs with separate model calls are added, the parent graph cannot limit total token consumption across all specialists because it does not know what each specialist spent.

**Prevention:**
- Before Phase 3, wire token usage tracking: update `token_budget_used` and `token_budget_remaining` in the provider's `generate()` response handling using the `usage` field from the API response.
- In Phase 3, pass `token_budget` from `TaskHandoff` to the specialist subgraph and have the specialist track against its allotted budget.
- The `ModelRouter` stub should read `token_budget_remaining` and route to a cheaper/faster model when budget is low.

**Phase:** Phase 2 (token tracking wiring); Phase 3 (per-specialist budget enforcement)

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|----------------|------------|
| Phase 2: LangGraph upgrade | Silent tool error behavior change in `langgraph-prebuilt>=1.0.1` | Pin exact prebuilt version; set `handle_tool_errors=True` explicitly |
| Phase 2: ToolNode adoption | `ToolNode.afunc` signature break in prebuilt 1.0.2 | Do not subclass `ToolNode`; use composition instead |
| Phase 2: Single-agent hardening | Message history bloat before multi-agent scale | Implement compaction at 40-message threshold |
| Phase 3: Subgraph delegation | State key bleeding from specialist into parent | Use isolated state pattern with narrow `HandoffResult` output |
| Phase 3: Parallel missions with Send | Plain list fields get overwritten not merged | Add `Annotated[list, operator.add]` reducers before any `Send` usage |
| Phase 3: Subgraph checkpointing | Subgraph state not persisted if compiled with its own checkpointer | Compile subgraphs without checkpointer; let parent propagate |
| Phase 3: Message accumulation | Specialist agent messages bloating parent `messages` list | Store specialist messages in subgraph private state only |
| Phase 4: FastAPI integration | Orchestrator initialized at module level breaks async event loop | Initialize inside `lifespan` context manager |
| Phase 4: SQLite under load | Concurrent writes produce `database is locked` | Migrate to Postgres for production; WAL mode for dev |
| Phase 4: CI pipeline | Live provider calls in integration tests produce flaky CI | Enforce `ScriptedProvider` in all non-smoke CI jobs |
| Phase 4: Stress testing | Recursion limit hit disguises infinite loops | Add loop detector; never raise `max_steps` to fix `GraphRecursionError` |
| Phase 4: Observability | Langfuse traces flat with no node hierarchy | Apply `@observe` to all graph node methods before production |

---

## Sources

- [LangGraph Subgraphs — official docs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs) — HIGH confidence
- [LangGraph v1 migration guide](https://docs.langchain.com/oss/python/migrate/langgraph-v1) — HIGH confidence
- [Breaking Change in langgraph-prebuilt==1.0.2 — GitHub Issue #6363](https://github.com/langchain-ai/langgraph/issues/6363) — HIGH confidence
- [Tool node error handling disabled by default after 1.0.1 — GitHub Issue #6486](https://github.com/langchain-ai/langgraph/issues/6486) — HIGH confidence
- [Subgraph state not inserted to persistence db — GitHub Issue #2142](https://github.com/langchain-ai/langgraph/issues/2142) — HIGH confidence
- [langgraph-checkpoint-sqlite SQL injection CVE-2025-67644](https://www.cvedetails.com/cve/CVE-2025-67644/) — HIGH confidence
- [LangGraph persistence docs — SQLite not recommended for production](https://docs.langchain.com/oss/python/langgraph/persistence) — HIGH confidence
- [Best practices for parallel nodes (fanouts) — LangChain forum](https://forum.langchain.com/t/best-practices-for-parallel-nodes-fanouts/1900) — HIGH confidence
- [Parallel message merge issues — LangChain forum](https://forum.langchain.com/t/seeking-help-with-some-merge-message-issues-when-langgraph-is-called-in-parallel/3007) — MEDIUM confidence
- [MultipleSubgraphsError — LangGraph Discussion #2095](https://github.com/langchain-ai/langgraph/discussions/2095) — HIGH confidence
- [Unexpected behavior of state reducer in subgraph — GitHub Issue #3587](https://github.com/langchain-ai/langgraph/issues/3587) — HIGH confidence
- [Scaling LangGraph Agents: Parallelization, Subgraphs, and Map-Reduce Trade-Offs](https://aipractitioner.substack.com/p/scaling-langgraph-agents-parallelization) — MEDIUM confidence
- [FastAPI LangGraph async lifecycle pitfall — Dev.to guide](https://dev.to/kasi_viswanath/streaming-ai-agent-with-fastapi-langgraph-2025-26-guide-1nkn) — MEDIUM confidence
- [Managing Context History in Agentic Systems with LangGraph — Medium](https://medium.com/@thakur.rana/managing-context-history-in-agentic-systems-with-langgraph-3645610c43fe) — MEDIUM confidence
- [Multi-agent workflows often fail — GitHub Blog](https://github.blog/ai-and-ml/generative-ai/multi-agent-workflows-often-fail-heres-how-to-engineer-ones-that-dont/) — MEDIUM confidence
- [GRAPH_RECURSION_LIMIT official troubleshooting docs](https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT) — HIGH confidence
- [Open Source Observability for LangGraph — Langfuse](https://langfuse.com/guides/cookbook/integration_langgraph) — HIGH confidence
