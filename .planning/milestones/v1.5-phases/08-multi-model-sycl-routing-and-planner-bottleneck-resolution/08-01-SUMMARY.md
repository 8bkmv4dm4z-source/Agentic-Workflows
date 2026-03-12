---
phase: 08-multi-model-sycl-routing-and-planner-bottleneck-resolution
plan: "01"
subsystem: testing
tags: [tdd, wave0, stubs, provider, cache, context-overflow, sycl]

# Dependency graph
requires:
  - phase: 07.8-multi-model-provider-routing-smart-cloud-fallback
    provides: LlamaCppChatProvider with with_alias() __new__-clone pattern
  - phase: 07.5-wire-artifactstore-to-runtime
    provides: ArtifactStore pool=None no-op pattern for storage classes
provides:
  - NotImplementedError stubs for SYCL-01 with_port() factory (8 tests)
  - NotImplementedError stubs for BTLNK-02 ToolResultCache (7 tests)
  - NotImplementedError stubs for BTLNK-01 large-result context cap (2 tests)
affects:
  - 08-02 (implements with_port() and orchestrator port env var wiring)
  - 08-03 (implements ToolResultCache storage class)
  - 08-05 (implements context overflow integration tests)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Wave 0 stubs use NotImplementedError (not pytest.skip) to guarantee RED state at collection time"
    - "Try/except at module level for not-yet-existing imports (ToolResultCache)"
    - "pytest.importorskip('psycopg_pool') at module level for Postgres integration test files"
    - "Lazy import inside test function body for orchestrator/graph imports (avoids collection overhead)"

key-files:
  created:
    - tests/unit/test_provider_port.py
    - tests/unit/test_tool_result_cache.py
    - tests/integration/test_context_overflow.py
  modified: []

key-decisions:
  - "Wave 0 stubs use NotImplementedError (not pytest.skip) to guarantee RED state — skip counts as not-FAILED per 07.6-00 decision"
  - "Integration stubs use pytest.importorskip('psycopg_pool') + requires_postgres marker — project-standard pattern from Phase 7 decisions"
  - "LangGraphOrchestrator imported lazily inside test function body for orchestrator stubs — avoids collection-time import overhead"

patterns-established:
  - "Wave 0 RED state: all stubs raise NotImplementedError to guarantee collection-time failure before implementation"

requirements-completed:
  - SYCL-01
  - SYCL-02
  - BTLNK-01
  - BTLNK-02

# Metrics
duration: 8min
completed: 2026-03-11
---

# Phase 08 Plan 01: Wave 0 Failing Test Stubs Summary

**17 NotImplementedError test stubs across 3 files establish RED state for SYCL-01 (with_port factory), BTLNK-02 (ToolResultCache), and BTLNK-01 (large-result context cap) before any implementation.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-11T14:01:45Z
- **Completed:** 2026-03-11T14:09:30Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Created 8 failing stubs in test_provider_port.py covering SYCL-01: with_port() factory (4 tests) and orchestrator port env var wiring (4 tests)
- Created 7 failing stubs in test_tool_result_cache.py covering BTLNK-02: store/get round trip, TTL expiry, pool=None no-op behavior, stable args hash, structural_health truncation counter
- Created 2 stubs in tests/integration/test_context_overflow.py covering BTLNK-01: large-result planner injection cap and cache retrievability (psycopg_pool-skipped in CI)
- Zero regressions: 1570 existing tests still pass

## Task Commits

Each task was committed atomically:

1. **Task 1: Create test_provider_port.py stubs for SYCL-01** - `f42d584` (test)
2. **Task 2: Create test_tool_result_cache.py and test_context_overflow.py stubs** - `fd18a56` (test)

**Plan metadata:** (pending docs commit)

## Files Created/Modified
- `tests/unit/test_provider_port.py` - 8 Wave 0 stubs: with_port() factory and orchestrator port env var wiring
- `tests/unit/test_tool_result_cache.py` - 7 Wave 0 stubs: ToolResultCache store/get/TTL/pool-none/hash
- `tests/integration/test_context_overflow.py` - 2 Wave 0 stubs: large-result planner cap and full-result cache retrieval

## Decisions Made
- Wave 0 stubs use NotImplementedError (not pytest.skip) to guarantee RED state at collection time — consistent with Phase 07.6-00 decision
- LangGraphOrchestrator imported lazily inside test function body for orchestrator stubs (avoids collection-time import cost in unit tests)
- Integration stubs use pytest.importorskip("psycopg_pool") at module level — project-standard Postgres test pattern from Phase 7

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 3 RED-state test files in place; Plan 02 can begin implementing with_port() on LlamaCppChatProvider and orchestrator port env var wiring
- ToolResultCache storage class (Plan 03/04) will turn 7 unit stubs GREEN
- Context overflow integration tests (Plan 05) will turn 2 integration stubs GREEN once ToolResultCache and ContextManager wiring complete

## Self-Check: PASSED
- `tests/unit/test_provider_port.py` — FOUND (8 tests, 8 NotImplementedError failures confirmed)
- `tests/unit/test_tool_result_cache.py` — FOUND (7 tests, 7 NotImplementedError failures confirmed)
- `tests/integration/test_context_overflow.py` — FOUND (2 tests skipped via psycopg_pool importorskip)
- Commit `f42d584` — FOUND
- Commit `fd18a56` — FOUND

---
*Phase: 08-multi-model-sycl-routing-and-planner-bottleneck-resolution*
*Completed: 2026-03-11*
