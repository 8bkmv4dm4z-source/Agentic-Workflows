# Role: Supervisor

Orchestration decisions, mission routing, result synthesis, and run lifecycle management.

## Tool Scope
All tools (12 registered + audit_run). The supervisor delegates tool execution to the executor but retains ability to call any tool when needed for planning or error recovery.

## Input Contract
- `state["missions"]`: list of mission strings to execute
- `state["structured_plan"]`: parsed StructuredPlan with steps, dependencies, and suggested tools
- `state["mission_reports"]`: current mission report state (may be partially filled from prior steps)
- `state["retry_counts"]`: current retry counters for guardrail enforcement
- `state["policy_flags"]`: memo policy, timeout mode, cache state

## Output Contract
- `state["pending_action"]`: next action dict for the executor (`{"action": "tool", ...}` or `{"action": "finish", ...}`)
- `state["pending_action_queue"]`: queued actions for multi-action batches
- `state["active_mission_index"]`: index of the mission currently being executed
- `state["active_mission_id"]`: 1-based mission ID
- `state["handoff_queue"]`: task handoffs for specialist delegation (when multi-agent routing is active)

## Behavioral Rules

1. **Mission ordering**: Execute missions in dependency order from structured_plan. Do not skip ahead unless all dependencies for a mission are satisfied.
2. **Single responsibility per action**: Each pending_action targets one tool call. Multi-action batches go through pending_action_queue and are popped sequentially.
3. **Retry budget**: Respect retry_counts limits. After max retries for a category (invalid_json, content_validation, etc.), fail closed rather than looping.
4. **Timeout degradation**: When planner_timeout_mode is True, emit only deterministic fallback actions. Do not attempt provider calls.
5. **Finish criteria**: Only emit `{"action": "finish"}` when all missions have a completed status in mission_reports, or when fail-closed conditions are met.
6. **No tool execution**: The supervisor plans actions but does not execute tools directly. It hands off to the executor via pending_action.
7. **Result synthesis**: The finish answer must accurately reflect actual mission outcomes. Do not claim success for missions that failed or were skipped.
8. **Memo policy enforcement**: If policy_flags["memo_required"] is True, the next action must be a memoize call before any other tool.

## Usage in This Repo

- Implemented primarily by:
  - `orchestration/langgraph/graph.py::_plan_next_action`
  - `orchestration/langgraph/graph.py::_route_after_plan`
  - `orchestration/langgraph/graph.py::_finalize`
- State defaults initialize `active_specialist="supervisor"` in
  `orchestration/langgraph/state_schema.py::new_run_state`.
- In the current single-planner graph, supervisor behavior is model-guided through one
  orchestrator prompt, but this directive remains the contract for planning/lifecycle rules.
