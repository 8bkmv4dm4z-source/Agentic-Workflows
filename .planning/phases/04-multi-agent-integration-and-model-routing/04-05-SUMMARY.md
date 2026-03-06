---
phase: 04-multi-agent-integration-and-model-routing
plan: 05
subsystem: orchestration
tags: [langgraph, subgraph, specialist, routing, executor-subgraph, parallel-invoke, via_subgraph]

# Dependency graph
requires:
  - phase: 04-04
    provides: "_route_to_specialist() with _execute_action() routing + via_subgraph post-tagging; all 26 integration regressions fixed"
  - phase: 04-01
    provides: "Compiled executor/evaluator subgraphs cached in __init__() as self._executor_subgraph and self._evaluator_subgraph"
provides:
  - "_route_to_specialist() executor/evaluator branch calls self._executor_subgraph.invoke(exec_state) before _execute_action()"
  - "Real subgraph node transitions appear in LangGraph logs — satisfies ROADMAP Phase 4 Success Criterion 1"
  - "MAGT-05 structural requirement satisfied: executor subgraph IS invoked via TaskHandoff input_context"
  - "deferred-items.md documents the complete pre/parallel-invoke architecture and tradeoff history"
  - "Pre-existing [04-02] deferred item marked RESOLVED"
affects: [phase-05, mission-auditor]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pre/parallel-invoke pattern: call self._executor_subgraph.invoke(exec_state) for node transition logging, then call self._execute_action(state) for production pipeline; subgraph result discarded to prevent double-execution"

key-files:
  created:
    - ".planning/phases/04-multi-agent-integration-and-model-routing/04-05-SUMMARY.md"
  modified:
    - "src/agentic_workflows/orchestration/langgraph/graph.py — _route_to_specialist() executor/evaluator branch: added self._executor_subgraph.invoke(exec_state) before _execute_action() call"
    - ".planning/phases/04-multi-agent-integration-and-model-routing/deferred-items.md — marked [04-02] as RESOLVED, added [04-05] section documenting the pre/parallel-invoke architecture"

key-decisions:
  - "Use parallel-invoke pattern (subgraph.invoke() + _execute_action()) rather than replacing _execute_action() with subgraph.invoke(): the executor subgraph provides node transition logs; _execute_action() provides the full production pipeline; result discarded to prevent double-execution"
  - "exec_state result intentionally discarded — RunState.tool_history is still populated by _execute_action(), not by copying from ExecutorState.exec_tool_history"
  - "Full migration of production pipeline into executor subgraph deferred to a future phase — current approach is correct and all tests pass"

patterns-established:
  - "Pre/parallel-invoke: build exec_state from TaskHandoff input_context, call self._executor_subgraph.invoke(exec_state), then call self._execute_action(state) for real tool execution; tag new tool_history entries with via_subgraph=True post-hoc"

requirements-completed: [MAGT-05, MAGT-06]

# Metrics
duration: 2min
completed: 2026-03-03
---

# Phase 4 Plan 05: Subgraph Invocation Wiring Summary

**Wired self._executor_subgraph.invoke(exec_state) into _route_to_specialist() via parallel-invoke pattern — subgraph provides real LangGraph node transitions while _execute_action() preserves full production pipeline**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-03-03T11:45:12Z
- **Completed:** 2026-03-03T11:47:30Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Wired `self._executor_subgraph.invoke(exec_state)` into `_route_to_specialist()` executor/evaluator branch, satisfying MAGT-05 structural requirement and ROADMAP Phase 4 Success Criterion 1
- Constructed `ExecutorState` dict from `TaskHandoff` `input_context` before invoking subgraph — the subgraph result is intentionally discarded to prevent double-execution
- All 40 previously-passing integration tests continue to pass; ruff check is clean
- Updated `deferred-items.md` to mark the [04-02] stale item as RESOLVED and document the complete pre/parallel-invoke architectural tradeoff across plans 04-01 through 04-05

## Task Commits

1. **Task 1: Wire self._executor_subgraph.invoke() into _route_to_specialist()** - `95ff71f` (feat)
2. **Task 2: Update deferred-items.md with subgraph invocation architecture** - `fe006b5` (docs)

## Files Created/Modified

- `/home/nir/dev/agent_phase0/src/agentic_workflows/orchestration/langgraph/graph.py` — Added `exec_state` construction and `self._executor_subgraph.invoke(exec_state)` call immediately before `self._execute_action(state)` in `_route_to_specialist()` executor/evaluator branch (lines ~1201-1219)
- `/home/nir/dev/agent_phase0/.planning/phases/04-multi-agent-integration-and-model-routing/deferred-items.md` — Marked [04-02] section as RESOLVED; added [04-05] section documenting the pre/parallel-invoke pattern and deferred full pipeline migration

## Decisions Made

- **Use parallel-invoke pattern (subgraph.invoke() then _execute_action())**: The plan's CONTEXT.md override specifies that subgraph.invoke() is called for node transition logging and _execute_action() for the production pipeline. These are complementary — the subgraph result is discarded to prevent double-execution of tools. This satisfies both the structural requirement (subgraph IS invoked) and test suite stability.

- **exec_state result intentionally discarded**: `RunState.tool_history` is populated by `_execute_action()`, not by copying from `ExecutorState.exec_tool_history`. This preserves arg normalization, duplicate detection, auto-memo-lookup, content validation, and mission attribution which are all present in `_execute_action()` but absent from the simplified subgraph `execute_node`.

## Deviations from Plan

None — plan executed exactly as written. The plan explicitly described the parallel-invoke pattern (task action section lines 180-222) and the implementation matched precisely.

## Issues Encountered

None — the edit applied cleanly, ruff check passed, and all 40 integration tests passed on the first run.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Phase 4 plan 05 complete: `self._executor_subgraph.invoke()` is now called in `_route_to_specialist()` for every executor-branch tool action
- ROADMAP Phase 4 Success Criterion 1 ("logs show real subgraph node transitions") is satisfied
- MAGT-05 and MAGT-06 requirements satisfied across plans 04-04 and 04-05
- Phase 5 (Production Readiness / FastAPI layer) can proceed with confidence that the subgraph wiring is complete

---
*Phase: 04-multi-agent-integration-and-model-routing*
*Completed: 2026-03-03*
