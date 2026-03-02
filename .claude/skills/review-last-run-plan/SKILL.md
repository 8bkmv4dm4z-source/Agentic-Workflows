---
name: review-last-run-plan
description: Review last-run artifacts and build a user-approvable, editable fix plan in plan mode. Use when the user asks to analyze lastRun.txt, validate failures across runs, confirm bug hypotheses, and produce a phased plan block before implementation.
---

# Review Last Run Plan

## Overview

Analyze run logs and output artifacts, then produce a decision-complete remediation plan that is explicitly presented for user approval and iteration. Keep this skill planning-focused; do not implement code changes while using it.

## Workflow

1. Gather context from:
- `lastRun.txt` (required)
- Current generated outputs (`fib50.txt`, `pattern_report.txt`, `users_sorted.txt`, `analysis_results.txt`) when present
- Current orchestration sources if needed for root-cause mapping:
`src/agentic_workflows/orchestration/langgraph/graph.py`,
`mission_parser.py`, `mission_tracker.py`, `mission_auditor.py`

2. Identify each run by `RUN START run_id=...` and extract:
- mission count
- step count
- timeout/fallback events
- planner outputs (`MODEL OUTPUT`, `PLAN QUEUED`, `PLAN QUEUE POP`, `PLANNED ACTION`)
- mission reports
- audit summary/findings
- cache/memo events

3. Evaluate and classify:
- mission execution correctness (PASS/WARN/FAIL)
- mission attribution correctness
- finish-claim correctness
- cache/memo correctness (including poisoning risk)

4. Validate explicit user hypotheses (example):
- first run failed due to planner timeout vs parser truncation
- rerun output correctness (file contents and acceptance criteria)

5. Build a plan, not code:
- define phases
- define acceptance criteria per phase
- define logging/observability additions required to verify fixes
- include approval gate before implementation/commit

## Plan-Mode Behavior

- If plan mode exists in the environment, stay in plan mode and output plan only.
- If plan mode does not exist, emulate plan mode behavior:
  - do analysis
  - produce only a `<proposed_plan>` block
  - request user edits/approval before implementation
- Treat the first plan as a draft that must remain editable by user feedback.

## Output Contract

Always return:

1. `LAST RUN REVIEW` summary:
- run-by-run findings
- hypothesis confirmations (`CONFIRMED` / `NOT CONFIRMED`)
- concrete log evidence (run ids + step numbers)

2. `<proposed_plan>`:
- title
- phases with sequencing
- exact files/components to change
- test/verification checklist
- approval gate (explicitly "wait for user approval before implementation")
- assumptions/defaults called out explicitly

3. `Open Questions / User Controls`:
- list only decisions that the user may want to override
- keep plan deterministic if user does not override

## Quality Rules

- Do not guess when evidence exists in logs/files; cite exact lines/steps.
- Distinguish "what happened" (evidence) from "why" (inference).
- Prioritize root-cause mapping over broad summaries.
- Keep scope on run review + planning; do not mutate code during this skill's execution.

## References

- Reuse the original review rubric at [references/review-last-run.md](references/review-last-run.md) for detailed mission checks and issue verification structure.
- Use [references/mission-rubric.md](references/mission-rubric.md) for compact expected mission outputs and acceptance hints.
