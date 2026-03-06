---
phase: 06-fastapi-service-layer
feature: stabilize-error-handling-context-managem
type: execute
wave: 1
depends_on: []
files_modified:
  - src/agentic_workflows/orchestration/langgraph/provider.py
  - src/agentic_workflows/orchestration/langgraph/graph.py
  - src/agentic_workflows/storage/sqlite.py
  - tests/unit/test_run_store.py
  - tests/unit/test_provider_retry.py
  - tests/fixtures/__init__.py
  - tests/fixtures/sse_sequences/__init__.py
  - tests/fixtures/sse_sequences/happy_path.py
  - tests/fixtures/sse_sequences/error_event.py
  - tests/fixtures/sse_sequences/reconnect.py
  - tests/unit/test_user_run.py
autonomous: true
requirements:
  - PROD-01
  - PROD-02

rollback_notes: |
  provider.py: revert _is_retryable_timeout_error to remove http_500 marker
  graph.py: revert _compact_messages to pre-token-budget version (remove
    _evict_tool_result_messages / the token-budget guard added at top of
    _compact_messages); the original count-based path is unchanged
  storage/sqlite.py: revert MAX_RESULT_JSON_BYTES truncation block in save_run
    (the os.makedirs fix and WAL/busy_timeout are already present — do NOT revert those)
  tests: safe to leave new test files in place; they do not affect runtime behaviour

must_haves:
  truths:
    - "Ollama HTTP 500 errors (context overflow) surface as a clean SSE error event + stream close, not a hanging connection"
    - "Run is marked status=failed in RunStore when provider fails after all retries"
    - "test_user_run.py covers happy path render, error event exit, and reconnect using httpx MockTransport (no live server)"
    - "SSE fixture sequences exist in tests/fixtures/sse_sequences/ and are importable"
    - "RunResult > 512KB is stored with truncated tool_history; mission_reports intact; warning logged"
    - "Concurrent update_run: 5 simultaneous calls complete without OperationalError"
    - "Context eviction trims message history before each plan call when estimated tokens exceed CTX_EVICTION_RATIO * OLLAMA_NUM_CTX"
    - "Evicted tool results are replaced by one-line placeholder messages in LLM context"
    - "SQLiteRunStore creates .tmp/ directory on first init without crashing"
    - "All 536 existing tests continue to pass"
  artifacts:
    - path: "src/agentic_workflows/orchestration/langgraph/provider.py"
      provides: "Extended _is_retryable_timeout_error to include http_500 / context_length"
      contains: "http 500"
    - path: "src/agentic_workflows/orchestration/langgraph/graph.py"
      provides: "_evict_tool_result_messages called from _compact_messages when OLLAMA_NUM_CTX set"
      contains: "_evict_tool_result_messages"
    - path: "src/agentic_workflows/storage/sqlite.py"
      provides: "MAX_RESULT_JSON_BYTES cap with tool_history truncation in save_run"
      contains: "MAX_RESULT_JSON_BYTES"
    - path: "tests/fixtures/sse_sequences/happy_path.py"
      provides: "Representative SSE event sequence for a successful run"
      exports: ["HAPPY_PATH_EVENTS"]
    - path: "tests/unit/test_user_run.py"
      provides: "3 CLI rendering tests using httpx.MockTransport"
      contains: "MockTransport"
  key_links:
    - from: "src/agentic_workflows/orchestration/langgraph/graph.py"
      to: "src/agentic_workflows/orchestration/langgraph/provider.py"
      via: "_compact_messages calls _evict_tool_result_messages; provider retry logic surfaces ProviderTimeoutError"
      pattern: "_evict_tool_result_messages"
    - from: "src/agentic_workflows/api/routes/run.py"
      to: "src/agentic_workflows/storage/sqlite.py"
      via: "update_run(status=failed) on ProviderTimeoutError reaching producer except block"
      pattern: "status.*failed"
    - from: "tests/unit/test_user_run.py"
      to: "tests/fixtures/sse_sequences/happy_path.py"
      via: "imports HAPPY_PATH_EVENTS, wraps in httpx.MockTransport for stream_run() test"
      pattern: "HAPPY_PATH_EVENTS"
---

<objective>
Harden Phase 6 service: provider 500 error surfacing, user_run.py mock transport tests, RunStore edge case fixes, and token-budget context eviction.

Purpose: Prevent Ollama context overflow from causing hanging SSE connections; ensure the CLI test suite covers SSE rendering without a live server; protect the DB from giant RunResult blobs; and add a lightweight token-budget eviction layer to graph.py so long runs do not exceed Ollama's num_ctx window.

Output: Patched provider.py (http_500 retryable), new _evict_tool_result_messages in graph.py, RunStore truncation + concurrency test, SSE fixture sequences, and test_user_run.py with MockTransport.
</objective>

<context>
@.planning/PROJECT.md
@.planning/STATE.md
@.planning/phases/06-fastapi-service-layer/06-01-SUMMARY.md
@.planning/phases/06-fastapi-service-layer/06-02-SUMMARY.md
@.planning/phases/06-fastapi-service-layer/06-03-SUMMARY.md

<interfaces>
<!-- Key contracts for this feature. Extracted from current codebase. -->

From src/agentic_workflows/orchestration/langgraph/provider.py:
```python
def _is_retryable_timeout_error(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = ("timeout", "timed out", "connection error", "connection reset",
               "temporarily unavailable", "service unavailable",
               "read timeout", "connect timeout")
    return any(marker in text for marker in markers)

class _RetryingProviderBase:
    def __init__(self) -> None:
        self.max_retries = _env_int("P1_PROVIDER_MAX_RETRIES", DEFAULT_PROVIDER_MAX_RETRIES)
    # After all retries exhausted: raises ProviderTimeoutError

class OllamaProvider(_RetryingProviderBase):
    self.num_ctx = _env_int("OLLAMA_NUM_CTX", 0)  # 0 means "not set"
```

From src/agentic_workflows/orchestration/langgraph/graph.py:
```python
def _compact_messages(self, state: RunState, *, max_messages: int = 50) -> None:
    # Called at top of _plan_next_action (line 582) — already handles count-based compaction.
    # New token-budget eviction must be inserted as a second guard BEFORE the count guard.

# Messages are plain dicts: {"role": "system"|"user"|"assistant", "content": str}
# Tool results injected as role="user" messages with content like:
#   "TOOL RESULT (read_file):\n{large json blob}"
# Or via state["tool_history"]: list[ToolRecord] (NOT in messages list)
```

From src/agentic_workflows/storage/sqlite.py:
```python
async def save_run(self, run_id: str, *, status: str, **fields: Any) -> None:
    # fields.get("result") is serialized to result_json via _to_json()
    # result dict contains: answer, tools_used (list[ToolRecord]), mission_report, ...
    # tools_used entries are dicts: {"call": ..., "tool": str, "args": dict, "result": dict}

async def update_run(self, run_id: str, **fields: Any) -> None:
    # Uses WAL + busy_timeout=5000 -- concurrent writes absorbed by SQLite

def _to_json(value: Any) -> str | None:
    return json.dumps(value, default=str)
```

From src/agentic_workflows/api/routes/run.py:
```python
# producer() already has:
except Exception as exc:
    log.error("run.producer_error", ...)
    await run_store.update_run(run_id, status="failed")
    error_evt = make_error(run_id, str(exc))
    await send_stream.send(error_evt)
# So ProviderTimeoutError raised from within _run_streaming() is already caught.
# The gap: Ollama HTTP 500 not currently in _is_retryable_timeout_error markers.
```

From src/agentic_workflows/cli/user_run.py:
```python
async def stream_run(user_input: str, prior_context=None) -> tuple[str, str]:
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=300.0) as client:
        async with client.stream("POST", "/run", json=payload, headers=headers) as resp:
            async for line in resp.aiter_lines():
                # parses SSE lines, calls _render_event(event)
    return run_id, answer

def _render_event(event: dict) -> None:
    # Renders node_start, node_end, run_complete, state_diff, error events
    # On error type: console.print("[bold red]ERROR: {detail}[/]")
```

SSE event shapes (from src/agentic_workflows/api/sse.py):
```python
make_node_start(node, run_id)  -> {"type": "node_start", "tier": "ui", "node": ..., "run_id": ..., "timestamp": ...}
make_node_end(node, run_id)    -> {"type": "node_end",   "tier": "ui", "node": ..., "run_id": ..., "updates": {}, "timestamp": ...}
make_run_complete(run_id)      -> {"type": "run_complete","tier": "ui", "run_id": ..., "result": {}, "timestamp": ...}
make_error(run_id, detail)     -> {"type": "error",       "tier": "ui", "run_id": ..., "detail": ..., "timestamp": ...}
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Provider 500 error surfacing + RunStore edge case hardening</name>
  <files>
    src/agentic_workflows/orchestration/langgraph/provider.py,
    src/agentic_workflows/storage/sqlite.py,
    tests/unit/test_run_store.py,
    tests/unit/test_provider_retry.py
  </files>
  <behavior>
    - test_http_500_is_retryable: _is_retryable_timeout_error returns True for exception with "http 500", "status code 500", "context length exceeded"
    - test_non_retryable_still_raises: ValueError("bad input") returns False from _is_retryable_timeout_error
    - test_large_result_truncated: save_run with result containing tool_history > 512KB total bytes stores result with tool_history entries replaced by {tool, args_summary, result_truncated: true}; mission_reports remain intact
    - test_large_result_warning_logged: same scenario emits a structlog warning with key "run_store.result_truncated"
    - test_result_under_limit_not_truncated: result under 512KB stored without modification
    - test_concurrent_update_run: asyncio.gather with 5 simultaneous update_run calls all succeed, final status is deterministic
    - test_makedirs_on_init: SQLiteRunStore instantiated with a path under a nonexistent temp directory does not raise
  </behavior>
  <action>
1. **src/agentic_workflows/orchestration/langgraph/provider.py** — Extend `_is_retryable_timeout_error`:

   Add these markers to the existing tuple (add after "connect timeout"):
   ```python
   "http 500",
   "status code 500",
   "context length exceeded",
   "context window",
   "request entity too large",
   "payload too large",
   ```
   This ensures Ollama context-overflow HTTP 500 responses surface as retryable `ProviderTimeoutError` rather than unclassified exceptions. After all retries exhaust, `ProviderTimeoutError` propagates to the SSE producer's except block, which already calls `update_run(status="failed")` and emits `make_error`.

   Also add `PLAN_RETRY_COUNT` env var support: read `int(os.environ.get("PLAN_RETRY_COUNT", "0"))` in `_RetryingProviderBase.__init__` and OR it with `P1_PROVIDER_MAX_RETRIES` using `max(self.max_retries, plan_retry_count)`. Log both values at debug level with structlog.

2. **src/agentic_workflows/storage/sqlite.py** — Add `MAX_RESULT_JSON_BYTES` cap to `save_run`:

   Add module-level constant:
   ```python
   import structlog as _structlog
   _log = _structlog.get_logger()
   MAX_RESULT_JSON_BYTES = int(os.environ.get("MAX_RESULT_JSON_BYTES", str(512 * 1024)))
   ```

   In `save_run`, before the `_to_json(fields.get("result"))` call, add a truncation guard:
   ```python
   result_value = fields.get("result")
   if result_value is not None:
       candidate = _to_json(result_value) or ""
       if len(candidate.encode()) > MAX_RESULT_JSON_BYTES:
           _log.warning("run_store.result_truncated",
                        run_id=run_id,
                        original_bytes=len(candidate.encode()),
                        limit_bytes=MAX_RESULT_JSON_BYTES)
           # Truncate tool_history entries; keep mission_reports intact
           truncated = dict(result_value)
           tool_history = truncated.get("tools_used", [])
           truncated["tools_used"] = [
               {
                   "tool": t.get("tool", "") if isinstance(t, dict) else str(t),
                   "args_summary": str(t.get("args", ""))[:200] if isinstance(t, dict) else "",
                   "result_truncated": True,
               }
               for t in tool_history
           ]
           result_value = truncated
   ```
   Replace the `_to_json(fields.get("result"))` argument with `_to_json(result_value)` in the INSERT statement.

3. **tests/unit/test_run_store.py** — Add tests for the new behaviors:

   Add `test_large_result_truncated` and `test_large_result_warning_logged`:
   - Build a result dict with `tools_used` containing 100 entries each with a 6KB `result` field (total ~600KB).
   - Call `await store.save_run(run_id, status="completed", result=large_result)`.
   - `await store.get_run(run_id)` then `json.loads(row["result_json"])` and assert `tools_used[0]["result_truncated"] == True` and `"mission_report"` is intact.
   - For warning test: patch `_structlog.get_logger()` (or use `caplog` if structlog is configured to emit to Python logging) and verify the warning key appears.

   Add `test_concurrent_update_run`:
   ```python
   @pytest.mark.asyncio
   async def test_concurrent_update_run(store):
       await store.save_run("conc", status="running")
       results = await asyncio.gather(*[
           store.update_run("conc", status="running", missions_completed=i)
           for i in range(5)
       ], return_exceptions=True)
       errors = [r for r in results if isinstance(r, Exception)]
       assert errors == [], f"Concurrent update_run raised: {errors}"
       row = await store.get_run("conc")
       assert row["status"] == "running"  # all updates used same status
   ```

   Add `test_makedirs_on_init` to verify SQLiteRunStore creates missing directories:
   ```python
   @pytest.mark.asyncio
   async def test_makedirs_on_init(tmp_path):
       """SQLiteRunStore must not crash if its parent directory does not yet exist."""
       db_path = str(tmp_path / "nonexistent_subdir" / "runs.db")
       store = SQLiteRunStore(db_path=db_path)
       await store.initialize()  # should create the directory and schema without error
       await store.save_run("init-test", status="running")
       row = await store.get_run("init-test")
       assert row is not None
   ```

   Add `test_http_500_is_retryable` in a new `tests/unit/test_provider_retry.py` file:
   ```python
   from agentic_workflows.orchestration.langgraph.provider import _is_retryable_timeout_error
   def test_http_500_is_retryable():
       assert _is_retryable_timeout_error(Exception("Ollama HTTP 500 error"))
   def test_context_length_is_retryable():
       assert _is_retryable_timeout_error(Exception("context length exceeded: 32768"))
   def test_non_retryable_value_error():
       assert not _is_retryable_timeout_error(ValueError("bad request"))
   ```
  </action>
  <verify>
    <automated>cd /home/nir/dev/agent_phase0 && pytest tests/unit/test_run_store.py tests/unit/test_provider_retry.py -x -q 2>&1</automated>
  </verify>
  <done>
    - _is_retryable_timeout_error returns True for "http 500", "context length exceeded"
    - save_run with result > 512KB stores truncated tool_history with mission_reports intact
    - structlog warning emitted on truncation
    - 5 concurrent update_run calls complete without OperationalError
    - SQLiteRunStore instantiated with nonexistent parent directory does not raise (test_makedirs_on_init passes)
    - All existing test_run_store.py tests still pass
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: SSE fixture sequences + user_run.py MockTransport tests</name>
  <files>
    tests/fixtures/__init__.py,
    tests/fixtures/sse_sequences/__init__.py,
    tests/fixtures/sse_sequences/happy_path.py,
    tests/fixtures/sse_sequences/error_event.py,
    tests/fixtures/sse_sequences/reconnect.py,
    tests/unit/test_user_run.py
  </files>
  <behavior>
    - test_happy_path_render: stream_run() against MockTransport replaying HAPPY_PATH_EVENTS prints node_start, node_end, run_complete to Rich console; returns (run_id, answer) where run_id matches fixture value
    - test_error_event_exits_nonzero: stream_run() against MockTransport replaying ERROR_EVENTS returns ("", "") and calls console.print with "[bold red]ERROR:" prefix
    - test_reconnect_stream_renders: stream_run with a MockTransport replaying RECONNECT_EVENTS (partial run state: only node_end + run_complete, no initial node_start) renders without crashing and returns run_id
  </behavior>
  <action>
1. **tests/fixtures/__init__.py** — Empty init (create if missing).

2. **tests/fixtures/sse_sequences/__init__.py** — Empty init.

3. **tests/fixtures/sse_sequences/happy_path.py** — Define `HAPPY_PATH_EVENTS` as a list of SSE event dicts derived from the known event types in `src/agentic_workflows/api/sse.py`. These are representative sequences (no real run logs produced SSE format — only process logs exist in .tmp/):

   ```python
   """Happy-path SSE fixture: full streaming run sequence."""
   from __future__ import annotations

   HAPPY_PATH_RUN_ID = "pub_abc123happypath"

   HAPPY_PATH_EVENTS: list[dict] = [
       {"type": "node_start", "tier": "ui", "node": "plan", "run_id": HAPPY_PATH_RUN_ID, "timestamp": "2026-03-06T00:00:00+00:00"},
       {"type": "node_end",   "tier": "ui", "node": "plan", "run_id": HAPPY_PATH_RUN_ID, "updates": {}, "timestamp": "2026-03-06T00:00:01+00:00"},
       {"type": "node_start", "tier": "ui", "node": "tool", "run_id": HAPPY_PATH_RUN_ID, "timestamp": "2026-03-06T00:00:02+00:00"},
       {"type": "node_end",   "tier": "ui", "node": "tool", "run_id": HAPPY_PATH_RUN_ID, "updates": {}, "timestamp": "2026-03-06T00:00:03+00:00"},
       {"type": "node_start", "tier": "ui", "node": "plan", "run_id": HAPPY_PATH_RUN_ID, "timestamp": "2026-03-06T00:00:04+00:00"},
       {"type": "node_end",   "tier": "ui", "node": "plan", "run_id": HAPPY_PATH_RUN_ID, "updates": {}, "timestamp": "2026-03-06T00:00:05+00:00"},
       {
           "type": "run_complete", "tier": "ui", "run_id": HAPPY_PATH_RUN_ID,
           "result": {"answer": "Task completed.", "mission_report": [], "audit_report": None},
           "timestamp": "2026-03-06T00:00:06+00:00",
       },
   ]
   ```

4. **tests/fixtures/sse_sequences/error_event.py** — Define `ERROR_EVENTS`:
   ```python
   """Error-event SSE fixture: stream contains a provider error."""
   from __future__ import annotations

   ERROR_RUN_ID = "pub_abc123errorrun"

   ERROR_EVENTS: list[dict] = [
       {"type": "node_start", "tier": "ui", "node": "plan", "run_id": ERROR_RUN_ID, "timestamp": "2026-03-06T00:00:00+00:00"},
       {"type": "error", "tier": "ui", "run_id": ERROR_RUN_ID, "detail": "provider_error: Ollama HTTP 500 error", "timestamp": "2026-03-06T00:00:01+00:00"},
   ]
   ```

5. **tests/fixtures/sse_sequences/reconnect.py** — Define `RECONNECT_EVENTS` (partial run — only trailing events as seen on reconnect):
   ```python
   """Reconnect SSE fixture: partial run state (post-reconnect events only)."""
   from __future__ import annotations

   RECONNECT_RUN_ID = "pub_abc123reconnect"

   RECONNECT_EVENTS: list[dict] = [
       {"type": "node_end",     "tier": "ui", "node": "tool", "run_id": RECONNECT_RUN_ID, "updates": {}, "timestamp": "2026-03-06T00:00:10+00:00"},
       {"type": "run_complete", "tier": "ui", "run_id": RECONNECT_RUN_ID, "result": {"answer": "Resumed."}, "timestamp": "2026-03-06T00:00:11+00:00"},
   ]
   ```

6. **tests/unit/test_user_run.py** — Three tests using `httpx.MockTransport`:

   Strategy: `httpx.MockTransport` takes a handler callable `handler(request) -> httpx.Response`. For SSE, build the response body as a concatenated SSE text (each event as `data: {json}\n\n`) with `content-type: text/event-stream`. `stream_run()` in user_run.py uses `client.stream("POST", "/run", ...)` and iterates `aiter_lines()`.

   ```python
   """Tests for src/agentic_workflows/cli/user_run.py using httpx.MockTransport."""
   from __future__ import annotations
   import json
   import io
   from unittest.mock import patch
   import pytest
   import httpx
   from rich.console import Console
   from tests.fixtures.sse_sequences.happy_path import HAPPY_PATH_EVENTS, HAPPY_PATH_RUN_ID
   from tests.fixtures.sse_sequences.error_event import ERROR_EVENTS, ERROR_RUN_ID
   from tests.fixtures.sse_sequences.reconnect import RECONNECT_EVENTS, RECONNECT_RUN_ID

   def _build_sse_body(events: list[dict]) -> bytes:
       """Encode events as SSE wire format: data: {json}\\n\\n per event."""
       return b"".join(
           f"data: {json.dumps(e)}\n\n".encode()
           for e in events
       )

   def _make_transport(events: list[dict]) -> httpx.MockTransport:
       body = _build_sse_body(events)
       def handler(request: httpx.Request) -> httpx.Response:
           return httpx.Response(
               200,
               headers={"content-type": "text/event-stream"},
               content=body,
           )
       return httpx.MockTransport(handler)

   @pytest.mark.asyncio
   async def test_happy_path_render():
       """stream_run() renders node_start/node_end/run_complete and returns correct run_id."""
       transport = _make_transport(HAPPY_PATH_EVENTS)
       import agentic_workflows.cli.user_run as user_run_mod
       buf = io.StringIO()
       test_console = Console(file=buf, highlight=False, markup=True)
       with patch.object(user_run_mod, "console", test_console):
           with patch.object(user_run_mod, "API_BASE_URL", "http://mock"):
               async with httpx.AsyncClient(
                   transport=transport, base_url="http://mock", timeout=10.0
               ) as client:
                   with patch("httpx.AsyncClient", return_value=client):
                       run_id, answer = await user_run_mod.stream_run("test input")

       assert run_id == HAPPY_PATH_RUN_ID
       assert answer == "Task completed."
       output = buf.getvalue()
       assert "plan" in output  # node_start/node_end rendered

   @pytest.mark.asyncio
   async def test_error_event_exit():
       """stream_run() with an error SSE event prints [bold red]ERROR and returns empty strings."""
       transport = _make_transport(ERROR_EVENTS)
       import agentic_workflows.cli.user_run as user_run_mod
       buf = io.StringIO()
       test_console = Console(file=buf, highlight=False, markup=True)
       with patch.object(user_run_mod, "console", test_console):
           with patch.object(user_run_mod, "API_BASE_URL", "http://mock"):
               async with httpx.AsyncClient(
                   transport=transport, base_url="http://mock", timeout=10.0
               ) as real_client:
                   with patch("httpx.AsyncClient", return_value=real_client):
                       run_id, answer = await user_run_mod.stream_run("test input")

       output = buf.getvalue()
       assert "ERROR" in output
       # run_id may be set from first node_start before error; answer should be empty
       assert answer == ""

   @pytest.mark.asyncio
   async def test_reconnect_stream_renders():
       """stream_run() with partial reconnect events (no initial node_start) renders without crashing."""
       transport = _make_transport(RECONNECT_EVENTS)
       import agentic_workflows.cli.user_run as user_run_mod
       buf = io.StringIO()
       test_console = Console(file=buf, highlight=False, markup=True)
       with patch.object(user_run_mod, "console", test_console):
           with patch.object(user_run_mod, "API_BASE_URL", "http://mock"):
               async with httpx.AsyncClient(
                   transport=transport, base_url="http://mock", timeout=10.0
               ) as client:
                   with patch("httpx.AsyncClient", return_value=client):
                       run_id, answer = await user_run_mod.stream_run("resume test")

       assert run_id == RECONNECT_RUN_ID
       output = buf.getvalue()
       assert "Resumed." in output or "Run Complete" in output
   ```

   Note on httpx.MockTransport patch approach: `stream_run()` creates `httpx.AsyncClient(base_url=API_BASE_URL, timeout=300.0)` internally. The cleanest mock approach is to patch `httpx.AsyncClient` in the `agentic_workflows.cli.user_run` module namespace to return a client pre-built with `MockTransport`. Use `unittest.mock.patch("agentic_workflows.cli.user_run.httpx.AsyncClient")` or — simpler and more reliable — use a context variable override. If patching proves complex, add an optional `_client_override: httpx.AsyncClient | None = None` parameter to `stream_run()` for testability (only if needed; prefer mock approach first).
  </action>
  <verify>
    <automated>cd /home/nir/dev/agent_phase0 && pytest tests/unit/test_user_run.py -x -q 2>&1</automated>
  </verify>
  <done>
    - tests/fixtures/sse_sequences/ package exists and is importable
    - HAPPY_PATH_EVENTS, ERROR_EVENTS, RECONNECT_EVENTS defined as lists of dicts
    - test_happy_path_render passes: run_id returned, Rich console printed node names
    - test_error_event_exit passes: "ERROR" in console output, answer empty
    - test_reconnect_stream_renders passes: partial events render without exception
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Token-budget context eviction in graph.py _compact_messages</name>
  <files>
    src/agentic_workflows/orchestration/langgraph/graph.py,
    tests/unit/test_context_eviction.py
  </files>
  <behavior>
    - test_eviction_not_triggered_without_ollama_num_ctx: when OLLAMA_NUM_CTX env var is 0 (not set), _compact_messages makes no evictions regardless of token count
    - test_eviction_not_triggered_under_threshold: with OLLAMA_NUM_CTX=8000 and total tokens < 6000 (0.75 * 8000), no eviction occurs
    - test_eviction_removes_large_tool_results: with OLLAMA_NUM_CTX=8000 and a 7000-token user message containing "TOOL RESULT", _evict_tool_result_messages removes oldest large tool-result messages and inserts placeholder
    - test_eviction_preserves_system_prompt: system message (role=system, first message) is never evicted
    - test_eviction_placeholder_content: evicted messages are replaced by "[tool_result: {tool_name}, {N} bytes, stored in run_store]"
    - test_eviction_stops_when_under_threshold: if evicting one message brings total under threshold, remaining messages are kept
  </behavior>
  <action>
**Research findings applied here:**
- `langchain_core.messages.trim_messages` is available but requires `BaseMessage` objects; graph.py uses plain dicts. The conversion overhead (dict -> BaseMessage -> trim -> dict) adds complexity without benefit. Use direct dict-based filtering instead.
- tiktoken is NOT installed. Token estimation: `sum(len(m.get("content",""))//4 for m in messages)` — the same heuristic already used in `graph.py` lines 833-836 for `token_budget_used` tracking.
- `OLLAMA_NUM_CTX` is already read by `OllamaProvider` at line 249. Graph.py must read it independently via `int(os.environ.get("OLLAMA_NUM_CTX", "0"))`.
- Eviction strategy: oldest-first tool result messages — identified as role="user" messages whose content starts with "TOOL RESULT" or contains that prefix (the existing tool dispatch pattern in `_dispatch_tool_actions`).
- `_compact_messages` is already called at the top of `_plan_next_action` (line 582). The token-budget eviction is added as a new private method called BEFORE the count-based compaction.

**Implementation:**

In `src/agentic_workflows/orchestration/langgraph/graph.py`, add the following method to `LangGraphOrchestrator` (place it adjacent to `_compact_messages`):

```python
def _evict_tool_result_messages(self, state: RunState) -> None:
    """Evict oldest large tool-result messages when token budget nears the context window.

    Only activates when OLLAMA_NUM_CTX is set (> 0).  Evicted messages are replaced
    by a one-line placeholder so the LLM knows the result exists but was pruned.

    The full result is preserved in RunStore/tool_history -- only the LLM context is trimmed.
    """
    import os as _os
    num_ctx = int(_os.environ.get("OLLAMA_NUM_CTX", "0"))
    if num_ctx <= 0:
        return  # Not Ollama or context size unknown -- skip eviction

    eviction_ratio = float(_os.environ.get("CTX_EVICTION_RATIO", "0.75"))
    threshold_tokens = int(num_ctx * eviction_ratio)

    messages = state.get("messages", [])
    estimated_tokens = sum(len(m.get("content", "")) // 4 for m in messages)
    if estimated_tokens <= threshold_tokens:
        return  # Under threshold -- nothing to do

    # Find eviction candidates: role=user messages with large tool results (oldest first)
    # These are injected by _dispatch_tool_actions as:
    #   {"role": "user", "content": "TOOL RESULT ({tool_name}):\n{json_blob}"}
    candidates: list[int] = []
    for i, msg in enumerate(messages):
        if i == 0:
            continue  # Always keep system prompt
        content = msg.get("content", "")
        if msg.get("role") == "user" and content.startswith("TOOL RESULT"):
            candidates.append(i)

    # Evict oldest candidates until we are under threshold
    evicted_indices: set[int] = set()
    for idx in candidates:  # already oldest-first (list order)
        if estimated_tokens <= threshold_tokens:
            break
        msg = messages[idx]
        content = msg.get("content", "")
        # Extract tool name from "TOOL RESULT (tool_name):\n..."
        tool_name = "unknown"
        try:
            after_paren = content[len("TOOL RESULT ("):]
            tool_name = after_paren[:after_paren.index(")")]
        except (ValueError, IndexError):
            pass
        original_bytes = len(content.encode())
        # Replace with placeholder
        messages[idx] = {
            "role": "user",
            "content": f"[tool_result: {tool_name}, {original_bytes} bytes, stored in run_store]",
        }
        evicted_indices.add(idx)
        estimated_tokens -= original_bytes // 4
        self.logger.info(
            "CONTEXT EVICT tool=%s bytes=%s remaining_est_tokens=%s",
            tool_name, original_bytes, estimated_tokens,
        )

    if evicted_indices:
        state["messages"] = messages
```

Then call it at the top of `_compact_messages`, before the existing count-based logic:
```python
def _compact_messages(self, state: RunState, *, max_messages: int = 50) -> None:
    self._evict_tool_result_messages(state)  # token-budget eviction (no-op if OLLAMA_NUM_CTX=0)
    messages = state.get("messages", [])
    if len(messages) <= max_messages:
        return
    # ... rest of existing count-based compaction unchanged ...
```

**tests/unit/test_context_eviction.py** — Unit tests for the new eviction logic:

```python
"""Tests for _evict_tool_result_messages in LangGraphOrchestrator."""
from __future__ import annotations
import os
from unittest.mock import MagicMock, patch
import pytest
from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
from agentic_workflows.orchestration.langgraph.state_schema import new_run_state, ensure_state_defaults

@pytest.fixture
def orch(scripted_provider):  # scripted_provider from conftest.py
    return LangGraphOrchestrator(provider=scripted_provider, max_steps=5)

def _state_with_messages(messages):
    """Build minimal RunState with given messages."""
    state = {
        "messages": messages,
        "run_id": "test-evict",
        "step": 0,
        "tool_history": [],
        "mission_reports": [],
        "pending_action": None,
        "pending_action_queue": [],
        "retry_counts": {},
        "policy_flags": {},
        "token_budget_remaining": 100000,
        "token_budget_used": 0,
        "missions": [],
        "structured_plan": None,
        "mission_contracts": [],
        "active_mission_index": -1,
        "active_mission_id": 0,
        "final_answer": "",
        "mission_ledger": [],
        "memo_events": [],
        "seen_tool_signatures": [],
        "truncated_actions": [],
        "handoff_queue": [],
        "handoff_results": [],
        "active_specialist": "supervisor",
        "rerun_context": {},
        "audit_report": None,
        "mission_tracker": {},
    }
    return state

def test_eviction_not_triggered_without_ollama_num_ctx(orch):
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "TOOL RESULT (read_file):\n" + "x" * 40000},
    ]
    state = _state_with_messages(messages)
    with patch.dict(os.environ, {"OLLAMA_NUM_CTX": "0"}):
        orch._evict_tool_result_messages(state)
    assert state["messages"][1]["content"].startswith("TOOL RESULT")  # not evicted

def test_eviction_not_triggered_under_threshold(orch):
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "TOOL RESULT (read_file):\n" + "x" * 100},
    ]
    state = _state_with_messages(messages)
    # 101 chars total / 4 = ~25 tokens; threshold is 0.75 * 8000 = 6000
    with patch.dict(os.environ, {"OLLAMA_NUM_CTX": "8000", "CTX_EVICTION_RATIO": "0.75"}):
        orch._evict_tool_result_messages(state)
    assert state["messages"][1]["content"].startswith("TOOL RESULT")  # not evicted

def test_eviction_removes_large_tool_results(orch):
    large_content = "TOOL RESULT (read_file):\n" + "x" * 30000  # ~7500 tokens
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": large_content},
        {"role": "assistant", "content": '{"action": "finish", "answer": "done"}'},
    ]
    state = _state_with_messages(messages)
    with patch.dict(os.environ, {"OLLAMA_NUM_CTX": "8000", "CTX_EVICTION_RATIO": "0.75"}):
        orch._evict_tool_result_messages(state)
    evicted_msg = state["messages"][1]
    assert evicted_msg["content"].startswith("[tool_result: read_file,")
    assert "bytes, stored in run_store" in evicted_msg["content"]

def test_eviction_preserves_system_prompt(orch):
    sys_content = "You are an orchestrator."
    messages = [
        {"role": "system", "content": sys_content},
        {"role": "user", "content": "TOOL RESULT (write_file):\n" + "x" * 30000},
    ]
    state = _state_with_messages(messages)
    with patch.dict(os.environ, {"OLLAMA_NUM_CTX": "8000", "CTX_EVICTION_RATIO": "0.75"}):
        orch._evict_tool_result_messages(state)
    assert state["messages"][0]["content"] == sys_content  # system prompt unchanged

def test_eviction_stops_when_under_threshold(orch):
    """With two large messages, only the first (oldest) is evicted if that brings under threshold."""
    large_content_1 = "TOOL RESULT (file1):\n" + "x" * 20000
    large_content_2 = "TOOL RESULT (file2):\n" + "x" * 20000
    # total ~10000 tokens, threshold 0.75*8000=6000; evicting one (~5000t) brings to ~5000 < 6000
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": large_content_1},
        {"role": "user", "content": large_content_2},
    ]
    state = _state_with_messages(messages)
    with patch.dict(os.environ, {"OLLAMA_NUM_CTX": "8000", "CTX_EVICTION_RATIO": "0.75"}):
        orch._evict_tool_result_messages(state)
    # First message evicted (placeholder), second may or may not be depending on remaining tokens
    assert state["messages"][1]["content"].startswith("[tool_result:")
```
  </action>
  <verify>
    <automated>cd /home/nir/dev/agent_phase0 && pytest tests/unit/test_context_eviction.py -x -q 2>&1</automated>
  </verify>
  <done>
    - _evict_tool_result_messages is a new private method on LangGraphOrchestrator
    - No-ops when OLLAMA_NUM_CTX=0 (env var not set or set to 0)
    - No-ops when estimated tokens <= CTX_EVICTION_RATIO * OLLAMA_NUM_CTX
    - Evicts oldest role=user "TOOL RESULT (...)" messages oldest-first until under threshold
    - Evicted content replaced by "[tool_result: {tool_name}, {N} bytes, stored in run_store]"
    - System prompt (messages[0]) is never evicted
    - Called at top of _compact_messages before count-based compaction
    - All 6 unit tests pass
    - Full suite (pytest tests/ -q) still passes at 536+
  </done>
</task>

</tasks>

<verification>
- `pytest tests/unit/test_run_store.py tests/unit/test_provider_retry.py -x -q` — all pass including concurrent, truncation, and makedirs tests
- `pytest tests/unit/test_user_run.py -x -q` — all 3 MockTransport tests pass
- `pytest tests/unit/test_context_eviction.py -x -q` — all 6 eviction tests pass
- `pytest tests/ -q` — full suite passes at 536+ (no regressions)
- `ruff check src/ tests/` — clean
</verification>

<success_criteria>
- Provider 500 errors (Ollama context overflow, network failures) surface as clean SSE error event + stream close via existing except block in run.py producer (no code change to run.py required — only provider.py marker extension)
- Run is marked status="failed" in RunStore when provider fails (existing except block already does this — just needed the 500 marker to classify correctly)
- test_user_run.py: 3 tests using httpx.MockTransport (no live server) — happy path, error event, reconnect
- SSE fixture sequences importable from tests/fixtures/sse_sequences/
- SQLiteRunStore: result > 512KB stored with truncated tool_history, mission_reports intact, warning logged
- SQLiteRunStore: creates parent directory on init (test_makedirs_on_init passes)
- Concurrent update_run: 5 simultaneous calls complete without OperationalError
- Context eviction: _evict_tool_result_messages trims before plan call when OLLAMA_NUM_CTX set
- Placeholder messages in LLM context when tool results evicted
- All 536 existing tests continue to pass
</success_criteria>

<output>
After completion, create `.planning/phases/06-fastapi-service-layer/features/stabilize-error-handling-context-managem/FEATURE-SUMMARY.md`
</output>
