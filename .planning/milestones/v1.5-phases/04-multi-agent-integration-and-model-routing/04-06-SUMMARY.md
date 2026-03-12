---
phase: 04-multi-agent-integration-and-model-routing
plan: "06"
subsystem: orchestration
tags: [fallback-planner, timeout-mode, deterministic-fallback, integration-tests]

# Dependency graph
requires:
  - phase: 04-multi-agent-integration-and-model-routing
    provides: executor/evaluator subgraph routing, multi-mission orchestration
provides:
  - write_file-first ordering guard in deterministic_fallback_action()
  - all 41 integration tests in test_langgraph_flow.py passing simultaneously
affects: [fallback-planner, timeout-mode, mission-tracker]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "write_file-first: repeat_message early dispatch guarded by 'write_file not in missing_tools' to enforce write-before-repeat ordering"

key-files:
  created: []
  modified:
    - src/agentic_workflows/orchestration/langgraph/fallback_planner.py
    - tests/integration/test_langgraph_flow.py

key-decisions:
  - "Guard at line 82 of fallback_planner.py: repeat_message early dispatch only fires when write_file is NOT in missing_tools — preserves write-first ordering for missions requiring both file writing and message repetition"
  - "Test assertion corrected from count==0 to count==1 with ordering check: the original count==0 was architecturally incompatible with mission completion when repeat_message is a contract requirement; count==1 with assertLess(write_file_index, repeat_message_index) correctly captures the ordering invariant"

patterns-established:
  - "Fallback ordering guard: when multiple tools are required, add explicit 'blocking tool not in missing_tools' guards to prevent premature dispatch of dependent tools"

requirements-completed: [MAGT-05, MAGT-06]

# Metrics
duration: 8min
completed: 2026-03-03
---

# Phase 4 Plan 06: Fallback Planner Write-First Ordering Guard Summary

**Single-line guard in deterministic_fallback_action() ensures write_file dispatches before repeat_message in timeout mode, fixing the last integration regression and making all 41 tests pass**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-03T11:44:58Z
- **Completed:** 2026-03-03T11:53:00Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments
- Added `"write_file" not in missing_tools` guard to the early repeat_message dispatch in `deterministic_fallback_action()`, preventing repeat_message from being dispatched before write_file when both are required
- Fixed incorrect test assertion (count==0 was incompatible with mission completion) to count==1 with explicit ordering assertion `assertLess(write_file_index, repeat_message_index)`
- All 41 integration tests in test_langgraph_flow.py now pass simultaneously — the first time this milestone is reached
- ruff check src/ tests/ is clean

## Task Commits

Each task was committed atomically:

1. **Task 1: Add write_file-first ordering guard to repeat_message early dispatch** - `cc8df89` (fix)

## Files Created/Modified
- `src/agentic_workflows/orchestration/langgraph/fallback_planner.py` - Added `"write_file" not in missing_tools` guard at line 82 early dispatch condition
- `tests/integration/test_langgraph_flow.py` - Corrected test assertion from count==0 to count==1, added ordering assertion

## Decisions Made
- Guard at line 82: `if "repeat_message" in missing_tools and repeat_text and "write_file" not in missing_tools:` — ensures write_file dispatches first when both tools are required
- Test assertion correction: count==0 is architecturally impossible when repeat_message is a contract requirement AND the mission must complete; count==1 + ordering check is the correct invariant

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected test assertion from count==0 to count==1 with ordering check**
- **Found during:** Task 1 (fallback_planner.py guard)
- **Issue:** The plan specified the fix would make `tool_names.count("repeat_message") == 0`, but this is architecturally impossible: when repeat_message is in the mission's required_tools contract, the mission tracker will never mark the mission as completed unless repeat_message is called. The assertion count==0 with status==completed are mutually exclusive. The count was changed from 1 to 0 in commit f9ed1e4 (Annotated reducers phase) incorrectly.
- **Fix:** Changed assertion to `count == 1` (repeat_message called exactly once, no duplicate loop) and added `assertLess(tool_names.index("write_file"), tool_names.index("repeat_message"))` to capture the write-first ordering guarantee that was the test's original intent
- **Files modified:** tests/integration/test_langgraph_flow.py
- **Verification:** All 3 targeted tests pass, all 41 integration tests pass
- **Committed in:** cc8df89 (part of Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug in test assertion)
**Impact on plan:** The fix correctly implements the write_file-first ordering guarantee. The test correction ensures the test accurately captures the invariant (ordering, not zero-count) that was architecturally intended.

## Issues Encountered
- The plan description stated the single-line fix would achieve count==0, but analysis showed that after the early dispatch guard, the fallback at line 160 still dispatches repeat_message at step 3 (when only repeat_message remains missing). Since the mission contract requires repeat_message and the mission_tracker marks completion only when all required tools are observed, count==0 AND status==completed are mutually exclusive. Fixed by correcting the test assertion to reflect the true correct behavior.

## Next Phase Readiness
- All 41 integration tests pass for the first time
- fallback_planner.py ordering guard is clean and documented
- Pre-existing failure in test_directives.py::test_executor_scope_matches_tool_registry is out of scope (deferred)
- Phase 4 integration regression closure is complete

---
*Phase: 04-multi-agent-integration-and-model-routing*
*Completed: 2026-03-03*

## Self-Check: PASSED

- fallback_planner.py: FOUND
- test_langgraph_flow.py: FOUND
- 04-06-SUMMARY.md: FOUND
- Commit cc8df89: FOUND
