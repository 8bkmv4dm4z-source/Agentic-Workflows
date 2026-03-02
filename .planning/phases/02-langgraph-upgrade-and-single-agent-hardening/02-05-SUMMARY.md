---
phase: 02-langgraph-upgrade-and-single-agent-hardening
plan: 05
subsystem: infra
tags: [github-actions, ci, ruff, mypy, pytest, scripted-provider]

# Dependency graph
requires:
  - phase: 02-01
    provides: langgraph 1.0.10 installed, test suite baseline at 267 tests

provides:
  - GitHub Actions CI workflow at .github/workflows/ci.yml
  - Automated quality gate: lint (ruff) + typecheck (mypy) + test (pytest) on every push and PR

affects:
  - all future phases (CI now gates every branch push and PR to main)

# Tech tracking
tech-stack:
  added: [github-actions (actions/checkout@v4, actions/setup-python@v5)]
  patterns: [CI workflow with scripted test double — no live LLM API keys required in CI]

key-files:
  created:
    - .github/workflows/ci.yml
  modified: []

key-decisions:
  - "branches: ['**'] on push trigger catches all feature branches, not just main"
  - "P1_PROVIDER=scripted in CI env — ScriptedProvider handles all LLM interaction, zero live API keys needed"
  - "No pip cache added — keep it simple; caching deferred to Phase 7 per CONTEXT.md"
  - "Single job named 'quality' with three sequential steps: lint -> typecheck -> test"

patterns-established:
  - "CI workflow: ruff check first, then mypy, then pytest — fail-fast on cheaper checks"
  - "Test isolation via environment variable injection (P1_PROVIDER=scripted) in CI env block"

requirements-completed: []

# Metrics
duration: 3min
completed: 2026-03-03
---

# Phase 2 Plan 05: CI Workflow Summary

**GitHub Actions CI workflow that runs ruff, mypy, and pytest on every push using ScriptedProvider — zero live LLM API keys required**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-02T22:08:32Z
- **Completed:** 2026-03-02T22:11:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Created `.github/workflows/ci.yml` as a full quality gate covering lint, typecheck, and test
- Configured triggers: push to all branches (`"**"`) and pull requests targeting `main`
- Set `P1_PROVIDER: scripted` in CI env so tests run without any live LLM provider keys
- Confirmed existing `claude.yml` is untouched

## Task Commits

Each task was committed atomically:

1. **Task 1: Create GitHub Actions CI workflow** - `8b7214b` (chore)

**Plan metadata:** (committed with final docs commit)

## Files Created/Modified
- `.github/workflows/ci.yml` — GitHub Actions workflow with lint/typecheck/test job using Python 3.12 and ScriptedProvider

## Decisions Made
- `branches: ["**"]` on push — catches all feature branches for continuous quality gating
- `P1_PROVIDER: scripted` env var in CI test step — prevents any accidental live API calls even if secrets were injected
- No API key secrets configured — structurally impossible to make live LLM calls from CI
- Sequential single-job design (not matrix) — simpler to debug and sufficient for current scope

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- `yamllint` not available on host — YAML validated via structure review; standard GitHub Actions YAML is well-formed

## User Setup Required
None - no external service configuration required. Workflow triggers automatically on git push.

## Next Phase Readiness
- CI gate is live and will run on any push to the repo
- All three Plans 02-05 success criteria are verifiable via `grep` checks on the file
- Phase 2 success criterion #5 (CI workflow) is satisfied

---
*Phase: 02-langgraph-upgrade-and-single-agent-hardening*
*Completed: 2026-03-03*
