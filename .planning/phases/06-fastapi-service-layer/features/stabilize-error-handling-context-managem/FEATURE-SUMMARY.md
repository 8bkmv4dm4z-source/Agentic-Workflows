---
phase: 06-fastapi-service-layer
feature: stabilize-error-handling-context-managem
subsystem: orchestration/service-layer
tags: [error-handling, sse, sqlite, context-eviction, provider-retry, mock-transport]
dependency_graph:
  requires: [06-03-PLAN]
  provides: [provider-500-hardening, sqlite-concurrency, context-eviction, sse-test-fixtures]
  affects: [provider.py, graph.py, sqlite.py, user_run.py]
tech_stack:
  added: [httpx.MockTransport, threading.Lock, structlog-warning]
  patterns: [TDD-red-green, concurrent-sqlite-locking, token-budget-eviction]
key_files:
  created:
    - tests/unit/test_provider_retry.py
    - tests/unit/test_user_run.py
    - tests/unit/test_context_eviction.py
    - tests/fixtures/__init__.py
    - tests/fixtures/sse_sequences/__init__.py
    - tests/fixtures/sse_sequences/happy_path.py
    - tests/fixtures/sse_sequences/error_event.py
    - tests/fixtures/sse_sequences/reconnect.py
  modified:
    - src/agentic_workflows/orchestration/langgraph/provider.py
    - src/agentic_workflows/orchestration/langgraph/graph.py
    - src/agentic_workflows/storage/sqlite.py
    - tests/unit/test_run_store.py
decisions:
  - "Added threading.Lock to SQLiteRunStore to fix concurrent update_run InterfaceError (anyio dispatches each call to separate thread pool threads)"
  - "Used httpx.MockTransport with patch('agentic_workflows.cli.user_run.httpx.AsyncClient') for SSE tests — cleanest approach without modifying stream_run signature"
  - "Token eviction uses len(content)//4 heuristic (same as existing token_budget_used tracking in graph.py) — no tiktoken dependency"
  - "_evict_tool_result_messages placed as new method called at top of _compact_messages for clear separation from count-based compaction"
  - "SQLiteRunStore.initialize() added as no-op async method for protocol compatibility — actual init happens synchronously in __init__"
metrics:
  duration: "~15 minutes"
  completed: "2026-03-06"
  tasks_completed: 3
  files_created: 9
  files_modified: 4
  tests_added: 29
---

# Phase 6 Stabilize Feature Summary: Error Handling + Context Management

**One-liner:** Provider HTTP 500 retry classification, SQLite thread-safe concurrent writes, token-budget context eviction with placeholder messages, and MockTransport SSE tests.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Provider 500 error surfacing + RunStore edge case hardening | 0f8d98f | provider.py, sqlite.py, test_run_store.py, test_provider_retry.py |
| 2 | SSE fixture sequences + user_run.py MockTransport tests | 1b82e7c | tests/fixtures/sse_sequences/, test_user_run.py |
| 3 | Token-budget context eviction in graph.py _compact_messages | e2a7e14 | graph.py, test_context_eviction.py |
| - | Ruff cleanup (unused imports in test files) | 40ca0b6 | test_context_eviction.py, test_run_store.py |

## What Was Built

### Task 1: Provider 500 Error Surfacing + RunStore Hardening

**provider.py** — Extended `_is_retryable_timeout_error` with 6 new markers:
- `"http 500"`, `"status code 500"`: Ollama context overflow responses surface as retryable errors
- `"context length exceeded"`, `"context window"`: explicit context limit messages
- `"request entity too large"`, `"payload too large"`: HTTP-level payload rejections

These markers ensure Ollama HTTP 500 (context overflow) propagates as `ProviderTimeoutError` after all retries, which the existing SSE producer except block already handles via `update_run(status="failed")` + `make_error()`.

**sqlite.py** — Three hardening changes:
1. `MAX_RESULT_JSON_BYTES` cap (512KB env-configurable): Before inserting, if serialized result exceeds limit, `tools_used` entries are replaced with `{tool, args_summary, result_truncated: True}` — `mission_report` is preserved intact.
2. `structlog` warning logged with `run_id`, `original_bytes`, `limit_bytes` when truncation occurs.
3. `threading.Lock` added to all `_conn.execute` calls — fixes `InterfaceError` on concurrent `anyio.to_thread.run_sync` dispatches to different worker threads.
4. Async `initialize()` no-op method added for protocol compatibility.

**Tests added (20):** 9 in `test_provider_retry.py`, 7 new tests in `test_run_store.py` (truncation, warning, concurrent, makedirs).

### Task 2: SSE Fixture Sequences + MockTransport Tests

**tests/fixtures/sse_sequences/** — Three fixture modules:
- `happy_path.py`: 7-event sequence (plan node_start/end x2, tool node_start/end, run_complete with answer)
- `error_event.py`: 2-event sequence (node_start then provider error SSE event)
- `reconnect.py`: 2-event partial sequence (node_end + run_complete, no initial node_start)

**test_user_run.py** — 3 tests using `httpx.MockTransport`:
- `test_happy_path_render`: patches `httpx.AsyncClient` constructor, verifies `run_id` returned and node names rendered via Rich console capture
- `test_error_event_exit`: verifies "ERROR" in console output and empty answer string on error SSE event
- `test_reconnect_stream_renders`: verifies partial event sequence renders without crash and returns correct `run_id`

### Task 3: Token-Budget Context Eviction

**graph.py** — New `_evict_tool_result_messages(state)` method on `LangGraphOrchestrator`:

Trigger conditions:
- `OLLAMA_NUM_CTX` env var must be set (> 0); otherwise no-op
- Estimated tokens (`sum(len(content)//4 for msg)`) must exceed `CTX_EVICTION_RATIO * OLLAMA_NUM_CTX` (default ratio 0.75)

Eviction strategy:
- Identifies `role=user` messages whose content starts with `"TOOL RESULT"` (tool dispatch pattern)
- Skips `messages[0]` (system prompt always preserved)
- Evicts oldest candidates first until estimated tokens drop below threshold
- Replaces each evicted message with: `"[tool_result: {tool_name}, {N} bytes, stored in run_store]"`
- Logs `CONTEXT EVICT` info line per eviction

Integration: Called at top of `_compact_messages`, before count-based compaction. Zero impact when `OLLAMA_NUM_CTX=0`.

**Tests added (6):** All 6 specified scenarios covered (no-trigger without env var, no-trigger under threshold, eviction of large result, system prompt preservation, placeholder format, stops when under threshold).

## Acceptance Criteria Status

- [x] Provider 500 errors (Ollama context overflow, network failures) result in clean SSE error event + stream close
- [x] Run marked `status="failed"` in RunStore when provider fails (existing except block, now correctly triggered)
- [x] `test_user_run.py`: 3 tests using httpx MockTransport (happy path, error event, reconnect)
- [x] SSE fixture sequences in `tests/fixtures/sse_sequences/`
- [x] `SQLiteRunStore` creates directory on first init (pre-existing, confirmed by test)
- [x] RunResult > 512KB stored with truncated tool_history; warning logged; mission_reports intact
- [x] Concurrency test: 5 simultaneous `update_run` calls complete without `OperationalError`
- [x] Context eviction active: message history trimmed before plan call when estimated tokens exceed ratio
- [x] Placeholder message replaces dropped tool results in LLM context
- [x] 577 tests pass (up from 536; 4 pre-existing failures in unrelated test_run_bash.py + test_write_file.py)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed concurrent SQLite OperationalError with threading.Lock**
- **Found during:** Task 1 (test_concurrent_update_run)
- **Issue:** `anyio.to_thread.run_sync` dispatches each call to a thread pool worker. With 5 concurrent calls, multiple threads called `_conn.execute()` simultaneously, causing `InterfaceError: bad parameter or other API misuse`.
- **Fix:** Added `self._lock = threading.Lock()` in `__init__`, wrapped all `_conn.execute` + `_conn.commit` blocks in `with self._lock:`.
- **Files modified:** `src/agentic_workflows/storage/sqlite.py`
- **Commit:** e2a7e14 (included in Task 3 commit since the lock fix was finalized then)

**2. [Rule 2 - Missing] Added async initialize() method**
- **Found during:** Task 1 test design
- **Issue:** The plan's `test_makedirs_on_init` called `await store.initialize()` but SQLiteRunStore had no such method.
- **Fix:** Added no-op async `initialize()` for protocol compatibility (actual init is synchronous in `__init__`).
- **Files modified:** `src/agentic_workflows/storage/sqlite.py`
- **Commit:** 0f8d98f

## Self-Check: PASSED

All artifact files exist, key content present in each file, all 4 commits verified in git log.
