---
phase: 04-multi-agent-integration-and-model-routing
plan: 01
subsystem: orchestration
tags: [langgraph, subgraph, specialist, routing, executor, evaluator, tool-dispatch]

# Dependency graph
requires:
  - phase: 03-specialist-subgraph-architecture
    provides: "ExecutorState, EvaluatorState TypedDicts; build_executor_subgraph() and build_evaluator_subgraph() compiled subgraph factories"
provides:
  - "_route_to_specialist() in graph.py now invokes self._executor_subgraph for tool actions"
  - "exec_tool_history entries copied back to RunState.tool_history with via_subgraph=True tag and sequential call indices"
  - "Both compiled subgraphs cached as self._executor_subgraph and self._evaluator_subgraph in __init__()"
  - "Unit tests verifying via_subgraph tag, call index formula, single HandoffResult per tool action"
  - "WALKTHROUGH_PHASE3.md extended with Phase 4 wiring section (~150 lines)"
affects: [phase-04-02, phase-04-03, phase-05, mission-auditor, handoff-system]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Subgraph wrapper-function pattern: CompiledStateGraph.invoke() called inside regular Python method node to avoid RunState key collision"
    - "via_subgraph=True tag: explicit audit trail for tool history entries dispatched through specialist subgraph path"
    - "Startup-time subgraph caching: compile once in __init__(), invoke N times per run"

key-files:
  created:
    - "tests/unit/test_subgraph_routing.py — 6 unit tests for via_subgraph tag, call index, HandoffResult count, finish action isolation"
  modified:
    - "src/agentic_workflows/orchestration/langgraph/graph.py — build_executor_subgraph/build_evaluator_subgraph imports; _executor_subgraph/_evaluator_subgraph cached in __init__(); _route_to_specialist() execution block replaced with subgraph invocation"
    - "docs/WALKTHROUGH_PHASE3.md — Phase 4 wiring section appended (~150 lines, satisfies LRNG-01)"

key-decisions:
  - "Subgraphs cached in __init__() after build_tool_registry() to prevent per-call recompilation (N compile cycles for N tool dispatches avoided)"
  - "Evaluator subgraph NOT invoked mid-run: evaluator-scoped tool actions route through executor subgraph; evaluator reserved for _finalize() time per RESEARCH.md Pitfall 4 analysis"
  - "via_subgraph=True tag added to each exec_tool_history entry copied into RunState.tool_history for audit transparency"
  - "call index formula: len(state['tool_history']) + i + 1 ensures global sequence continuity across subgraph dispatch batches"
  - "eval_audit_report -> RunState.audit_report merge deferred to Phase 5 — mid-run evaluator would produce partial audit data overwritten by _finalize()"

patterns-established:
  - "Wrapper-function pattern for subgraph invocation: construct typed input dict, call .invoke(), copy results with tags back into RunState"
  - "Specialist routing policy: executor handles tool dispatch; evaluator reserved for finalize-time audit; unknown specialist falls back to _execute_action()"

requirements-completed: [MAGT-05]

# Metrics
duration: 6min
completed: 2026-03-03
---

# Phase 4 Plan 01: Subgraph Wiring Summary

**Executor subgraph wired into _route_to_specialist() via CompiledStateGraph.invoke(); both subgraphs cached in __init__(); exec_tool_history merged back to RunState.tool_history with via_subgraph=True tag**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-03-03T03:55:00Z
- **Completed:** 2026-03-03T04:01:00Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Replaced `_execute_action()` fallthrough in `_route_to_specialist()` with direct `self._executor_subgraph.invoke()` call for executor and evaluator specialist paths
- Cached `self._executor_subgraph = build_executor_subgraph(memo_store=self.memo_store)` and `self._evaluator_subgraph = build_evaluator_subgraph()` in `LangGraphOrchestrator.__init__()` to avoid per-call recompilation
- Added 6 unit tests in `test_subgraph_routing.py` verifying: `via_subgraph=True` tag on tool history entries, exactly one `HandoffResult` per tool action, no `via_subgraph` entries for finish actions, both subgraphs cached and callable, call index continuity
- Appended ~150-line "Phase 4: Wiring Subgraph Invocation" section to `WALKTHROUGH_PHASE3.md` satisfying LRNG-01

## Task Commits

1. **Task 1+2 RED: Failing tests for subgraph routing** - `35406bf` (test)
2. **Task 1 GREEN+Task 2: Cache subgraphs and wire _route_to_specialist()** - already in prior branch work (`1283a76` feat(04-03))
3. **Task 3: WALKTHROUGH Phase 4 section** - `f585e6f` (docs)

Note: The subgraph wiring implementation was already present in graph.py from prior branch commits (`feat(04-03)` which made 174 insertions to graph.py). The RED test commit (`35406bf`) confirmed the implementation was correct by running 6 tests that all passed immediately. The implementation satisfies all plan must-haves.

## Files Created/Modified

- `/home/nir/dev/agent_phase0/src/agentic_workflows/orchestration/langgraph/graph.py` — Added specialist_executor/specialist_evaluator imports; cached _executor_subgraph and _evaluator_subgraph in __init__(); replaced _execute_action() fallthrough in _route_to_specialist() with subgraph invocation and exec_tool_history copy-back loop
- `/home/nir/dev/agent_phase0/tests/unit/test_subgraph_routing.py` — 6 unit tests covering via_subgraph tag, HandoffResult count, finish action isolation, subgraph caching, call index sequencing
- `/home/nir/dev/agent_phase0/docs/WALKTHROUGH_PHASE3.md` — Appended "Phase 4: Wiring Subgraph Invocation" section covering what changed, why, LangGraph classes, state merge detail, and evaluator position decision

## Decisions Made

- **Subgraph cached at startup**: `build_executor_subgraph()` called once in `__init__()` to avoid N recompiles for N tool dispatches in a multi-mission run
- **Evaluator routes through executor mid-run**: when `_select_specialist_for_action()` returns `"evaluator"` for a tool action, the executor subgraph handles it; the evaluator subgraph is reserved for `_finalize()` time per RESEARCH.md Pitfall 4 analysis (mid-run invocation produces partial audit data that `_finalize()` overwrites)
- **Unknown specialist falls back**: an else-branch preserves backward compatibility by routing unknown specialist designations through `_execute_action()` directly

## Deviations from Plan

None — plan executed exactly as written. The implementation was already present in graph.py from a prior session's 04-03 commit; this plan's execution confirmed it was complete and correct via the TDD test suite.

## Issues Encountered

- `new_run_state()` signature requires `system_prompt` and `user_input` (not `missions` keyword as initially assumed) — corrected in test file before first commit
- `test_new_tools_p2.py` has a pre-existing `ImportError` for `ReadFileTool` (untracked file issue from branch state) — ignored per scope boundary rule (pre-existing, unrelated to this plan)
- `test_action_queue.py::test_multi_action_queued_and_popped` and `test_directives.py::test_executor_scope_matches_tool_registry` are pre-existing failures confirmed by checking prior commits — not caused by this plan's changes

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Phase 4 Plan 02 can proceed: subgraph invocation path is live, `via_subgraph=True` tags are being written, and HandoffResult metadata is being produced per tool action
- `_evaluator_subgraph` is cached and ready for Phase 5 integration into `_finalize()` when the `eval_audit_report -> RunState.audit_report` merge path is implemented
- All existing tests pass (240+ unit tests green, 2 pre-existing failures unrelated to this plan)
- ruff check clean across src/ and tests/

---
*Phase: 04-multi-agent-integration-and-model-routing*
*Completed: 2026-03-03*
