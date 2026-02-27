# Agent Instructions

> This file is mirrored across `CLAUDE.md`, `AGENTS.md`, and `GEMINI.md` so the same instructions load in any AI environment.

This repo follows the transition plan in `deep-research-report.md`: learn agent engineering by moving from a manual loop to framework orchestration, then toward production hardening.

## Mission and Phase Context

Primary mission:
- Build a reliable, stateful, tool-using agent stack with strict schemas, deterministic execution, and auditability.

Phase status (source of truth: `deep-research-report.md`):
- Completed: Phase 0 (`p0/` manual loop baseline)
- Completed: Phase 1 (`execution/langgraph/` LangGraph implementation + notebooks)
- Next: Phase 2 (rebuild hardened orchestrator components)
- Later: Phase 3 (production TypeScript infra)

Default targeting rule:
- Work on the highest implemented phase unless the user explicitly asks for a lower one.
- In this repo that means default to Phase 1 paths under `execution/langgraph/`.

## Start Here (Context Load Order)

When starting work, load context in this order:
1. `deep-research-report.md` (overall mission, roadmap, risk model)
2. `P1_WALKTHROUGH.md` (current Phase 1 architecture, known bugs, run guidance)
3. `directives/phase1_langgraph.md` (Phase 1 SOP)
4. `execution/langgraph/` code + `tests/test_langgraph_flow.py`

## Notebook-First Working Mode (Phase 1)

For walkthrough and learning tasks, follow the notebook path:
1. `execution/notebooks/phase1_langgraph_walkthrough.ipynb`
2. `execution/notebooks/p1_state_schema.ipynb`
3. `execution/notebooks/p1_provider.ipynb`
4. `execution/notebooks/p1_policy.ipynb`
5. `execution/notebooks/p1_memo_store.ipynb`
6. `execution/notebooks/p1_checkpoint_store.ipynb`
7. `execution/notebooks/p1_tools_registry.ipynb`
8. `execution/notebooks/p1_graph_orchestrator.ipynb`

Use notebooks for explainability and verification, but keep production logic in `execution/langgraph/*.py`.

## 3-Layer Architecture (Operating Model)

Layer 1: Directive (what to do)
- SOPs in `directives/`
- Defines goals, inputs, tools/scripts, outputs, and edge cases

Layer 2: Orchestration (decision-making)
- Read directives and route execution
- Handle retries, failures, recovery, and stop conditions
- Keep behavior aligned with phase goals and constraints

Layer 3: Execution (deterministic doing)
- Deterministic Python code in `execution/`
- Tool execution, persistence, data handling, and IO
- Env/config via `.env`

Why this matters:
- Keep probabilistic reasoning in orchestration.
- Push repeated logic and side effects into deterministic code.

## Working Rules

1. Check for existing tools first
- Before writing new code, inspect `execution/` and existing tools.

2. Self-anneal on failures
- Read stack traces and logs.
- Fix root cause, rerun, and verify.
- Capture learnings in SOP/walkthrough docs when requested.

3. Update docs with operational learnings
- `P1_WALKTHROUGH.md` is the active operational handoff for Phase 1.
- Add known failure modes, mitigations, and prompt guidance there.
- Do not create/overwrite directives without explicit user request.

4. Preserve phase isolation
- Keep Phase 0 legacy in `p0/`.
- Keep Phase 1 changes in `execution/langgraph/`, `tests/`, and docs.

5. Reliability defaults
- Enforce strict action schemas.
- Bound retries and fail closed when necessary.
- Keep duplicate-call protections and mission/task progress state explicit.

## Known Phase 1 Reality (Current)

- Provider/model outputs may violate JSON-only contracts (for example XML-ish tool-call envelopes).
- Mission progress can drift if planner ignores system feedback.
- Duplicate tool retries must be bounded and observable.

When this happens:
1. Capture logs and failing step.
2. Harden parser/policy/stop conditions in orchestrator code.
3. Add regression tests in `tests/test_langgraph_flow.py`.
4. Update `P1_WALKTHROUGH.md` with the bug and fix.

## File Organization

- `.tmp/`: intermediates and local stores (regenerable)
- `p0/`: legacy Phase 0 baseline
- `execution/`: deterministic implementation code
- `execution/langgraph/`: Phase 1 orchestration runtime
- `execution/notebooks/`: walkthrough notebooks
- `directives/`: SOPs
- `tests/`: automated tests
- `.env`: provider/config secrets

## Practical Commands

- Run Phase 1 demo:
  - `.venv/bin/python -m execution.langgraph.run`
- Run tests:
  - `.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q`

## Summary

Operate as an orchestration engineer:
- route intent through directives,
- execute deterministic code paths,
- harden reliability with tests and stop conditions,
- keep documentation synchronized with observed behavior.
