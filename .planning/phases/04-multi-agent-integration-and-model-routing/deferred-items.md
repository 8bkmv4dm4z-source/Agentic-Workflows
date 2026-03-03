# Deferred Items — Phase 04

Items discovered during plan execution that are out of scope for the plan that discovered them.

## [04-02] _route_to_specialist() missing _record_mission_tool_event() call

**Found during:** Plan 04-02 (Task 1 investigation)
**Scope:** Pre-existing regression from plan 04-01 subgraph wiring

**Issue:**
`_route_to_specialist()` in `graph.py` routes tool actions through `self._executor_subgraph.invoke()` and copies `exec_tool_history` entries back to `state["tool_history"]` with `via_subgraph=True`. However, it does NOT call `self._record_mission_tool_event()` after copying, which means `mission_reports[*].used_tools` and `mission_reports[*].tool_results` stay empty.

**Impact:**
- 26 existing integration tests in `test_langgraph_flow.py` fail with `required_tools_missing` audit FAIL findings
- MissionAuditor's `required_tools_missing` check (FAIL level) triggers when `mission_contracts` have required tools set but `mission_reports.used_tools` is empty
- `test_langgraph_flow.py::LangGraphFlowTests` tests that expect `audit_report["failed"] == 0` on runs with required tools all fail

**Fix required:**
In `_route_to_specialist()`, after the loop that appends tagged entries to `tool_history`, add:
```python
for entry in result_state.get("exec_tool_history", []):
    self._record_mission_tool_event(
        state,
        entry.get("tool", ""),
        entry.get("result", {}),
        mission_index=max(0, mission_id - 1) if mission_id > 0 else None,
        tool_args=entry.get("args", {}),
    )
```
Also update `tool_call_counts` to match `_execute_action()` behavior.

**Files to fix:**
- `src/agentic_workflows/orchestration/langgraph/graph.py` — `_route_to_specialist()` method (lines ~1194-1254)
