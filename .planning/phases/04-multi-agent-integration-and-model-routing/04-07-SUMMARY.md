---
phase: 04-multi-agent-integration-and-model-routing
plan: "07"
subsystem: tools, orchestration, ui
tags: [new-tools, clarify-action, ui-panels, diagnosis, retrospective]

# Dependency graph
requires:
  - phase: 04-multi-agent-integration-and-model-routing
    provides: all 6 plans complete (04-01 through 04-06), 351 tests passing
provides:
  - parse_code_structure tool (AST + regex, 13 tests)
  - describe_db_schema tool (SQLite PRAGMA + CSV, 8 tests)
  - clarify action type wired in graph (clarify_node → finalize)
  - _diagnose_incomplete_missions() injected into finish rejection messages
  - UI panels: clarification box, context warning, stuck indicator
affects: [tools-registry, graph, mission-parser, run-ui]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "clarify action: planner emits 'clarify' action to break confusion loops; clarify_node → finalize edge in graph"
    - "_diagnose_incomplete_missions(): injected into both finish-rejection paths to provide structured recovery context"
    - "AST + regex dual-mode parsing: ast.parse() for .py files, regex fallback for other languages in parse_code_structure"

key-files:
  created:
    - src/agentic_workflows/tools/parse_code_structure.py
    - src/agentic_workflows/tools/describe_db_schema.py
    - tests/unit/test_parse_code_structure.py
    - tests/unit/test_describe_db_schema.py
  modified:
    - src/agentic_workflows/tools/tools_registry.py
    - src/agentic_workflows/orchestration/langgraph/graph.py
    - src/agentic_workflows/orchestration/langgraph/mission_parser.py
    - src/agentic_workflows/orchestration/langgraph/run.py
    - src/agentic_workflows/schemas.py

key-decisions:
  - "parse_code_structure uses Python AST for .py files for correctness; regex fallback for non-Python to avoid hard ast.parse() failures on non-Python syntax"
  - "describe_db_schema handles both SQLite (PRAGMA table_info) and CSV (header + type inference) — unified schema description interface for two most common agent data sources"
  - "clarify action type added rather than repurposing 'finish' or 'error' — clean separation of concerns; clarify means 'I need more information', not 'I failed'"
  - "_diagnose_incomplete_missions() injected into finish rejection (not a new node) — minimal graph change, maximum diagnostic value; keeps rejection message rich without restructuring the graph"
  - "UI panels are pure render functions (not state mutations) — separation of display logic from graph state"

patterns-established:
  - "Dual-source tool pattern: single tool handles two input formats (SQLite DB + CSV file) via format detection"
  - "Clarify-then-finalize: confusion loop recovery without adding new terminal states"
  - "_TOOL_KEYWORD_MAP expansion: keyword hints for new tools reduce planner hallucination on unfamiliar tool names"

requirements-completed: []

# Metrics
duration: ~60min (estimated, outside GSD cycle)
completed: 2026-03-03
---

# Phase 4 Plan 07: Deterministic Tools + Clarify Action + UI Panels Summary

**Two new deterministic tools (372 tests, 21 new), clarify action for confusion-loop recovery, diagnostic injection into finish rejection, and three UI panels added to the CLI output — all outside the formal GSD cycle as Phase 4 post-completion improvements**

## Performance

- **Duration:** ~60 min (estimated)
- **Completed:** 2026-03-03
- **Tasks:** 5
- **Files created:** 4 (2 tools + 2 test files)
- **Files modified:** 5

## Accomplishments

- Added `parse_code_structure` tool: Python AST parser with regex fallback for non-Python files; extracts functions, classes, imports; registered in tools_registry; 13 unit tests
- Added `describe_db_schema` tool: SQLite PRAGMA + CSV header reader; returns structured schema metadata; registered in tools_registry; 8 unit tests
- Added `clarify` action type to schemas.py and wired `clarify_node → finalize` edge in graph.py — allows planner to break confusion loops by explicitly requesting clarification
- Added `_diagnose_incomplete_missions()` to graph.py, injected into both finish-rejection message paths — provides structured recovery context (which missions are incomplete, which tools are missing)
- Added three UI panels to run.py: `render_clarification_panel`, `render_context_warning_panel`, `render_stuck_indicator`
- Expanded `_TOOL_KEYWORD_MAP` in mission_parser.py with 9 new keyword hints for the new tools
- Total test count: 351 → 372 (21 new tests, all passing)
- ruff check src/ tests/ is clean

## Task Commits

Work performed outside the GSD commit cycle as incremental improvements after 04-06 completion. No single commit boundary per task.

## Files Created/Modified

**Created:**
- `src/agentic_workflows/tools/parse_code_structure.py` — AST + regex code structure analyzer
- `src/agentic_workflows/tools/describe_db_schema.py` — SQLite PRAGMA + CSV schema describer
- `tests/unit/test_parse_code_structure.py` — 13 unit tests
- `tests/unit/test_describe_db_schema.py` — 8 unit tests

**Modified:**
- `src/agentic_workflows/tools/tools_registry.py` — registered parse_code_structure, describe_db_schema
- `src/agentic_workflows/orchestration/langgraph/graph.py` — clarify_node added, _diagnose_incomplete_missions() added + injected
- `src/agentic_workflows/orchestration/langgraph/mission_parser.py` — _TOOL_KEYWORD_MAP expanded with 9 new hints
- `src/agentic_workflows/orchestration/langgraph/run.py` — 3 UI panels added
- `src/agentic_workflows/schemas.py` — "clarify" added as valid action type

## Decisions Made

- **parse_code_structure dual-mode:** AST for .py (correct, typed), regex for others (safe, no crash on non-Python syntax)
- **describe_db_schema dual-source:** single tool handles SQLite DB and CSV — most common agent data sources; format detected by file extension
- **clarify as distinct action type:** clean semantic separation from "finish" (done) and "error" (failed); clarify = "I need more context"
- **_diagnose_incomplete_missions() injected, not a new node:** minimal graph change; keeps rejection loop structure intact; provides rich diagnostic context without restructuring routing

## Deviations from Plan

None — this is a retrospective plan. All work was implemented directly without a prior PLAN.md.

## Issues Encountered

None. All 5 changes were incremental and non-breaking. Existing 351 tests continued to pass; 21 new tests added.

## Next Phase Readiness

- 372 tests pass
- 2 new deterministic tools available for mission assignment
- clarify action available for planner use in confusion-loop scenarios
- UI panels provide better operator visibility during runs
- Phase 5 (FastAPI / Langfuse) can proceed from a clean baseline

---
*Phase: 04-multi-agent-integration-and-model-routing*
*Completed: 2026-03-03*

## Self-Check: PASSED

- parse_code_structure.py: FOUND
- describe_db_schema.py: FOUND
- test_parse_code_structure.py: FOUND
- test_describe_db_schema.py: FOUND
- 04-07-PLAN.md: FOUND
- 04-07-SUMMARY.md: THIS FILE
