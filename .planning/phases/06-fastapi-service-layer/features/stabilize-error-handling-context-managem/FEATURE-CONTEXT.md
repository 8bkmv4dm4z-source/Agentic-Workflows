# Phase 6: FastAPI Service Layer — Feature Context

**Mode:** Stabilize
**Feature:** Error handling hardening, CLI log-replay test coverage, RunStore edge cases, context management
**Gathered:** 2026-03-06
**Status:** Ready for planning

<domain>
## Feature Boundary

Phase 6 scope: Wrap LangGraphOrchestrator.run() in a FastAPI HTTP service with SSE
streaming, run persistence, API client CLI, and eval harness.

This feature: Harden the existing Phase 6 service — graceful provider failure recovery in
SSE streams, replay-based CLI tests from real run logs, RunStore edge case fixes, and a
context pruning system in the orchestrator to prevent Ollama 500s from context overflow.

Does NOT extend phase scope. Does NOT modify ROADMAP.md.

</domain>

<decisions>
## Implementation Decisions

### Error Handling — Provider Failures in SSE Streams
- On LLM provider 500 errors: retry N times (configurable via `PLAN_RETRY_COUNT` env var, default 3)
  before giving up — the orchestrator already has retry logic; ensure it surfaces correctly to the API layer
- On final failure: emit SSE error event `{type: "error", detail: "provider_error", run_id: "..."}`,
  close the stream, and mark the run as `"failed"` in RunStore via `update_run`
- Response format: SSE error event only (no pre-stream HTTP 500 once the EventSourceResponse has started)
- Exception must be caught in the SSE producer coroutine so the stream closes cleanly rather than hanging

### Test Coverage — user_run.py Log-Replay Mock Runs
- Use existing captured run logs (from `.tmp/` or log files) as source material for fixtures
- Mechanism: `httpx.MockTransport` replaying pre-recorded SSE event sequences (not a live server)
  — this is the "postman-style" delivery mechanism: recorded, deterministic, no Ollama required
- Fixture strategy: parse real run logs → extract SSE event sequences → store as Python fixtures
  in `tests/fixtures/sse_sequences/` (list of `{event, data}` dicts per scenario)
- Test scenarios to cover:
  1. Happy path: full streaming run (node_start → node_end → run_complete events render correctly)
  2. Error event rendering: SSE stream contains `{type: "error"}` → user_run.py prints error and exits non-zero
  3. Resume/reconnect: user_run.py calls GET /run/{id}/stream and renders partial run state
- CLI tests live in `tests/unit/test_user_run.py`

### RunStore Edge Cases
- **Large result_json**: Add a `MAX_RESULT_JSON_BYTES` cap (default 512KB). If the serialized
  RunResult exceeds this, truncate `tool_history` entries to `{tool, args_summary, result_truncated: true}`
  before storing — keep mission_reports intact. Log a warning when truncation occurs.
- **DB path creation**: `SQLiteRunStore.__init__` must call `os.makedirs(os.path.dirname(db_path), exist_ok=True)`
  before `sqlite3.connect()` — currently crashes if `.tmp/` doesn't exist
- **Concurrent update_run races**: Add a concurrency test using `asyncio.gather` with 5 simultaneous
  `update_run` calls — verify WAL + `busy_timeout=5000` absorbs all writes without `OperationalError`

### Context Management — "Read, Plan, Then Forget"
- **Location:** `src/agentic_workflows/orchestration/langgraph/graph.py` (in the plan step,
  before calling the provider)
- **Research required:** planner must research and recommend the approach before implementation.
  Key questions for research:
  1. Does LangGraph expose a `trim_messages()` utility? (it does — `langgraph.prebuilt` or
     `langchain_core.messages.trim_messages`)
  2. What token estimation is available without a live model call? (len(text)//4 heuristic vs tiktoken)
  3. Summary strategy: truncate oldest tool results vs. summarize them into one message?
- **Target behavior:** Before each plan call, if estimated message history exceeds
  `OLLAMA_NUM_CTX * 0.75` tokens, evict oldest tool result messages first (keep system prompt
  + last K exchanges). Evicted full results are already in RunStore — the LLM gets a one-line
  summary placeholder: `"[tool_result: read_file, 7495 bytes, stored in run_store]"`
- **Config:** `CTX_EVICTION_RATIO` env var (default 0.75) — evict when history > ratio * num_ctx
- **Scope note:** This touches `graph.py` (orchestrator core) which is shared across all phases.
  Keep changes isolated to the `_build_messages()` / message-assembly step; do not touch
  provider API call logic. If research reveals a cleaner LangGraph-native approach, prefer that.

### Claude's Discretion
- Exact httpx.MockTransport implementation shape (response builder vs. side_effect list)
- Token estimation method (len//4 is acceptable given we own the model config)
- Whether evicted context summaries are stored back in RunStore for audit purposes

</decisions>

<acceptance_criteria>
## Done When

- [ ] Provider 500 errors (Ollama context overflow, network failures) result in a clean SSE
      `{type: "error"}` event + stream close, not a hanging connection or silent timeout
- [ ] Run is marked `status="failed"` in RunStore when provider fails after all retries
- [ ] `tests/unit/test_user_run.py` covers: happy path render, error event exit, reconnect —
      all using httpx mock transport (no live server required)
- [ ] SSE fixture sequences exist in `tests/fixtures/sse_sequences/` derived from real run logs
- [ ] `SQLiteRunStore` creates `.tmp/` directory on first init without crashing
- [ ] RunResult > 512KB is stored with truncated tool_history (warning logged); mission_reports intact
- [ ] Concurrency test: 5 simultaneous `update_run` calls complete without `OperationalError`
- [ ] Context eviction active in graph.py: message history trimmed before provider call when
      estimated tokens exceed `CTX_EVICTION_RATIO * OLLAMA_NUM_CTX`
- [ ] After eviction, a summary placeholder message replaces dropped tool results in LLM context
- [ ] All 536 existing tests continue to pass

</acceptance_criteria>

<deferred>
## Deferred Ideas

- Postman Collection JSON export (`.json` file for manual Postman import) — mock transport covers
  automated testing; manual Postman collection is a separate UX concern
- Per-provider context limits (Groq/Anthropic have much larger windows) — eviction only triggers
  when `OLLAMA_NUM_CTX` is set; Anthropic/Groq paths unaffected
- Semantic summarization of tool results via a small LLM call — too complex for stabilization;
  placeholder string is sufficient
- Streaming context eviction (evict mid-stream as tokens accumulate) — evict only at plan step start

</deferred>

---

*Phase: 06-fastapi-service-layer*
*Feature context gathered: 2026-03-06*
