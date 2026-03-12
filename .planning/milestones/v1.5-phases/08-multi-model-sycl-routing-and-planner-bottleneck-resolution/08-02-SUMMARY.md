---
phase: 08-multi-model-sycl-routing-and-planner-bottleneck-resolution
plan: "02"
subsystem: infra
tags: [llamacpp, sycl, provider, routing, multi-server]

# Dependency graph
requires:
  - phase: 08-01
    provides: Wave 0 test stubs (RED) for with_port() and orchestrator port wiring

provides:
  - LlamaCppChatProvider.with_port(port) factory method
  - Orchestrator LLAMA_CPP_PLANNER_PORT / LLAMA_CPP_EXECUTOR_PORT env var reading
  - _generate_with_hard_timeout optional provider param
  - _planner_provider / _executor_provider role-specific routing
  - structural_health fields: tool_result_cache_hits, tool_result_truncations

affects:
  - 08-03
  - 08-04

# Tech tracking
tech-stack:
  added: []
  patterns:
    - with_port() clone pattern using urllib.parse for URL port substitution (mirrors with_alias() but creates fresh OpenAI client)
    - Startup reachability check with warn+fallback (no hard fail on unreachable port)
    - Optional provider param on _generate_with_hard_timeout for role-specific dispatch

key-files:
  created: []
  modified:
    - src/agentic_workflows/orchestration/langgraph/provider.py
    - src/agentic_workflows/orchestration/langgraph/graph.py
    - src/agentic_workflows/orchestration/langgraph/state_schema.py
    - tests/unit/test_provider_port.py
    - .env.example

key-decisions:
  - "with_port() uses urllib.parse (not regex) for URL port substitution — per RESEARCH.md Pitfall 3"
  - "_detect_llama_cpp_model imported into graph.py namespace so it can be patched in tests"
  - "_build_port_url module-level helper avoids duplicating urllib.parse logic in __init__"
  - "When no port env vars set, _planner_provider and _executor_provider are identical to self.provider — no behavior change for existing setups"
  - "Unreachable port logs WARNING and falls back to default server — no hard fail"
  - "_generate_with_hard_timeout provider param takes priority over router when not None — planner callers pass self._planner_provider"

patterns-established:
  - "with_port() clone: __new__ + copy all attributes + fresh OpenAI client with updated base_url"
  - "Port reachability: _detect_llama_cpp_model() called at init; None return → warning + fallback"

requirements-completed:
  - SYCL-01

# Metrics
duration: 7min
completed: 2026-03-11
---

# Phase 08 Plan 02: SYCL-01 Provider Port Routing Summary

**LlamaCppChatProvider.with_port() factory and orchestrator SYCL multi-server routing via LLAMA_CPP_PLANNER_PORT/EXECUTOR_PORT env vars with warn+fallback on unreachable ports**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-11T14:10:00Z
- **Completed:** 2026-03-11T14:17:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Added `with_port(port)` factory to `LlamaCppChatProvider` — clones provider with fresh OpenAI client pointing at given port, preserving all settings
- Orchestrator reads `LLAMA_CPP_PLANNER_PORT` / `LLAMA_CPP_EXECUTOR_PORT` at init, assigns `_planner_provider` / `_executor_provider` via `with_port()` (or falls back with WARNING if unreachable)
- `_generate_with_hard_timeout()` gains optional `provider: ChatProvider | None` param; `_plan_next_action()` passes `self._planner_provider`
- `structural_health` gains `tool_result_cache_hits` and `tool_result_truncations` defaults in `new_run_state()` and `ensure_state_defaults()`
- All 8 test stubs replaced with real assertions; 1586 tests pass (0 regressions)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add with_port() factory method to LlamaCppChatProvider** - `042d992` (feat)
2. **Task 2: Wire role-specific providers in orchestrator and _generate_with_hard_timeout** - `b0d135e` (feat)

_Note: TDD tasks — stubs replaced with real assertions in same task commit._

## Files Created/Modified

- `src/agentic_workflows/orchestration/langgraph/provider.py` - Added `with_port()` method after `with_alias()`
- `src/agentic_workflows/orchestration/langgraph/graph.py` - Added `_build_port_url` helper, `_detect_llama_cpp_model` import, port env var wiring in `__init__`, `provider` param on `_generate_with_hard_timeout`, planner provider pass-through
- `src/agentic_workflows/orchestration/langgraph/state_schema.py` - Added `tool_result_cache_hits` and `tool_result_truncations` defaults
- `tests/unit/test_provider_port.py` - Replaced 8 NotImplementedError stubs with real assertions
- `.env.example` - Documented `LLAMA_CPP_PLANNER_PORT` / `LLAMA_CPP_EXECUTOR_PORT`

## Decisions Made

- Used `urllib.parse` (not regex) for URL port substitution — per RESEARCH.md Pitfall 3, handles edge cases like IPv6 and paths correctly
- Imported `_detect_llama_cpp_model` into `graph.py` namespace explicitly so tests can patch `agentic_workflows.orchestration.langgraph.graph._detect_llama_cpp_model`
- `_build_port_url` added as module-level helper to avoid duplicating urllib.parse logic in `__init__`
- When no port env vars set, `_planner_provider is self.provider` — zero behavior change for existing single-server setups
- `provider` param on `_generate_with_hard_timeout` takes priority over router when not None; `_plan_next_action` passes `self._planner_provider`

## Deviations from Plan

None - plan executed exactly as written. Minor deviation: test file used `ScriptedChatProvider` (which doesn't exist in provider.py) — fixed to use `ScriptedProvider` from `tests.conftest`.

## Issues Encountered

- Test env used `P1_PROVIDER=llamacpp` but build_provider requires `llama-cpp` — fixed in test setup.
- `ScriptedChatProvider` import path was wrong — corrected to `tests.conftest.ScriptedProvider`.

## User Setup Required

To use SYCL dual-server routing, set in `.env`:
```
LLAMA_CPP_PLANNER_PORT=8080
LLAMA_CPP_EXECUTOR_PORT=8081
```
Planner will use port 8080, executor will use 8081. If either port is unreachable at startup, a WARNING is logged and that role falls back to the default server.

## Next Phase Readiness

- with_port() and orchestrator wiring ready for Plan 03 (executor provider selection)
- structural_health fields available for Plan 04 (ToolResultCache hit/truncation tracking)
- All existing tests pass — no regressions

## Self-Check: PASSED

All artifacts verified:
- provider.py: with_port() method present
- graph.py: _planner_provider wired
- state_schema.py: tool_result_cache_hits/truncations present
- 08-02-SUMMARY.md: created
- Commits 042d992, b0d135e: verified in git log

---
*Phase: 08-multi-model-sycl-routing-and-planner-bottleneck-resolution*
*Completed: 2026-03-11*
