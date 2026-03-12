---
phase: 06-fastapi-service-layer
plan: 03
subsystem: api
tags: [fastapi, httpx, rich, sse, eval, cli, scripted-provider]

requires:
  - phase: 06-fastapi-service-layer
    provides: POST /run SSE streaming, GET /run/{id}, RunStore, FastAPI app skeleton
provides:
  - CLI user_run.py as API client with Rich SSE rendering and auto-start
  - Eval harness with 3 deterministic ScriptedProvider scenarios through API
  - Fixed streaming state accumulation bug (annotated list fields)
affects: [07-postgres, deployment]

tech-stack:
  added: []
  patterns: [checkpoint_store.load_latest() for final state retrieval, ASGITransport eval fixtures]

key-files:
  created:
    - src/agentic_workflows/cli/__init__.py
    - src/agentic_workflows/cli/user_run.py
    - tests/eval/__init__.py
    - tests/eval/conftest.py
    - tests/eval/test_eval_harness.py
  modified:
    - src/agentic_workflows/orchestration/langgraph/user_run.py
    - src/agentic_workflows/api/routes/run.py

key-decisions:
  - "CLI user_run.py talks to FastAPI via httpx, not orchestrator directly -- single source of truth"
  - "Retrieve final state from checkpoint_store.load_latest() instead of accumulating stream chunks -- avoids _sequential_node annotated list zeroing"
  - "Old user_run.py kept with deprecation warning for backward compatibility"

patterns-established:
  - "Eval fixture pattern: _build_eval_app() with ScriptedProvider per scenario"
  - "SSE rendering via Rich console.print with node-type dispatch"

requirements-completed: [PROD-01, PROD-02]

duration: 8min
completed: 2026-03-05
---

# Phase 06 Plan 03: API Client + Eval Harness Summary

**CLI user_run as httpx API client with Rich SSE rendering, 3-scenario eval harness, and streaming state accumulation fix**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-04T23:36:42Z
- **Completed:** 2026-03-04T23:45:00Z
- **Tasks:** 2 of 3 (Task 3 is human-verify checkpoint)
- **Files modified:** 7

## Accomplishments
- New cli/user_run.py connects to FastAPI service via httpx, renders SSE events with Rich terminal formatting
- Auto-start spawns uvicorn in background if API server is not running
- 3 eval scenarios (simple mission, multi-mission, tool chain) pass through API using ScriptedProvider
- Fixed critical streaming state accumulation bug: annotated list fields (tool_history, mission_reports) were being zeroed by _sequential_node wrapper in stream updates
- Old user_run.py preserved with deprecation warning for backward compatibility
- 536 total tests passing (3 new eval tests)

## Task Commits

Each task was committed atomically:

1. **Task 1: Convert user_run.py to API client** - `33eb546` (feat)
2. **Task 2: Eval harness + streaming bug fix** - `ed704ba` (test)

## Files Created/Modified
- `src/agentic_workflows/cli/__init__.py` - Empty init for cli package
- `src/agentic_workflows/cli/user_run.py` - API client with Rich SSE rendering, auto-start, interactive session (160 lines)
- `src/agentic_workflows/orchestration/langgraph/user_run.py` - Added deprecation warning
- `src/agentic_workflows/api/routes/run.py` - Fixed streaming state accumulation via checkpoint_store.load_latest()
- `tests/eval/__init__.py` - Empty init for eval package
- `tests/eval/conftest.py` - Eval fixtures with 3 ScriptedProvider response sequences (97 lines)
- `tests/eval/test_eval_harness.py` - 3 eval scenarios through API (135 lines)

## Decisions Made
- CLI user_run.py talks to FastAPI via httpx (not orchestrator directly) -- enforces single source of truth constraint
- Retrieve final state from `checkpoint_store.load_latest()` instead of accumulating from stream chunks -- `_sequential_node` zeroes annotated list fields (tool_history, mission_reports) in stream updates, making chunk-based accumulation unreliable
- Old `user_run.py` kept with deprecation warning rather than deleted -- backward compatibility

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed streaming state accumulation in POST /run route**
- **Found during:** Task 2 (eval harness tests)
- **Issue:** `_sequential_node` wrapper zeroes annotated list fields (tool_history, mission_reports, memo_events, seen_tool_signatures) in stream update dicts to prevent operator.add doubling. `stream_mode="updates"` yielded these zeroed values, and `last_state.update(chunk)` overwrote the correct in-place-mutated lists with empty ones. Additionally, `_finalize()` was being called twice (once as graph node, once explicitly), causing double audit reports.
- **Fix:** Removed chunk-based state accumulation and redundant `_finalize()` call. Now retrieves complete final state from `checkpoint_store.load_latest(run_id)` which has the correct state saved by the finalize graph node.
- **Files modified:** src/agentic_workflows/api/routes/run.py
- **Verification:** All 3 eval tests pass with correct tool_history and mission_reports. 8 existing API integration tests still pass.
- **Committed in:** ed704ba (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Bug fix was necessary for eval tests to validate tool ordering and mission reports. No scope creep.

## Issues Encountered
None beyond the auto-fixed deviation above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 6 complete: all endpoints functional, CLI connected, eval harness passing
- Awaiting human verification (Task 3 checkpoint) for end-to-end confirmation
- Ready for Phase 7 (Postgres migration, containerization)

---
*Phase: 06-fastapi-service-layer*
*Completed: 2026-03-05*
