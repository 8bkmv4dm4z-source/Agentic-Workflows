---
phase: 02-langgraph-upgrade-and-single-agent-hardening
plan: "02"
subsystem: state_schema
tags: [reducers, annotated, compaction, langgraph, state]
dependency_graph:
  requires: [02-01]
  provides: [LGUP-03, LGUP-04]
  affects: [state_schema.py, graph.py, test_state_schema.py, test_langgraph_flow.py]
tech_stack:
  added: [operator.add, typing.Annotated, os.getenv compaction]
  patterns: [Annotated reducer, sequential_node wrapper, sliding-window compaction]
key_files:
  created:
    - tests/unit/test_state_schema.py
  modified:
    - src/agentic_workflows/orchestration/langgraph/state_schema.py
    - src/agentic_workflows/orchestration/langgraph/graph.py
    - tests/integration/test_langgraph_flow.py
decisions:
  - "operator.add reducer requires sequential nodes to return empty-list delta for Annotated fields — implemented via _sequential_node() wrapper in graph.py"
  - "type: ignore[misc] added on all four Annotated lines because operator.add is Callable not a type annotation"
  - "ensure_state_defaults() augmented with compaction at end; no existing logic removed"
metrics:
  duration: "7 min"
  completed_date: "2026-03-03"
  tasks_completed: 2
  files_changed: 4
---

# Phase 2 Plan 02: RunState Reducers and Message Compaction Summary

Annotated[list[T], operator.add] reducers on four RunState list fields plus sliding-window message compaction in ensure_state_defaults() — with _sequential_node() wrapper fixing LangGraph 1.0 reducer doubling in sequential operation.

## What Was Done

### Task 1: Add Annotated reducers to four RunState list fields

**state_schema.py changes:**

Added `import operator` and `import os` to standard library imports. Added `Annotated` to the typing import. Changed four plain list fields to use `Annotated[list[T], operator.add]`:

```python
tool_history: Annotated[list[ToolRecord], operator.add]  # type: ignore[misc]
memo_events: Annotated[list[MemoEvent], operator.add]  # type: ignore[misc]
seen_tool_signatures: Annotated[list[str], operator.add]  # type: ignore[misc]
mission_reports: Annotated[list[MissionReport], operator.add]  # type: ignore[misc]
```

**graph.py changes — node return value audit and fix:**

The plan stated that "in-place mutations are safe and do not go through the reducer." This assumption was empirically verified to be incorrect with LangGraph 1.0: when a node returns the full RunState dict, the reducer applies `operator.add(old_list, returned_list)`, doubling every Annotated list on each graph step. Tests confirmed this caused `mission_count: 6144` and `tools_used_count: 1168` in a simple single-tool run (both multiplied by 2^n for each graph cycle).

**Fix:** Added `_sequential_node()` wrapper and `_ANNOTATED_LIST_FIELDS` constant to `graph.py`:

```python
_ANNOTATED_LIST_FIELDS: frozenset[str] = frozenset(
    {"tool_history", "memo_events", "seen_tool_signatures", "mission_reports"}
)

def _sequential_node(fn):
    """Wrap a sequential LangGraph node so Annotated list fields return [] (empty delta)."""
    def wrapper(state: RunState) -> RunState:
        result = fn(state)
        if isinstance(result, dict):
            for field in _ANNOTATED_LIST_FIELDS:
                if field in result:
                    result[field] = []
        return result
    wrapper.__name__ = getattr(fn, "__name__", repr(fn))
    wrapper.__qualname__ = getattr(fn, "__qualname__", repr(fn))
    return wrapper
```

LangGraph 1.0 uses the post-mutation state as the "old" value for the reducer. When a node does in-place mutation (`state["tool_history"].append(record)`) and then returns `{"tool_history": []}` (empty delta), `operator.add(post_mutation_list, [])` = `post_mutation_list`. The in-place mutations are preserved correctly.

All four nodes in `_compile_graph()` are wrapped:
```python
builder.add_node("plan", _sequential_node(self._plan_next_action))
builder.add_node("execute", _sequential_node(self._route_to_specialist))
builder.add_node("policy", _sequential_node(self._enforce_memo_policy))
builder.add_node("finalize", _sequential_node(self._finalize))
```

**Phase 4 note:** When parallel Send() branches are implemented, those branches will return only the delta items (new records only) for the Annotated fields — not the full list. The `_sequential_node()` wrapper is NOT applied to Send() sub-nodes. This correctly implements `operator.add` semantics: `current_list + branch_delta = merged_list`.

### Task 2: Message compaction in ensure_state_defaults()

Added at the end of `ensure_state_defaults()` (just before `return cast(RunState, state_dict)`):

```python
# Message compaction — sliding window, drop oldest non-system messages
_threshold = int(os.getenv("P1_MESSAGE_COMPACTION_THRESHOLD", "40"))
_messages = state_dict.get("messages", [])
if len(_messages) > _threshold:
    _system_msgs = [m for m in _messages if m.get("role") == "system"]
    _non_system = [m for m in _messages if m.get("role") != "system"]
    _keep_count = max(0, _threshold - len(_system_msgs))
    state_dict["messages"] = _system_msgs + _non_system[-_keep_count:]
```

Default threshold: 40 messages. Configurable via `P1_MESSAGE_COMPACTION_THRESHOLD` env var. System messages are always preserved. Most recent non-system messages are retained (sliding window keeps tail).

## Node Return Value Audit

Nodes checked for safe return patterns:
- `_plan_next_action` — returns `state` directly at all exit points (20+ return statements). All in-place mutations; no partial dict returns for Annotated fields.
- `_route_to_specialist` — same pattern.
- `_enforce_memo_policy` — same pattern.
- `_finalize` — same pattern.

One occurrence of `"memo_events": final_state.get("memo_events", [])` at line ~227 is in `run()` (the result extraction method), NOT a graph node return. Safe.

All nodes wrapped by `_sequential_node()` — Annotated list fields zeroed in returned dict.

## Test Counts

| State | Count |
|-------|-------|
| Before plan | 267 |
| After plan | 277 |
| New tests | 10 |

New tests:
- `test_tool_history_has_annotated_reducer` (unit)
- `test_memo_events_has_annotated_reducer` (unit)
- `test_seen_tool_signatures_has_annotated_reducer` (unit)
- `test_mission_reports_has_annotated_reducer` (unit)
- `test_compaction_fires_above_threshold` (unit)
- `test_compaction_preserves_system_message` (unit)
- `test_compaction_keeps_most_recent` (unit)
- `test_compaction_does_not_fire_at_threshold` (unit)
- `test_compaction_threshold_env_var` (unit)
- `test_reducer_two_branch_merge` (integration)

## mypy type: ignore Notes

Added `# type: ignore[misc]` on all four Annotated lines. Reason: `operator.add` is a `Callable[[Any, Any], Any]`, not a PEP 593 type metadata value. mypy's `Annotated` strict checking rejects non-type second arguments. LangGraph reads the `__metadata__` tuple at runtime, not via mypy. The `type: ignore[misc]` is scoped to each line, not the whole file.

Reference for Phase 4 ADR: document the `_sequential_node()` pattern as the standard wrapper for all sequential graph nodes; document that Send() parallel sub-nodes must NOT use this wrapper and must return only delta lists.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed Annotated reducer list doubling in sequential operation**

- **Found during:** Task 1 GREEN phase — pytest run after adding reducers
- **Issue:** Plan's assumption "in-place mutations do not go through the reducer and are safe" was incorrect. LangGraph 1.0 applies `operator.add(post_mutation_list, returned_list)` when a node returns the full state dict. This doubled every Annotated list on every graph step (16 tests failed; `mission_count` grew to 6144, `tools_used_count` to 1168 in a simple single-tool run).
- **Fix:** Added `_sequential_node()` wrapper function and `_ANNOTATED_LIST_FIELDS` constant in `graph.py`. Wrapper zeros out the Annotated fields in node return dicts. Applied to all four graph nodes in `_compile_graph()`.
- **Files modified:** `src/agentic_workflows/orchestration/langgraph/graph.py`
- **Commit:** f9ed1e4

## Self-Check: PASSED
