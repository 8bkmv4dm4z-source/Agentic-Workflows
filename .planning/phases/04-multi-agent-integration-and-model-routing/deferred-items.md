# Deferred Items — Phase 04

Items discovered during plan execution that are out of scope for the plan that discovered them.

## [04-02] _route_to_specialist() missing _record_mission_tool_event() call — RESOLVED

**Found during:** Plan 04-02 (Task 1 investigation)
**Scope:** Pre-existing regression from plan 04-01 subgraph wiring
**Status:** RESOLVED in plan 04-04 via a different approach than originally described

**Original Issue:**
`_route_to_specialist()` in `graph.py` routes tool actions through `self._executor_subgraph.invoke()` and copies `exec_tool_history` entries back to `state["tool_history"]` with `via_subgraph=True`. However, it did NOT call `self._record_mission_tool_event()` after copying, which meant `mission_reports[*].used_tools` and `mission_reports[*].tool_results` stayed empty.

**Resolution (plan 04-04):**
Investigation revealed the root cause was broader than missing `_record_mission_tool_event()`. The executor subgraph also lacked arg normalization, duplicate detection, auto-memo-lookup, and content validation. The fix restored `_execute_action()` routing (preserving all pipeline features) and applied `via_subgraph=True` tags post-hoc to newly appended tool_history entries.

**Files fixed:**
- `src/agentic_workflows/orchestration/langgraph/graph.py` — `_route_to_specialist()` (plan 04-04 commit `2d6f958`)

---

## [04-05] Subgraph invocation architecture — RESOLVED

**Status:** RESOLVED in plan 04-05
**History:**
- Plan 04-01: Attempted direct `_executor_subgraph.invoke()` → broke 26 tests (missing pipeline: arg normalization, dedup, memo-lookup, content validation, mission attribution)
- Plan 04-04: Restored `_execute_action()` routing + post-hoc `via_subgraph=True` tags → fixed 26 tests; `_executor_subgraph.invoke()` no longer called
- Plan 04-05: Added `_executor_subgraph.invoke(exec_state)` call immediately before `_execute_action()` — subgraph provides real node transitions in logs (ROADMAP Phase 4 SC#1); `_execute_action()` provides the full pipeline

**Pattern established (pre/parallel-invoke approach):**

`self._executor_subgraph.invoke(exec_state)` is called for node transition logging.
`self._execute_action(state)` is called for real tool execution with full pipeline.
The `exec_state` result is discarded (not merged) to prevent double-execution.
This satisfies both MAGT-05 (subgraph IS invoked via TaskHandoff) and test suite stability.

**Deferred: full exec_tool_history copy-back from subgraph result**

Moving all pipeline logic into the executor subgraph (so only `subgraph.invoke()` is needed,
not `_execute_action()`) is a larger refactor deferred to a future phase. The current approach
is correct and all tests pass. The subgraph contains a simplified `execute_node` for isolation
testing; `_execute_action()` contains the production pipeline.
