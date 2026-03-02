# ADR-003: Annotated[list[T], operator.add] Reducers for RunState List Fields

**Status:** Accepted
**Date:** 2026-03-02

## Context
`RunState` has four plain `list[T]` fields: `tool_history`, `mission_reports`, `memo_events`,
`seen_tool_signatures`. In LangGraph, when parallel branches (via `Send()`) converge, the
default merge behavior for non-annotated fields is last-writer-wins — meaning one branch's
records silently overwrite another's. Phase 4 will introduce parallel mission fan-out via
`Send()`. If reducers are not in place before then, the data loss will be silent and hard to diagnose.

## Decision
Add `Annotated[list[T], operator.add]` to all four list fields in `RunState`. This tells
LangGraph to concatenate (not replace) when parallel branches merge. `ensure_state_defaults()`
is NOT removed — it remains the repair function for missing keys, independent of reducer
annotations. All graph.py mutations of these fields are in-place appends (`state[field].append(...)`)
which do not go through the reducer; only dict-key returns go through it.

## Consequences
- Parallel Send() branches can be safely introduced in Phase 4 without data loss
- mypy may report warnings on `Annotated[list[T], operator.add]` because `operator.add` is
  `Callable`, not a type annotation — suppressed with `# type: ignore[misc]` if needed
- Node return values that include these fields as dict keys must return only the delta (new records),
  not the full accumulated list — audit confirms only one such occurrence in graph.py (line 227,
  in the run() result extraction, not a graph node return)
- All 208 existing sequential tests pass unchanged
