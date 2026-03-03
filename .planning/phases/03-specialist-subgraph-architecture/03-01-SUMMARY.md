---
phase: 03-specialist-subgraph-architecture
plan: 01
subsystem: orchestration
tags: [langgraph, specialist, subgraph, TypedDict, tool-dispatch, executor]

# Dependency graph
requires:
  - phase: 02-langgraph-upgrade-and-single-agent-hardening
    provides: langgraph>=1.0, Annotated reducers, ToolNode wiring
provides:
  - ExecutorState TypedDict (11 fields, exec_-prefixed for RunState isolation)
  - build_executor_subgraph() — compiled single-node StateGraph for tool dispatch
  - Unit test suite for executor subgraph (5 tests, isolation + invocation)
affects: [03-02-specialist-evaluator, 04-subgraph-wiring-main-graph]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_ensure_executor_defaults() repair-at-entry pattern for subgraph nodes"
    - "tool_scope whitelist filtering at subgraph compile time"
    - "exec_/eval_ prefix convention for RunState key isolation"

key-files:
  created:
    - src/agentic_workflows/orchestration/langgraph/specialist_executor.py
    - tests/unit/test_specialist_executor.py
  modified:
    - src/agentic_workflows/orchestration/langgraph/directives.py

key-decisions:
  - "ExecutorState does not inherit from RunState — full isolation via prefixed field names"
  - "tool_scope filters build_tool_registry() at subgraph compile time, not at runtime"
  - "Single-node START->execute->END topology: minimal design for testable isolation before Phase 4 multi-node refinement"
  - "run_bash added to EXECUTOR_TOOLS in directives.py to match tools_registry.py (pre-existing sync bug fixed)"

patterns-established:
  - "Subgraph state: TypedDict with exec_/eval_ prefix; repair via _ensure_*_defaults() at node entry"
  - "Subgraph factory: build_*_subgraph(tool_scope, memo_store) — accepts scope at compile time"
  - "Error handling: unknown tool returns {error: tool_not_found: X} with status=error; never raises"

requirements-completed: [MAGT-01, MAGT-02]

# Metrics
duration: 2min
completed: 2026-03-03
---

# Phase 3 Plan 01: Specialist Executor Subgraph Summary

**Isolated ExecutorState TypedDict and build_executor_subgraph() factory compiling a single-node LangGraph StateGraph for scoped tool dispatch with zero RunState key overlap**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-03-03T00:36:01Z
- **Completed:** 2026-03-03T00:37:59Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Created specialist_executor.py with ExecutorState (11 fields: task_id, specialist, mission_id, tool_scope, input_context, token_budget, exec_tool_history, exec_seen_signatures, result, tokens_used, status)
- build_executor_subgraph() compiles START->execute->END StateGraph; dispatches tools from filtered registry; records exec_tool_history; returns status=success or status=error gracefully
- 5 unit tests pass: field set assertion, RunState disjoint check, sort_array invocation, tool_history recording, unknown tool error path
- Auto-fixed pre-existing run_bash omission from EXECUTOR_TOOLS (directives.py was out of sync with tools_registry.py)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create specialist_executor.py** - `e2c69fa` (feat)
2. **Task 2: Tests + directives.py auto-fix** - `e8a5eb0` (test)

## Files Created/Modified
- `src/agentic_workflows/orchestration/langgraph/specialist_executor.py` — ExecutorState TypedDict + build_executor_subgraph() factory
- `tests/unit/test_specialist_executor.py` — 5 unit tests for executor subgraph isolation and invocation
- `src/agentic_workflows/orchestration/langgraph/directives.py` — Added run_bash to EXECUTOR_TOOLS (auto-fix)

## Decisions Made
- ExecutorState uses standalone TypedDict with no RunState inheritance; exec_-prefixed list fields guarantee zero key overlap
- tool_scope filtering happens at compile time inside build_executor_subgraph() so the subgraph has a closed-over registry
- _ensure_executor_defaults() follows the ensure_state_defaults() pattern from state_schema.py

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] run_bash missing from EXECUTOR_TOOLS in directives.py**
- **Found during:** Task 2 (running full test suite for regression check)
- **Issue:** tools_registry.py added run_bash in the Phase 2 additions block but directives.py EXECUTOR_TOOLS was not updated; test_directives.py::test_executor_scope_matches_tool_registry failed with "Items in first set but not second: 'run_bash'"
- **Fix:** Added "run_bash" to the EXECUTOR_TOOLS frozenset in directives.py
- **Files modified:** src/agentic_workflows/orchestration/langgraph/directives.py
- **Verification:** pytest tests/unit/ -q — 307 passed (0 failed)
- **Committed in:** e8a5eb0 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — pre-existing bug)
**Impact on plan:** Auto-fix necessary for test suite consistency. No scope creep.

## Issues Encountered
None — plan executed as specified after the pre-existing directives sync bug was fixed.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- ExecutorState and build_executor_subgraph() are ready for Phase 4 wiring into _route_to_specialist
- EvaluatorState / build_evaluator_subgraph() to be created in 03-02
- 307 tests passing; no regressions

---
*Phase: 03-specialist-subgraph-architecture*
*Completed: 2026-03-03*
