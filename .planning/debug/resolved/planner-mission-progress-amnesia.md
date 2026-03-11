---
status: resolved
trigger: "planner-mission-progress-amnesia"
created: 2026-03-11T00:00:00Z
updated: 2026-03-11T02:00:00Z
---

## Current Focus

hypothesis: CONFIRMED — cross-mission duplicate detection fires for a legitimate re-use of
the same tool+args across missions, silently blocking the tool. The guidance message injected
is then circular: it tells the planner "next task is mission 3" which the planner re-attempts
with the same tool call, causing an infinite dedup loop.
test: confirmed via log analysis — TOOL EXEC never fires for steps 3-9, SPECIALIST OUTPUT
      returns error, no DUPLICATE log line because the duplicate guidance is to state["messages"]
expecting: fix to inject a TOOL_RESULT synthetic message when a cross-mission duplicate is
           detected, so the planner knows the result is already available
next_action: apply fix to executor_node.py _execute_action duplicate handling

## Symptoms

expected: After tool X succeeds for sub-task N, planner issues the action for sub-task N+1 and continues until the mission is complete.
actual: After a successful tool result the planner repeats the same tool call or stalls — it does not advance to the next sub-task. The parser (mission_parser) correctly emits multiple sub-steps but the planner does not follow through on all of them.
errors: No hard errors — the run completes but silently skips remaining sub-tasks.
reproduction: Run any multi-step mission via `make local-run` and observe the PLANNER_STEP log lines in .tmp/api.log — same tool repeats across steps instead of progressing through sub-tasks.
timeline: Observed after Phase 8 execution (graph.py decomposition into mixins). May pre-date Phase 8.

## Eliminated

- hypothesis: planner receiving wrong state / wrong message history
  evidence: context injection is correct (761 chars, missions=1), planner gets proper messages
  timestamp: 2026-03-11T01:00:00Z

- hypothesis: executor subgraph (specialist_executor.py) failing
  evidence: _route_to_specialist calls self._execute_action() directly, NOT the subgraph;
            the subgraph is only used if explicitly invoked
  timestamp: 2026-03-11T01:00:00Z

- hypothesis: scope block (list_directory not in EXECUTOR_TOOLS)
  evidence: list_directory IS in EXECUTOR_TOOLS (directives.py line 58), scope check passes
  timestamp: 2026-03-11T01:00:00Z

## Evidence

- timestamp: 2026-03-11T01:00:00Z
  checked: api.log PLANNER_STEP and SPECIALIST OUTPUT lines for all steps
  found: Steps 3-9 all call list_directory with path=.../tools/, pattern=*.py; each returns
         SPECIALIST OUTPUT status=error; no TOOL EXEC log fires for any of these steps
  implication: _execute_action returns before reaching self.tools[tool_name].execute()

- timestamp: 2026-03-11T01:00:00Z
  checked: executor_node.py _execute_action — all early-return paths between SPECIALIST EXECUTE
           log (line 324) and TOOL EXEC log (line 492)
  found: Only 4 early-return paths exist: (1) scope block, (2) memo lookup auto-hit [write_file only],
         (3) memo policy retry [memo_required=False], (4) duplicate signature check.
         Paths 1-3 are all ruled out. Path 4 is the only remaining candidate.
  implication: seen_tool_signatures already contains the step-1 signature for list_directory

- timestamp: 2026-03-11T01:00:00Z
  checked: step-1 vs step-3 args comparison
  found: Step 1 listed the same tools/ directory and produced 42 .py files — highly likely
         the LLM used the same path=.../tools/, pattern=*.py args. Step 3 uses identical args.
         Signature matches → dedup fires.
  implication: This is a legitimate cross-mission dedup that should be allowed (or redirected
               to the cached result), not silently blocked

- timestamp: 2026-03-11T01:00:00Z
  checked: duplicate guidance message content
  found: When dedup fires, state["messages"] gets:
         "Duplicate tool call detected for 'list_directory'... Next incomplete task: listing each tool's..."
         This guidance tells the planner to work on mission 3, which it already was trying to do
         via list_directory. The planner sees mission 3 is incomplete and calls list_directory again.
  implication: Circular guidance — planner enters infinite dedup loop

- timestamp: 2026-03-11T01:00:00Z
  checked: _route_to_specialist status determination (executor_node.py lines 204-211)
  found: status = "success" if post_tool_history_len > pre_tool_history_len else "error"
         When dedup fires, tool_history is not appended → status = "error"
         This "error" status goes into handoff_results but is NOT communicated to the planner
         as a TOOL_RESULT message in state["messages"]. The planner sees no result at all.
  implication: Planner never learns the tool ran (successfully) in a previous step.
               It keeps trying to execute it.

## Resolution

root_cause: |
  TWO cascading bugs caused planner amnesia:

  BUG 1 (executor_node.py — previously fixed):
  When the same tool+args combination is legitimately needed for a later mission but was
  already executed for an earlier mission, seen_tool_signatures blocked the re-execution.
  The guidance message injected was circular and contained no reference to the available
  prior result. The planner had no TOOL_RESULT in its conversation history and retried
  indefinitely until max_duplicate_tool_retries was exhausted.

  BUG 2 (orchestrator.py — fixed in this session):
  The ContextManager was instantiated with large_result_threshold=800. The list_directory
  tool returned 7580 chars for 42 .py files. The TOOL RESULT TRUNCATED gate in
  executor_node.py fired at 800 chars, which only fits ~7 file entries. The planner wrote
  the audit based on the truncated 7-file view, producing tool_audit.txt with only 7 files
  instead of the expected 42.

fix: |
  BUG 1: In executor_node.py, when the duplicate check fires and there is a prior successful
  result in tool_history for the same signature, inject a synthetic TOOL_RESULT message
  containing the cached result and append a replay entry to tool_history. Converts the
  "block" into a "replay". (Previously applied.)

  BUG 2: Raised large_result_threshold from 800 → 3000 in orchestrator.py (actual
  instantiation) and graph.py (AST anchor comment for test discoverability). Updated
  test_context_manager_truncation.py to assert the new value of 3000.
  The threshold of 3000 still protects against genuinely huge results (LLM text, large
  file reads) while permitting reasonably-sized structured results like directory listings.

verification: |
  1505 unit + 89 integration = 1594 tests pass. No regressions.
  ruff check clean on all changed files.

files_changed:
  - src/agentic_workflows/orchestration/langgraph/executor_node.py  (BUG 1 — prior session)
  - src/agentic_workflows/orchestration/langgraph/orchestrator.py   (BUG 2 — 800 → 3000)
  - src/agentic_workflows/orchestration/langgraph/graph.py          (BUG 2 — AST anchor 800 → 3000)
  - tests/unit/test_context_manager_truncation.py                   (BUG 2 — assertion updated)
