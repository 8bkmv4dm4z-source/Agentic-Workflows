---
phase: 04-multi-agent-integration-and-model-routing
plan: 03
subsystem: orchestration
tags: [model-router, provider-routing, langgraph, multi-provider, task-complexity]

# Dependency graph
requires:
  - phase: 03-specialist-subgraph
    provides: LangGraphOrchestrator base with specialist subgraphs and ChatProvider protocol
provides:
  - ModelRouter wired in LangGraphOrchestrator.__init__() via self._router
  - _generate_with_hard_timeout() routes via self._router.route(complexity) instead of self.provider
  - fast_provider optional constructor arg for dual-provider configuration
  - 5 unit tests confirming routing split and backward compatibility
  - 2 integration tests proving strong provider receives planning calls end-to-end
affects:
  - 04-multi-agent-integration-and-model-routing
  - future phases adding fast provider configuration

# Tech tracking
tech-stack:
  added: []
  patterns:
    - ModelRouter.route(complexity) wraps provider selection; callers never reference self.provider directly for generate() calls
    - complexity="planning" as default arg maintains full backward compatibility with all existing call sites
    - TrackedScriptedProvider pattern for counting generate() calls in integration tests without live LLM

key-files:
  created:
    - tests/unit/test_model_router_wiring.py
    - tests/integration/test_model_router_integration.py
  modified:
    - src/agentic_workflows/orchestration/langgraph/graph.py

key-decisions:
  - "fast_provider=None defaults to same as strong_provider via ModelRouter fallback — zero behavior change for single-provider configs"
  - "complexity='planning' default in _generate_with_hard_timeout() ensures all existing call sites continue routing to strong provider without modification"
  - "self.provider is preserved on the orchestrator (not removed) — used by Anthropic ToolNode path and provider-type checks elsewhere"

patterns-established:
  - "TaskComplexity = 'planning' default: all _generate_with_hard_timeout() callers pass strong provider by default; explicit 'tool_selection' opt-in for fast provider"
  - "TrackedScriptedProvider: minimal inline scripted provider with call_count for integration assertions"

requirements-completed: [OBSV-03]

# Metrics
duration: 5min
completed: 2026-03-03
---

# Phase 04 Plan 03: ModelRouter Wiring Summary

**ModelRouter wired into LangGraphOrchestrator via self._router; _generate_with_hard_timeout() routes by TaskComplexity with backward-compat fast_provider=None fallback**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-03T01:54:59Z
- **Completed:** 2026-03-03T01:59:51Z
- **Tasks:** 3
- **Files modified:** 3 (1 modified, 2 created)

## Accomplishments
- Wired ModelRouter in LangGraphOrchestrator.__init__() with optional fast_provider parameter
- Updated _generate_with_hard_timeout() to accept complexity: TaskComplexity = "planning" and route via self._router.route(complexity)
- 5 unit tests confirm routing split (planning/evaluation/error_recovery -> strong; tool_selection/continuation -> fast) and backward compatibility
- 2 integration tests prove strong provider receives planning calls in end-to-end run with TrackedScriptedProvider

## Task Commits

Each task was committed atomically:

1. **Task 1: Add fast_provider arg and wire ModelRouter in __init__() and _generate_with_hard_timeout()** - `1283a76` (feat)
2. **Task 2: Unit tests for ModelRouter routing split and backward compatibility** - `b37a9e5` (test)
3. **Task 3: Integration test — end-to-end routing verification with dual provider stubs** - `80e87d8` (test)

**Plan metadata:** (final commit hash — see state update)

_Note: TDD tasks executed as RED (verify test fails) -> GREEN (implement + pass) for all 3 tasks_

## Files Created/Modified
- `src/agentic_workflows/orchestration/langgraph/graph.py` - Added fast_provider arg, ModelRouter instantiation in __init__(), updated _generate_with_hard_timeout() signature and body
- `tests/unit/test_model_router_wiring.py` - 5 unit tests: routing split and orchestrator wiring
- `tests/integration/test_model_router_integration.py` - 2 integration tests: end-to-end dual-provider and single-provider verification

## Decisions Made
- fast_provider=None defaults to same as strong_provider via ModelRouter's existing fallback — zero behavior change for single-provider configs
- complexity="planning" as default arg maintains full backward compatibility with all existing _generate_with_hard_timeout() call sites
- self.provider is preserved on the orchestrator (not removed) — used by Anthropic ToolNode path and provider-type checks elsewhere
- Import placement follows alphabetical order per ruff I001 rule: mission_parser -> model_router -> policy -> provider -> specialist_evaluator -> specialist_executor -> state_schema

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed import ordering to satisfy ruff I001**
- **Found during:** Task 1 (after implementing the changes)
- **Issue:** Adding `model_router` import between `mission_parser` and `specialist_evaluator/specialist_executor` left the import block unsorted (specialist_* "sp" appeared before provider "pr")
- **Fix:** Reordered imports to alphabetical sequence: model_router -> policy -> provider -> specialist_evaluator -> specialist_executor
- **Files modified:** src/agentic_workflows/orchestration/langgraph/graph.py
- **Verification:** `ruff check src/...graph.py` passes
- **Committed in:** 1283a76 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (import ordering)
**Impact on plan:** Minor formatting fix, no scope creep.

## Issues Encountered
- Pre-existing test failures (28 tests) unrelated to this plan: test_langgraph_flow.py integration tests, test_action_queue, test_directives, test_subgraph_routing, and test_run_helpers — all pre-existing before Task 1 changes (verified via git stash). No new failures introduced.
- test_new_tools_p2.py has collection error (ImportError: ReadFileTool) — pre-existing, out of scope.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- ModelRouter is now wired and active; LangGraphOrchestrator ready to accept a second fast provider
- OBSV-03 requirement satisfied: real routing decisions via ModelRouter.route() in the hot path
- Plans 04-01 and 04-02 operate in a different subsystem (subgraph routing); no interference
- To enable dual-provider routing: pass fast_provider=<fast_instance> to LangGraphOrchestrator constructor

## Self-Check: PASSED

All artifacts verified:
- FOUND: tests/unit/test_model_router_wiring.py
- FOUND: tests/integration/test_model_router_integration.py
- FOUND: .planning/phases/04-multi-agent-integration-and-model-routing/04-03-SUMMARY.md
- FOUND commit: 1283a76 (Task 1 - graph.py wiring)
- FOUND commit: b37a9e5 (Task 2 - unit tests)
- FOUND commit: 80e87d8 (Task 3 - integration tests)

---
*Phase: 04-multi-agent-integration-and-model-routing*
*Completed: 2026-03-03*
