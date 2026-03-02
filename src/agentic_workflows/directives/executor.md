# Role: Executor

Deterministic tool execution, argument normalization, file I/O, and result recording.

## Tool Scope
12 registered tools: `repeat_message`, `sort_array`, `string_ops`, `math_stats`, `write_file`, `memoize`, `retrieve_memo`, `task_list_parser`, `text_analysis`, `data_analysis`, `json_parser`, `regex_matcher`.

## Input Contract
- `state["pending_action"]`: action dict with `{"action": "tool", "tool_name": "...", "args": {...}}`
- `state["tool_history"]`: prior tool call records for deduplication and chain integrity
- `state["seen_tool_signatures"]`: set of signature hashes for duplicate detection
- `state["active_mission_index"]`: which mission this action belongs to
- `state["policy_flags"]`: memo policy state

## Output Contract
- `state["tool_history"]`: appended with new ToolRecord (`call`, `tool`, `args`, `result`)
- `state["mission_reports"][active_mission_index]`: updated with used_tools and tool_results
- `state["seen_tool_signatures"]`: updated with new call signature
- `state["tool_call_counts"]`: incremented for the executed tool
- `state["pending_action"]`: set to None after execution

## Behavioral Rules

1. **Argument normalization**: Apply canonical arg aliases before execution (e.g., `array`→`items`, `file_path`→`path`, `text`→`content`). Never pass raw planner args to tools.
2. **Duplicate detection**: Hash the (tool_name, normalized_args) tuple. If the signature exists in seen_tool_signatures, reject the call and return a duplicate error.
3. **Content validation**: For write_file calls, validate content format against the active mission contract (e.g., fibonacci CSV must be comma-separated integers). Reject invalid content with a structured error.
4. **No planning**: The executor does not decide which tool to call next. It executes exactly what pending_action specifies.
5. **Result recording**: Every execution (success or error) must be recorded in tool_history and the active mission report.
6. **Error propagation**: Tool errors are returned as structured dicts (`{"error": "...", "details": "..."}`), not exceptions. The supervisor handles retry decisions.
7. **Memo policy compliance**: If a memoize action is pending, execute it before any other queued action.
8. **Idempotency awareness**: write_file and memoize are not idempotent — duplicate calls with different content must be detected and flagged.

## Usage in This Repo

- Implemented primarily by:
  - `orchestration/langgraph/graph.py::_execute_action`
  - `orchestration/langgraph/graph.py::_normalize_tool_args`
  - `orchestration/langgraph/graph.py::_record_mission_tool_event`
- Tool registration is centralized in
  `orchestration/langgraph/tools_registry.py::build_tool_registry`.
- In the current graph, `_route_to_specialist` is a pass-through that sets
  `active_specialist="executor"` and delegates to `_execute_action`.
