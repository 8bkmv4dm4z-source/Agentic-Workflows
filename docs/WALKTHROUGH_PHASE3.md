# Phase 3 Walkthrough: Specialist Subgraph Architecture

This document satisfies LRNG-01: every non-trivial refactor touching specialist
files must be accompanied by an explanation of what changed, why it was changed,
which LangGraph classes implement it, and how the subgraphs connect to the main
graph interface.

---

## What Changed

### Files Created

**`src/agentic_workflows/orchestration/langgraph/specialist_executor.py`** (NEW)

Defines `ExecutorState` — an 11-field `TypedDict` with `exec_`-prefixed list
fields to guarantee zero key overlap with `RunState`. Also defines
`build_executor_subgraph()`, a factory that compiles a single-node
`StateGraph(ExecutorState)` with a `START -> execute -> END` topology. The
`execute` node dispatches one tool call from `input_context`, records the result
in `exec_tool_history`, and returns `status="success"` or `status="error"`.

**`src/agentic_workflows/orchestration/langgraph/specialist_evaluator.py`** (NEW)

Defines `EvaluatorState` — a 10-field `TypedDict` with `eval_`-prefixed list
fields for RunState isolation. Also defines `build_evaluator_subgraph()`, a
no-parameter factory that compiles a single-node `StateGraph(EvaluatorState)`
with a `START -> evaluate -> END` topology. The `evaluate` node delegates to
`audit_run()` (from `mission_auditor.py`), remapping the `eval_`-prefixed field
names back to the bare kwarg names that `audit_run()` expects.

**`tests/unit/test_specialist_executor.py`** (NEW)

Five unit tests covering: exact field set assertion (11 fields), RunState
disjointness, successful `sort_array` invocation, `exec_tool_history` recording
after a call, and graceful `status=error` return for an unknown tool name.

**`tests/unit/test_specialist_evaluator.py`** (NEW)

Four unit tests covering: basic invocation returning `status=success`, standard
`AuditReport` keys present in `eval_audit_report`, empty-state graceful handling,
and exact field set assertion (10 fields).

**`tests/unit/test_state_isolation.py`** (NEW)

The primary ROADMAP acceptance gate. Four tests using `__annotations__` inspection
(not `get_type_hints()`) to assert: `ExecutorState` and `RunState` share zero
annotation keys; `EvaluatorState` and `RunState` share zero annotation keys;
`ExecutorState` has exactly the 11 required fields; `EvaluatorState` has exactly
the 10 required fields. On failure, each disjointness test prints the overlapping
key set so the collision is immediately identifiable.

### Files Modified

**`src/agentic_workflows/orchestration/langgraph/directives.py`**

Auto-fix (Rule 1 — pre-existing bug): added `"run_bash"` to the
`EXECUTOR_TOOLS` frozenset, which had fallen out of sync with `tools_registry.py`
after Phase 2 added `run_bash` to the registry. Fixed during Plan 03-01.

---

## Why

Phase 3 creates independently testable specialist units before Phase 4 wires them
into the main graph. The design rationale rests on three principles.

First, subgraphs that can be compiled and invoked in isolation are dramatically
easier to develop and debug than components embedded inside a 1700-line
orchestrator. A developer working on the executor tool-dispatch logic can write
unit tests, iterate on edge cases, and verify behavior using a six-line test
helper — without standing up the full `LangGraphOrchestrator`, loading all five
missions, or mocking the planning LLM.

Second, the `TypedDict` isolation boundary makes the input/output contract
explicit and static. Both `ExecutorState` and `EvaluatorState` define their
complete field sets at the class level. Any caller constructing the input dict
gets immediate type-checker feedback if a required field is missing or
wrongly typed. This explicit contract is the alternative to the implicit
"whatever keys the parent graph happens to have at this step" approach that
makes large graph systems brittle.

Third, Pattern A — calling a compiled subgraph inside a regular Python function
node — enables Phase 4 to invoke subgraphs from `_route_to_specialist()` without
requiring that the subgraph and the main graph share any state keys. Because
`ExecutorState` and `RunState` share zero keys (verified by
`test_state_isolation.py`), a thin wrapper function translates a `TaskHandoff`
dict into an `ExecutorState` dict, calls `build_executor_subgraph().invoke(...)`,
and maps the result back. LangGraph never "sees" the subgraph as a node in the
parent graph — it is just a Python callable — so the state merge issue does not
arise.

---

## Which LangGraph Classes Implement It

**`StateGraph`**

The graph builder class from `langgraph.graph`. Accepts a `TypedDict` class as
its state schema parameter: `StateGraph(ExecutorState)`. Every node function
receives and returns an instance of that TypedDict (which at runtime is a plain
`dict`). The schema parameter is used by LangGraph's type-checking and by the
reducer system when `Annotated` fields are present.

**`StateGraph.compile()`**

Returns a `CompiledStateGraph`. This is the object stored in memory and passed
around as the "subgraph". The `.invoke(state_dict)` method on
`CompiledStateGraph` is the primary call target in both unit tests and the
eventual Phase 4 wrapper.

**`START` and `END`**

Sentinel string constants from `langgraph.graph` used to wire entry and exit
edges. `builder.add_edge(START, "execute")` tells LangGraph which node runs
first; `builder.add_edge("execute", END)` terminates the graph after that node.
Both subgraphs use the simplest possible topology: `START -> single_node -> END`.

**`CompiledStateGraph.invoke(state_dict)`**

The method used in every unit test to drive the subgraph. Accepts a plain `dict`
matching the schema TypedDict. Returns a `dict` with the same shape populated by
the node function. Because LangGraph applies `dict.update()` semantics (with
reducer support for `Annotated` fields), the returned dict reflects all mutations
made by the node, including appends to `exec_tool_history`.

---

## How Subgraphs Connect to the Main Graph Interface

In Phase 3, both subgraphs are compiled and unit-tested in complete isolation.
They are **not** wired into `graph.py`. The `_route_to_specialist()` function in
`LangGraphOrchestrator` remains a pass-through stub that takes no action:

```python
def _route_to_specialist(self, handoff: TaskHandoff) -> HandoffResult:
    ...
    return HandoffResult(task_id=handoff["task_id"], result={}, status="skipped")
```

This is intentional. Phase 3 establishes the subgraph contracts and validates
isolation before any wiring creates the risk of silent RunState corruption.

**Phase 4 preview — how wiring will work:**

`_route_to_specialist()` will construct an `ExecutorState` or `EvaluatorState`
dict from the incoming `TaskHandoff`, call the appropriate compiled subgraph via
`.invoke()`, and map the result back to a `HandoffResult`. A sketch:

```python
from agentic_workflows.orchestration.langgraph.specialist_executor import (
    build_executor_subgraph,
)

def _route_to_specialist(self, handoff: TaskHandoff) -> HandoffResult:
    executor = build_executor_subgraph(
        tool_scope=handoff.get("tool_scope"),
        memo_store=self._memo_store,
    )
    exec_state = {
        "task_id": handoff["task_id"],
        "specialist": "executor",
        "mission_id": handoff.get("mission_id", 0),
        "tool_scope": handoff.get("tool_scope", []),
        "input_context": handoff.get("input_context", {}),
        "token_budget": handoff.get("token_budget", 4096),
    }
    result = executor.invoke(exec_state)
    return HandoffResult(
        task_id=handoff["task_id"],
        result=result.get("result", {}),
        status=result.get("status", "error"),
    )
```

Because `ExecutorState` and `RunState` share **no** keys, LangGraph cannot use
the `builder.add_node(compiled_subgraph)` shortcut (which would require the
subgraph to output a subset of RunState keys). The wrapper function pattern is
required. This constraint is why `test_state_isolation.py` is the primary ROADMAP
acceptance gate: it enforces that the wrapper-function pattern remains the only
valid integration approach, preventing an accidental "shortcut" that would
silently corrupt RunState fields.

---

## State Key Isolation

The field-name prefix convention is the central design choice of Phase 3. Fields
that would collide with `RunState` keys are renamed with a specialist prefix
before the TypedDict is finalized.

In `ExecutorState`, the two list fields that track execution history use the
`exec_` prefix:

- `exec_tool_history` (instead of `tool_history` which exists in `RunState`)
- `exec_seen_signatures` (instead of `seen_tool_signatures` — note the prefix
  is applied and the base name is also changed for clarity)

In `EvaluatorState`, five fields that mirror RunState audit and mission data use
the `eval_` prefix:

- `eval_mission_reports` (instead of `mission_reports`)
- `eval_tool_history` (instead of `tool_history`)
- `eval_missions` (instead of `missions`)
- `eval_mission_contracts` (instead of `mission_contracts`)
- `eval_audit_report` (instead of `audit_report`)

The five fields shared between both specialist states (`task_id`, `specialist`,
`mission_id`, `tokens_used`, `status`) appear in neither `RunState` nor the
other specialist state, so no prefix is needed for them.

The ROADMAP requires zero key overlap because LangGraph's state merge semantics
use key identity. When a subgraph is added as a node via
`builder.add_node(compiled_subgraph)`, LangGraph merges the subgraph's output
dict back into the parent state by key. An overlapping key — say `tool_history`
in both `RunState` and `ExecutorState` — would cause the executor's local
`exec_tool_history` to be silently discarded while the RunState's `tool_history`
was overwritten with whatever partial list the executor had accumulated. This
class of bug is invisible at compile time and produces non-deterministic behavior
at runtime, making it one of the most dangerous failure modes in a multi-agent
LangGraph system.

The prefix convention eliminates the overlap structurally. `test_state_isolation.py`
verifies it remains eliminated as the codebase evolves.

---

## References

- `.planning/phases/03-specialist-subgraph-architecture/03-CONTEXT.md` — Phase 3
  design decisions and pattern selection rationale
- `.planning/phases/03-specialist-subgraph-architecture/03-RESEARCH.md` —
  LangGraph subgraph documentation sources and Pattern A vs Pattern B comparison
- `src/agentic_workflows/orchestration/langgraph/handoff.py` — `TaskHandoff` and
  `HandoffResult` TypedDicts (unchanged in Phase 3)
- `src/agentic_workflows/orchestration/langgraph/state_schema.py` — `RunState`
  TypedDict (unchanged in Phase 3; 26 fields listed in annotations)
- `docs/ADR/` — Phase 2 architectural decision records (ADR-0001 through ADR-0004)
  for LangGraph upgrade context
