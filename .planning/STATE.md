# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-02)

**Core value:** A specialist-routing multi-agent system that reliably executes multi-mission workloads end-to-end — with the architecture understood deeply enough to stress test, evolve, and deploy with confidence.
**Current focus:** Phase 2 — LangGraph Upgrade and Single-Agent Hardening

## Current Position

Phase: 2 of 7 (LangGraph Upgrade and Single-Agent Hardening)
Plan: 5 of TBD in current phase (02-05 complete)
Status: In progress
Last activity: 2026-03-03 — Plan 02-05 complete: GitHub Actions CI workflow with ruff/mypy/pytest, ScriptedProvider, no live API keys

Progress: [███░░░░░░░] 15% (Phase 1 complete, Phase 2 plans 01-05 done)

## Performance Metrics

**Velocity:**
- Total plans completed: 5
- Average duration: 4 min
- Total execution time: ~0.20 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 02-langgraph-upgrade | 5 | 20 min | 4 min |

**Recent Trend:**
- Last 5 plans: 02-01 (3 min), 02-02 (7 min), 02-03 (N/A), 02-04 (N/A), 02-05 (3 min)
- Trend: Stable

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Foundation]: langgraph<1.0 pin was safe when set; now blocks Phase 2 — flagged for revisit
- [Foundation]: TypedDict for RunState (not Pydantic BaseModel) — LangGraph native; repair via ensure_state_defaults()
- [Foundation]: tool_history is source of truth for args; tool_results in mission_reports intentionally excludes args
- [Roadmap]: LRNG-01 (WALKTHROUGH requirement) mapped to Phase 3 — first major refactor phase; process carries forward to all subsequent phases
- [02-01]: langgraph-prebuilt pin changed from <1.0.2 to >=1.0.6,<1.1.0 — plan's <1.0.2 was pip-unresolvable with langgraph>=1.0.6; codebase doesn't use ToolNode.afunc yet so safe
- [02-01]: Installed langgraph 1.0.10, langgraph-prebuilt 1.0.8, langchain-anthropic 1.3.4; test suite confirmed at 267 (grew from 208 during Phase 1)
- [02-02]: Annotated[list[T], operator.add] reducers added to 4 RunState list fields; _sequential_node() wrapper needed in graph.py because operator.add doubles lists when nodes return full state — LangGraph 1.0 applies reducer to returned dict even for full-state returns; wrapper zeroes Annotated fields in return dict (operator.add(post_mutation_list, []) = no-op)
- [02-02]: Message compaction added to ensure_state_defaults() — sliding window at P1_MESSAGE_COMPACTION_THRESHOLD (default 40), system messages always preserved
- [02-04]: @observe(name="run") applied to main() in run.py — main() is the CLI entrypoint; graph.py orchestrator.run() already had @observe separately; closes OBSV-02
- [02-04]: docs/ADR/ established with 4 ADRs (Status/Context/Decision/Consequences format) for Phase 2 key decisions — LRNG-02 closed
- [02-05]: CI workflow uses P1_PROVIDER=scripted in env block — ScriptedProvider handles all LLM interaction, zero live API keys in CI
- [02-05]: branches: ["**"] on push catches all feature branches; no pip cache (deferred to Phase 7)

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 2 entry]: ~~langgraph<1.0 pin must be removed~~ RESOLVED — langgraph 1.0.10 installed (02-01 complete)
- [Phase 2]: Verify ToolNode.afunc behavior with langgraph-prebuilt 1.0.8 when wiring in Plan 03 (plan originally warned about 1.0.2 break)
- [Phase 2]: ~~@observe() not yet wired on run/provider path~~ RESOLVED — @observe(name="run") on main() in run.py (02-04 complete)
- [Phase 3]: ~~RunState reducer annotations must be complete before any Send()-based parallel execution is attempted~~ RESOLVED — Annotated reducers added in 02-02 with _sequential_node() wrapper for safe sequential operation

## Session Continuity

Last session: 2026-03-02
Stopped at: Plan 02-04 complete — @observe(name="run") on run.py main(), docs/ADR/ with 4 ADRs, 277 tests green
Resume file: None
