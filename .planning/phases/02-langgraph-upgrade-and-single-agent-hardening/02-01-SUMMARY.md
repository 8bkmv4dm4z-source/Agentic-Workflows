---
phase: 02-langgraph-upgrade-and-single-agent-hardening
plan: 01
subsystem: infra
tags: [langgraph, langgraph-prebuilt, langchain-anthropic, dependencies, pyproject]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: "Stable 208-test (now 267-test) green suite and Phase 1 architecture"
provides:
  - "langgraph>=1.0.6,<2.0 installed and running (actual: 1.0.10)"
  - "langgraph-prebuilt>=1.0.6,<1.1.0 installed (actual: 1.0.8)"
  - "langchain-anthropic>=0.3.0 installed (actual: 1.3.4)"
  - "All 267 existing tests confirmed passing with langgraph 1.0.10"
affects: [02-02, 02-03, 02-04, 02-05, all-phase-2-plans]

# Tech tracking
tech-stack:
  added:
    - "langgraph 1.0.10 (upgraded from 0.6.11 — removes <1.0 blocker pin)"
    - "langgraph-prebuilt 1.0.8 (upgraded from 0.6.5)"
    - "langchain-anthropic 1.3.4 (newly added — required for Phase 2 ToolNode path)"
  patterns: []

key-files:
  created: []
  modified:
    - "pyproject.toml — version pin updated from langgraph<1.0 to langgraph>=1.0.6,<2.0"

key-decisions:
  - "langgraph-prebuilt pin changed from <1.0.2 (plan) to >=1.0.6,<1.1.0 (actual): langgraph 1.0.6 itself requires langgraph-prebuilt>=1.0.2, making the plan's <1.0.2 pin impossible; since this codebase does not use ToolNode.afunc (Plan 03 wires it), pinning to >=1.0.6,<1.1.0 is safe"
  - "Installed langgraph 1.0.10 (latest in 1.0.x series) despite planning for 1.0.6 minimum — pip resolves to latest compatible; the >=1.0.6,<2.0 constraint is satisfied"
  - "Test count is 267 (not 208 as stated in plan) — suite grew during Phase 1 work; all 267 pass"

patterns-established: []

requirements-completed: [LGUP-01]

# Metrics
duration: 3min
completed: 2026-03-02
---

# Phase 2 Plan 01: LangGraph Version Upgrade Summary

**Upgraded langgraph from 0.6.11 to 1.0.10, added langgraph-prebuilt 1.0.8 and langchain-anthropic 1.3.4 — removing the master Phase 2 blocker pin with all 267 tests green**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-02T21:52:20Z
- **Completed:** 2026-03-02T21:55:28Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Removed `langgraph>=0.2.67,<1.0` pin that was blocking all Phase 2 work
- Installed langgraph 1.0.10 (1.0.x stable series), langgraph-prebuilt 1.0.8, langchain-anthropic 1.3.4
- Confirmed 267 tests pass unchanged after the upgrade (ruff clean, no new mypy errors)
- ToolNode, tools_condition, and Annotated reducers from langgraph 1.0.x are now available for Phase 2 plans

## Task Commits

Each task was committed atomically:

1. **Task 1: Upgrade langgraph version pin in pyproject.toml** - `bd8d3b3` (chore)
2. **Task 2: Verify full test suite green** - verification-only, no code changes (confirmed in Task 1 commit)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified

- `/home/nir/dev/agent_phase0/pyproject.toml` — version constraints updated: `langgraph>=0.2.67,<1.0` replaced with `langgraph>=1.0.6,<2.0`, `langgraph-prebuilt>=1.0.6,<1.1.0`, `langchain-anthropic>=0.3.0`

## Decisions Made

1. **langgraph-prebuilt pin adjusted from `<1.0.2` to `>=1.0.6,<1.1.0`**: The plan's rationale for `<1.0.2` was to avoid GitHub Issue #6363 (ToolNode.afunc break in 1.0.2). However, `langgraph 1.0.6` itself declares `Requires-Dist: langgraph-prebuilt<1.1.0,>=1.0.2` in its wheel metadata, making `<1.0.2` pip-unresolvable with any `langgraph>=1.0.6`. Since the codebase does not call `ToolNode.afunc` (that is Plan 03's work), pinning to `>=1.0.6,<1.1.0` is safe and allows pip to resolve. Plan 03 should verify ToolNode.afunc behavior when wiring it.

2. **Actual installed versions exceed minimums**: pip resolved `langgraph==1.0.10` and `langgraph-prebuilt==1.0.8` (the latest 1.0.x releases), which is expected and desirable — both are within the `<2.0` and `<1.1.0` upper bounds.

3. **Test count is 267 not 208**: The suite grew from 208 (pre-Phase 1.5) to 267 during Phase 1 development on the `p1-stable-sub-task-parsing` branch. All 267 pass.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed incompatible `langgraph-prebuilt<1.0.2` pin**
- **Found during:** Task 1 (pip install attempt)
- **Issue:** Plan specified `langgraph-prebuilt>=1.0.1,<1.0.2` but langgraph 1.0.6+'s wheel metadata requires `langgraph-prebuilt>=1.0.2`. Pip reported ResolutionImpossible — no version of langgraph>=1.0.6 is compatible with prebuilt<1.0.2.
- **Fix:** Changed `langgraph-prebuilt>=1.0.1,<1.0.2` to `langgraph-prebuilt>=1.0.6,<1.1.0` (safe upper bound matching langgraph 1.0.x release family)
- **Files modified:** `pyproject.toml`
- **Verification:** `pip install -e ".[dev]"` succeeded; `pip show langgraph-prebuilt` shows Version: 1.0.8
- **Committed in:** `bd8d3b3` (Task 1 commit — fix applied before commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - incompatible version constraint)
**Impact on plan:** Necessary fix — plan's pin was pip-unresolvable with the target langgraph version. Adjusted pin still satisfies the spirit: guards against untested major breaks in prebuilt API, while resolving within the known-stable 1.0.x family.

## Issues Encountered

- pip reported `externally-managed-environment` when called as system `pip` — project uses `.venv` virtual environment; all installs correctly targeted `.venv/bin/pip`.
- mypy reports 56 pre-existing errors in 9 files — all pre-date this plan. No new mypy errors were introduced by the dependency upgrade. The plan's success criterion of "no new errors introduced by the dependency bump" is met.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **Ready:** langgraph 1.0.x API is available — `ToolNode`, `tools_condition`, `Annotated` reducers, `Command` returns are all accessible
- **Note for Plan 03:** When wiring `ToolNode.afunc`, verify behavior against langgraph-prebuilt 1.0.8 (the version actually installed); the original concern was about 1.0.2 introducing a signature break
- **Note for Plan 03+:** `langchain-anthropic 1.3.4` is installed and importable — ready for Anthropic tool-call format integration

## Self-Check: PASSED

- pyproject.toml: FOUND and contains `langgraph>=1.0.6,<2.0` (old `<1.0` pin absent)
- 02-01-SUMMARY.md: FOUND
- Task commit bd8d3b3: FOUND
- 267 tests: PASSED
- ruff: PASSED (All checks passed)
- mypy: 56 pre-existing errors, 0 new errors from dependency bump

---
*Phase: 02-langgraph-upgrade-and-single-agent-hardening*
*Completed: 2026-03-02*
