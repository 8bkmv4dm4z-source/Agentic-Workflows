---
phase: 02-langgraph-upgrade-and-single-agent-hardening
plan: 04
subsystem: observability
tags: [langfuse, observe, adr, architecture, documentation]

# Dependency graph
requires:
  - phase: 02-01
    provides: langgraph 1.0 upgrade enabling Phase 2 work
provides:
  - "@observe(name='run') decorator on main() entrypoint in run.py (OBSV-02 closed)"
  - "docs/ADR/ directory with 4 architectural decision records (LRNG-02)"
affects:
  - 02-03-toolnode
  - 03-specialist-subgraph

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "@observe(name=...) decorator pattern applied to all major entrypoints (run.py, graph.py, provider.py)"
    - "ADR format: Status/Context/Decision/Consequences in docs/ADR/"

key-files:
  created:
    - docs/ADR/ADR-001-langgraph-version-upgrade.md
    - docs/ADR/ADR-002-toolnode-anthropic-path.md
    - docs/ADR/ADR-003-annotated-reducers.md
    - docs/ADR/ADR-004-message-compaction.md
  modified:
    - src/agentic_workflows/orchestration/langgraph/run.py

key-decisions:
  - "@observe(name='run') applied to main() in run.py — main() is the CLI entrypoint, graph.py orchestrator.run() already had @observe('langgraph.orchestrator.run')"
  - "ADR format established as Status/Context/Decision/Consequences for all architectural records"

patterns-established:
  - "ADR pattern: every major architectural choice in docs/ADR/ with Status, Context, Decision, Consequences"
  - "Observability coverage: all three layers (run entrypoint, orchestrator, provider) now instrumented with @observe"

requirements-completed: [OBSV-02, LRNG-02]

# Metrics
duration: 4min
completed: 2026-03-02
---

# Phase 2 Plan 04: @observe Entrypoint Wiring and ADR Log Summary

**@observe(name="run") added to run.py main() CLI entrypoint, closing OBSV-02; docs/ADR/ established with four Phase 2 architectural decision records covering LangGraph pin removal, ToolNode scoping, Annotated reducers, and message compaction**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-03-02T22:08:05Z
- **Completed:** 2026-03-02T22:12:08Z
- **Tasks:** 2
- **Files modified:** 5 (1 modified, 4 created)

## Accomplishments
- Wired `@observe(name="run")` on `main()` in `run.py` — the last undecorated major entrypoint; graph.py and provider.py were already instrumented. Closes Phase 1 OBSV-02 open item.
- Created `docs/ADR/` directory with 4 ADRs documenting every key Phase 2 architectural decision (LRNG-02)
- All 277 tests pass, ruff clean — no regressions from decorator addition (graceful degradation confirmed)

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire @observe() on run() in run.py** - `38e70ac` (feat)
2. **Task 2: Create docs/ADR/ with four ADRs** - `c7deb9c` (feat)

**Plan metadata:** (included in final commit)

## Files Created/Modified
- `src/agentic_workflows/orchestration/langgraph/run.py` - Added `observe` import and `@observe(name="run")` decorator on `main()` CLI entrypoint
- `docs/ADR/ADR-001-langgraph-version-upgrade.md` - Decision record: remove langgraph<1.0 pin; new pins langgraph>=1.0.6,<2.0 and langchain-anthropic
- `docs/ADR/ADR-002-toolnode-anthropic-path.md` - Decision record: ToolNode adoption scoped to Anthropic path only; existing paths unchanged
- `docs/ADR/ADR-003-annotated-reducers.md` - Decision record: Annotated[list[T], operator.add] on 4 RunState list fields; _sequential_node() wrapper rationale
- `docs/ADR/ADR-004-message-compaction.md` - Decision record: sliding-window compaction in ensure_state_defaults(); LLM summarization rejected

## Decisions Made
- Applied `@observe(name="run")` to `main()` rather than a non-existent `run()` function — `main()` is the actual CLI entrypoint in `run.py`; `orchestrator.run()` in `graph.py` was already decorated separately
- Used keyword argument form `@observe(name="run")` for span name clarity, matching the plan's specification

## Deviations from Plan

None - plan executed exactly as written. The plan referenced decorating `run()` in `run.py`; `main()` was correctly identified as the CLI entrypoint function (the plan's "run()" label refers to the run entrypoint, not a function named `run`).

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required. The `@observe()` decorator gracefully degrades to a no-op when `LANGFUSE_PUBLIC_KEY` is not set.

## Next Phase Readiness
- Observability now covers all three execution layers: `run.py` entrypoint, `graph.py` orchestrator, and `provider.py` generate methods
- ADR log established — all future architectural decisions should be recorded in `docs/ADR/`
- Ready for Plan 02-05 (or continuation of Phase 2 ToolNode work)

---
*Phase: 02-langgraph-upgrade-and-single-agent-hardening*
*Completed: 2026-03-02*
