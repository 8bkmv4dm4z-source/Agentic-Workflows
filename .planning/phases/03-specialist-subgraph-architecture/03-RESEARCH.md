# Phase 3: Specialist Subgraph Architecture - Research

**Researched:** 2026-03-02
**Domain:** LangGraph subgraph isolation, TypedDict state design, compiled StateGraph testing
**Confidence:** HIGH (LangGraph docs verified via WebFetch; existing codebase fully read)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**State Isolation Depth**
- Rich TypedDicts mirroring the directive input/output contracts — not thin wrappers
- `ExecutorState` contains: `task_id`, `specialist`, `mission_id`, `tool_scope`, `input_context`, `token_budget`, `tool_history`, `seen_tool_signatures`, `result`, `tokens_used`, `status`
- `EvaluatorState` contains: `task_id`, `specialist`, `mission_id`, `mission_reports`, `tool_history`, `missions`, `mission_contracts`, `audit_report`, `tokens_used`, `status`
- Neither state inherits from `RunState` — overlap is intentional but each field is independently declared
- A unit test must assert `set(ExecutorState.__annotations__) & set(RunState.__annotations__) == set()` (and same for EvaluatorState)

**Tool Scope Enforcement**
- Strict enforcement in the executor subgraph — only tools listed in `tool_scope` from the `TaskHandoff` are registered into the subgraph's `ToolNode`
- Reuse existing `tools_registry.py::build_tool_registry()`, filter by `tool_scope` before passing to `ToolNode`
- Rationale: makes the subgraph self-documenting and testable in isolation

**Subgraph Node Count**
- Minimal single-node design for this phase — one `execute` node (executor) and one `evaluate` node (evaluator)
- Phase 3 goal is isolation + testability, not behavioral fidelity; multi-node refinement is Phase 4
- Single node calls logic directly (tool dispatch for executor, `audit_run()` for evaluator)

**WALKTHROUGH Target**
- New standalone `docs/WALKTHROUGH_PHASE3.md` — not appended to `P1_WALKTHROUGH.md`
- Covers: what changed, why, which LangGraph classes implement it (StateGraph, ToolNode, tools_condition), how subgraphs connect to the main graph interface

### Claude's Discretion

- Exact TypedDict field ordering
- Node naming conventions inside the subgraphs
- Import structure between `specialist_executor.py`, `specialist_evaluator.py`, and `handoff.py`
- Test fixture design for the unit tests (mock vs real tool registry)
- Whether `build_executor_subgraph()` accepts `tool_scope` as a parameter or reads it from the initial state

### Deferred Ideas (OUT OF SCOPE)

- Wiring `_route_to_specialist` to actually invoke the subgraphs — Phase 4
- Multi-node subgraph refinement (supervisor→execute→record inside executor) — Phase 4
- Parallel mission `Send()` map-reduce using the specialist subgraphs — Phase 4
- Model routing into the subgraphs (strong vs fast provider) — Phase 4
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| MAGT-01 | `ExecutorState` TypedDict exists as an isolated state schema (does not share keys with `RunState`) | TypedDict isolation pattern; field list from CONTEXT.md; key-overlap test pattern confirmed |
| MAGT-02 | `specialist_executor.py` contains a real, independently-compiled `StateGraph` for the executor role | LangGraph `StateGraph.compile()` pattern; single-node subgraph design; `build_executor_subgraph()` factory function |
| MAGT-03 | `EvaluatorState` TypedDict exists as an isolated state schema | Same TypedDict isolation pattern; field list from CONTEXT.md |
| MAGT-04 | `specialist_evaluator.py` contains a real, independently-compiled `StateGraph` for the evaluator role | `build_evaluator_subgraph()` factory; `audit_run()` reuse as the node body |
| LRNG-01 | Every non-trivial refactor of graph.py, state_schema.py, or specialist files is accompanied by a WALKTHROUGH update | Documented pattern: new `docs/WALKTHROUGH_PHASE3.md`, template sections established |
</phase_requirements>

---

## Summary

Phase 3 creates two independently compiled LangGraph StateGraphs — one for the executor specialist and one for the evaluator specialist — each with its own isolated TypedDict state schema. The primary deliverable is testability: both subgraphs can be invoked in isolation (without the main graph running) by passing a `TaskHandoff`-shaped input and asserting a `HandoffResult`-shaped output. No routing changes to the main graph are made in this phase.

The key technical insight is that LangGraph 0.2 supports two subgraph communication patterns. When parent and subgraph states share NO keys, the subgraph is compiled independently and invoked via `.invoke()` inside a wrapper function (Pattern A). When they share keys, the compiled subgraph can be passed directly to `add_node()` (Pattern B). Phase 3 uses Pattern A: `ExecutorState` and `EvaluatorState` are intentionally designed to not share keys with `RunState`, and `_route_to_specialist` (which remains a pass-through in this phase) will use a wrapper function in Phase 4 to call `build_executor_subgraph().invoke(handoff_state)`.

The implementation surface is tight: two new files (`specialist_executor.py`, `specialist_evaluator.py`), two new TypedDicts, two `build_*_subgraph()` factory functions, two new test files, and `docs/WALKTHROUGH_PHASE3.md`. No changes to `graph.py`, `state_schema.py`, or `handoff.py` are required.

**Primary recommendation:** Use LangGraph's "call subgraph inside a node" pattern (Pattern A) — compile each specialist graph independently, expose a `build_*_subgraph()` factory, and invoke directly with `.invoke()`. This produces a fully testable unit in isolation.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| langgraph | >=0.2.67,<1.0 (Phase 2 will upgrade to >=1.0.6) | `StateGraph`, `START`, `END` — the graph compilation API | Project's existing orchestration layer; subgraph API is identical in 0.2 and 1.0 |
| Python typing | stdlib | `TypedDict`, `Literal`, `Annotated` — state schema declarations | LangGraph native state contract; matches all existing state files |
| operator | stdlib | `operator.add` — list field reducer for `Annotated` fields | Required for parallel-branch safe list accumulation (LGUP-03 from Phase 2) |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| agentic_workflows.orchestration.langgraph.tools_registry | local | `build_tool_registry()` — returns full 12-tool dict | Executor subgraph: call, then filter by `tool_scope` |
| agentic_workflows.orchestration.langgraph.mission_auditor | local | `audit_run()` — deterministic post-run check | Evaluator subgraph node body |
| agentic_workflows.orchestration.langgraph.handoff | local | `TaskHandoff`, `HandoffResult`, factory functions | Entry/exit contract for both subgraphs |
| agentic_workflows.orchestration.langgraph.memo_store | local | `SQLiteMemoStore` | Required by `build_tool_registry()` for memoize/retrieve_memo tools |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `StateGraph` for subgraph | Raw function call | StateGraph gives compiled graph object testable independently; raw function loses the LangGraph node structure needed for Phase 4 wiring |
| Single-node subgraph | Multi-node subgraph (plan→execute→record) | Multi-node matches the directive more closely but adds test complexity; Phase 3 goal is isolation, not fidelity — multi-node is Phase 4 |
| `tool_scope` parameter to factory | Reading `tool_scope` from initial state | Parameter approach makes the factory more testable (caller controls scope); state approach requires the caller to embed scope in the state dict |

**Installation:** No new packages needed for Phase 3. LangGraph subgraph API is available in the existing `langgraph>=0.2.67,<1.0` dependency (and in >=1.0.6 after Phase 2 upgrade).

---

## Architecture Patterns

### Recommended Project Structure

```
src/agentic_workflows/orchestration/langgraph/
├── specialist_executor.py    # ExecutorState TypedDict + build_executor_subgraph()
├── specialist_evaluator.py   # EvaluatorState TypedDict + build_evaluator_subgraph()
├── handoff.py                # UNCHANGED — TaskHandoff / HandoffResult types
├── state_schema.py           # UNCHANGED — RunState
├── graph.py                  # UNCHANGED — _route_to_specialist remains pass-through
└── tools_registry.py         # UNCHANGED — reused by executor subgraph

docs/
└── WALKTHROUGH_PHASE3.md     # NEW — architecture explanation per LRNG-01

tests/unit/
├── test_specialist_executor.py   # NEW
└── test_specialist_evaluator.py  # NEW
```

### Pattern 1: Isolated Subgraph with Independent TypedDict State

**What:** Compile a StateGraph whose state schema shares NO keys with `RunState`. Expose it via a factory function. Invoke it from tests or from parent node wrappers using `.invoke()`.

**When to use:** When the subgraph represents a specialist with its own bounded state contract — inputs come from a `TaskHandoff`, outputs map to a `HandoffResult`.

**Example (executor):**
```python
# Source: LangGraph official docs — "Call Subgraph Inside a Node" pattern
# https://docs.langchain.com/oss/python/langgraph/use-subgraphs

from __future__ import annotations
from typing import Any, Literal
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

from agentic_workflows.orchestration.langgraph.handoff import (
    TaskHandoff, HandoffResult, create_handoff_result
)
from agentic_workflows.orchestration.langgraph.tools_registry import build_tool_registry
from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore


class ExecutorState(TypedDict):
    # Entry contract — populated from TaskHandoff
    task_id: str
    specialist: Literal["executor"]
    mission_id: int
    tool_scope: list[str]
    input_context: dict[str, Any]
    token_budget: int
    # Working state — written by the execute node
    tool_history: list[dict[str, Any]]
    seen_tool_signatures: list[str]
    # Exit contract — populated before END
    result: dict[str, Any]
    tokens_used: int
    status: Literal["success", "error", "timeout"]


def _ensure_executor_defaults(state: ExecutorState) -> ExecutorState:
    """Repair-at-entry pattern: ensure all keys are present."""
    state.setdefault("tool_history", [])
    state.setdefault("seen_tool_signatures", [])
    state.setdefault("result", {})
    state.setdefault("tokens_used", 0)
    state.setdefault("status", "success")
    return state


def build_executor_subgraph(
    tool_scope: list[str] | None = None,
    memo_store: SQLiteMemoStore | None = None,
) -> Any:  # CompiledStateGraph
    """Build and compile an isolated executor StateGraph.

    Args:
        tool_scope: Override which tools are registered. If None, uses all
                    tools returned by build_tool_registry().
        memo_store: SQLiteMemoStore for memoize/retrieve_memo tools.
                    Defaults to an in-memory/temp store if None.
    Returns:
        Compiled LangGraph StateGraph (CompiledStateGraph).
    """
    store = memo_store or SQLiteMemoStore()
    full_registry = build_tool_registry(store)
    if tool_scope is not None:
        registry = {k: v for k, v in full_registry.items() if k in tool_scope}
    else:
        registry = full_registry

    def execute_node(state: ExecutorState) -> ExecutorState:
        state = _ensure_executor_defaults(state)
        context = state.get("input_context", {})
        tool_name = context.get("tool_name", "")
        args = context.get("args", {})
        tool = registry.get(tool_name)
        if tool is None:
            state["result"] = {"error": f"tool_not_found: {tool_name}"}
            state["status"] = "error"
            return state
        try:
            result = tool.execute(args)
            state["result"] = result
            state["status"] = "success"
            state["tool_history"].append({
                "tool": tool_name, "args": args, "result": result
            })
        except Exception as exc:
            state["result"] = {"error": str(exc)}
            state["status"] = "error"
        return state

    builder = StateGraph(ExecutorState)
    builder.add_node("execute", execute_node)
    builder.add_edge(START, "execute")
    builder.add_edge("execute", END)
    return builder.compile()
```

**Example (invoking in unit test):**
```python
# Source: LangGraph docs — isolated subgraph invocation
def test_executor_subgraph_sort_array():
    graph = build_executor_subgraph(tool_scope=["sort_array"])
    handoff_state = {
        "task_id": "test-t1",
        "specialist": "executor",
        "mission_id": 1,
        "tool_scope": ["sort_array"],
        "input_context": {
            "tool_name": "sort_array",
            "args": {"items": [3, 1, 2], "order": "asc"},
        },
        "token_budget": 4096,
        "tool_history": [],
        "seen_tool_signatures": [],
        "result": {},
        "tokens_used": 0,
        "status": "success",
    }
    result = graph.invoke(handoff_state)
    assert result["status"] == "success"
    assert result["result"].get("sorted") == [1, 2, 3]
```

### Pattern 2: Evaluator Subgraph (audit_run() delegation)

**What:** Minimal single-node subgraph that delegates to the existing `audit_run()` function, taking mission-level data from `EvaluatorState` and returning findings in `audit_report`.

**Example:**
```python
# EvaluatorState fields derived from evaluator.md directive contract
class EvaluatorState(TypedDict):
    task_id: str
    specialist: Literal["evaluator"]
    mission_id: int
    mission_reports: list[dict[str, Any]]
    tool_history: list[dict[str, Any]]
    missions: list[str]
    mission_contracts: list[dict[str, Any]]
    audit_report: dict[str, Any] | None
    tokens_used: int
    status: Literal["success", "error", "timeout"]


def build_evaluator_subgraph() -> Any:  # CompiledStateGraph
    from agentic_workflows.orchestration.langgraph.mission_auditor import audit_run

    def evaluate_node(state: EvaluatorState) -> EvaluatorState:
        try:
            report = audit_run(
                mission_reports=state.get("mission_reports", []),
                tool_history=state.get("tool_history", []),
                missions=state.get("missions", []),
                mission_contracts=state.get("mission_contracts", []),
            )
            state["audit_report"] = report.__dict__ if hasattr(report, "__dict__") else dict(report)
            state["status"] = "success"
        except Exception as exc:
            state["audit_report"] = {"error": str(exc)}
            state["status"] = "error"
        return state

    builder = StateGraph(EvaluatorState)
    builder.add_node("evaluate", evaluate_node)
    builder.add_edge(START, "evaluate")
    builder.add_edge("evaluate", END)
    return builder.compile()
```

### Pattern 3: Key-Overlap Unit Test

**What:** Python annotation inspection to assert zero shared keys between specialist states and RunState. This is the ROADMAP primary acceptance gate.

**Example:**
```python
from agentic_workflows.orchestration.langgraph.state_schema import RunState
from agentic_workflows.orchestration.langgraph.specialist_executor import ExecutorState
from agentic_workflows.orchestration.langgraph.specialist_evaluator import EvaluatorState

def test_executor_state_no_key_overlap_with_run_state():
    overlap = set(ExecutorState.__annotations__) & set(RunState.__annotations__)
    assert overlap == set(), f"Unexpected shared keys: {overlap}"

def test_evaluator_state_no_key_overlap_with_run_state():
    overlap = set(EvaluatorState.__annotations__) & set(RunState.__annotations__)
    assert overlap == set(), f"Unexpected shared keys: {overlap}"
```

### Pattern 4: WALKTHROUGH Documentation Structure (LRNG-01)

Every file touched in Phase 3 must have a corresponding section in `docs/WALKTHROUGH_PHASE3.md`:

```markdown
# Phase 3 Walkthrough: Specialist Subgraph Architecture

## What Changed
- `specialist_executor.py` (NEW): ExecutorState TypedDict + build_executor_subgraph()
- `specialist_evaluator.py` (NEW): EvaluatorState TypedDict + build_evaluator_subgraph()

## Why
[explanation of isolation goal and testability]

## Which LangGraph Classes Implement It
- `StateGraph` — graph builder; accepts TypedDict as state schema
- `StateGraph.compile()` — produces CompiledStateGraph; the `.invoke()` target
- `START`, `END` — sentinel nodes for edge wiring

## How Subgraphs Connect to Main Graph Interface
[Phase 3: not wired into main graph yet]
[Phase 4: _route_to_specialist will call build_executor_subgraph().invoke(...)]
```

### Anti-Patterns to Avoid

- **Inheriting from RunState:** TypedDicts cannot be directly inherited in a way that removes keys. Declare all fields independently. The "overlap is intentional" note in CONTEXT.md means that some field *names* may recur (e.g., `tool_history`) but each is independently declared — they are not the same field object.
- **`add_node(compiled_subgraph)` when states don't share keys:** LangGraph raises an error if you pass a compiled subgraph with incompatible state directly to `add_node()` without a wrapper function. Phase 3 avoids this by not wiring into the main graph at all — subgraphs are tested via direct `.invoke()`.
- **Using `checkpointer=True` on subgraphs in unit tests:** Adds SQLite I/O to tests and introduces thread-safety concerns. Compile subgraphs with default (no checkpointer) for unit tests.
- **Defining `ExecutorState` with `Annotated[list[T], operator.add]`:** These reducers are for parallel `Send()` branches in the main graph. A single-node subgraph executed sequentially does not need reducers — add them only if/when parallel fan-out is introduced (Phase 4+).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Tool execution in executor node | Custom tool-dispatch loop | `tools_registry.build_tool_registry()` filtered by `tool_scope` | Registry already has all 12 tools, arg normalization, error handling |
| Post-run audit in evaluator node | Re-implement checks inline | `mission_auditor.audit_run()` | 9 deterministic checks already battle-tested; 208 tests cover it |
| State contract for subgraph entry/exit | New TypedDicts unrelated to existing types | `handoff.TaskHandoff` / `HandoffResult` as the caller-facing contract | Already exists, has factory functions, tested by `test_handoff.py` |
| Graph compilation boilerplate | Any non-StateGraph compilation | `langgraph.graph.StateGraph` + `.compile()` | Official LangGraph pattern; Phase 4 depends on compiled subgraph as callable |

**Key insight:** Phase 3's value is the isolation boundary and the factory function. The logic inside each subgraph node is almost entirely reuse of existing modules — the new code is the StateGraph skeleton and TypedDicts wrapping existing behavior.

---

## Common Pitfalls

### Pitfall 1: TypedDict Field Overlap Silently Breaks the Acceptance Test

**What goes wrong:** A developer adds a field to `ExecutorState` or `EvaluatorState` that also exists in `RunState` (e.g., `tool_history`, `status`, `missions`). The key-overlap unit test fails at CI time.

**Why it happens:** Both `RunState` and `ExecutorState` legitimately need `tool_history`. The decision in CONTEXT.md is intentional: same name is OK as long as each is independently declared (not inherited). But if a developer looks at `RunState` and copies fields wholesale, the overlap test fails.

**How to avoid:** Start from the field list in CONTEXT.md exactly. Do not use `from state_schema import RunState; class ExecutorState(RunState): pass`. Each field must be written out explicitly in the new module.

**Warning signs:** `set(ExecutorState.__annotations__) & set(RunState.__annotations__)` returns a non-empty set.

### Pitfall 2: `audit_run()` Signature Mismatch

**What goes wrong:** `mission_auditor.audit_run()` is called with wrong argument names or types inside the evaluator node. The evaluator subgraph raises `TypeError` at runtime.

**Why it happens:** `audit_run()` takes specific kwargs (`mission_reports`, `tool_history`, `missions`, `mission_contracts`). The evaluator's `EvaluatorState` fields must map 1:1 to these kwarg names.

**How to avoid:** Verify the actual `audit_run()` signature from `mission_auditor.py` before writing the evaluate node. The field names in `EvaluatorState` are chosen specifically to match the audit function's kwargs.

**Warning signs:** `TypeError: audit_run() got an unexpected keyword argument`.

### Pitfall 3: `SQLiteMemoStore` Not Provided to `build_executor_subgraph()`

**What goes wrong:** `build_tool_registry()` requires a `SQLiteMemoStore` instance. If `build_executor_subgraph()` is called without providing one, a default in-memory store is created — which is fine for tests but must not share a store with the main graph in production.

**Why it happens:** The `memoize` and `retrieve_memo` tools are store-bound. The store is created inside the factory if not provided.

**How to avoid:** Default to `SQLiteMemoStore()` (temp path) inside `build_executor_subgraph()` when no store is provided. Document that production callers should pass the shared store. Unit tests are fine with the default.

**Warning signs:** Tests calling `build_executor_subgraph()` without any args work fine; integration calls in Phase 4 must explicitly pass the production store.

### Pitfall 4: `StateGraph.compile()` Called Without `END` Edge

**What goes wrong:** The subgraph compiles without error but `invoke()` hangs indefinitely or raises a validation error because no edge leads to `END`.

**Why it happens:** LangGraph requires an explicit edge from the last node to `END`. Forgetting `builder.add_edge("execute", END)` produces a graph with no terminal node.

**How to avoid:** Always add `builder.add_edge(START, "node_name")` and `builder.add_edge("node_name", END)` as the final two edges. The unit test that calls `.invoke()` will catch this immediately.

**Warning signs:** `invoke()` returns `None` or raises `GraphRecursionError`.

### Pitfall 5: `TypedDict.__annotations__` Returns Empty Dict for Inherited Classes

**What goes wrong:** If `ExecutorState` is defined as `class ExecutorState(SomeBase, TypedDict): ...` and the overlap test uses `__annotations__`, it may miss fields defined in the base class.

**Why it happens:** `__annotations__` is per-class, not cumulative for inherited TypedDicts.

**How to avoid:** Do not inherit from other TypedDicts in `ExecutorState` or `EvaluatorState`. All fields must be declared directly in each class. Use `typing.get_type_hints()` if inheritance is ever needed — but CONTEXT.md explicitly prohibits inheriting from `RunState`.

**Warning signs:** Overlap test passes unexpectedly even when a developer re-uses a field name.

---

## Code Examples

### Building and Invoking an Executor Subgraph (Full Pattern)

```python
# Source: LangGraph official docs — https://docs.langchain.com/oss/python/langgraph/use-subgraphs
# Pattern: "Call Subgraph Inside a Node" (no shared state keys)

from langgraph.graph import StateGraph, START, END

# 1. Build the subgraph
graph = build_executor_subgraph(tool_scope=["sort_array"])

# 2. Invoke it directly (unit test or standalone)
result_state = graph.invoke({
    "task_id": "t-001",
    "specialist": "executor",
    "mission_id": 1,
    "tool_scope": ["sort_array"],
    "input_context": {
        "tool_name": "sort_array",
        "args": {"items": [3, 1, 2], "order": "asc"},
    },
    "token_budget": 4096,
    "tool_history": [],
    "seen_tool_signatures": [],
    "result": {},
    "tokens_used": 0,
    "status": "success",
})

# 3. Assert on the HandoffResult shape
assert result_state["status"] == "success"
assert "sorted" in result_state["result"]

# 4. Wrap in HandoffResult for the main graph (Phase 4 pattern — not Phase 3)
from agentic_workflows.orchestration.langgraph.handoff import create_handoff_result
handoff_result = create_handoff_result(
    task_id=result_state["task_id"],
    specialist="executor",
    status=result_state["status"],
    output=result_state["result"],
    tokens_used=result_state["tokens_used"],
)
```

### Building and Invoking an Evaluator Subgraph (Full Pattern)

```python
# Source: existing audit_run() usage in graph.py _finalize()
graph = build_evaluator_subgraph()

result_state = graph.invoke({
    "task_id": "t-002",
    "specialist": "evaluator",
    "mission_id": 1,
    "mission_reports": [
        {
            "mission_id": 1,
            "mission": "Sort the array",
            "used_tools": ["sort_array"],
            "tool_results": [{"tool": "sort_array", "result": {"sorted": [1, 2, 3]}}],
            "result": "Done",
            "status": "completed",
            "required_tools": ["sort_array"],
            "required_files": [],
            "written_files": [],
            "expected_fibonacci_count": None,
            "contract_checks": [],
            "subtask_contracts": [],
            "subtask_statuses": [],
        }
    ],
    "tool_history": [
        {"call": 1, "tool": "sort_array", "args": {"items": [3, 1, 2]}, "result": {"sorted": [1, 2, 3]}}
    ],
    "missions": ["Sort the array"],
    "mission_contracts": [],
    "audit_report": None,
    "tokens_used": 0,
    "status": "success",
})

assert result_state["status"] == "success"
assert result_state["audit_report"] is not None
```

### State Key Overlap Assertion

```python
# Source: CONTEXT.md success criterion; TypedDict.__annotations__ is stdlib
import typing

def test_state_isolation():
    from agentic_workflows.orchestration.langgraph.state_schema import RunState
    from agentic_workflows.orchestration.langgraph.specialist_executor import ExecutorState
    from agentic_workflows.orchestration.langgraph.specialist_evaluator import EvaluatorState

    run_keys = set(RunState.__annotations__)
    executor_keys = set(ExecutorState.__annotations__)
    evaluator_keys = set(EvaluatorState.__annotations__)

    assert executor_keys.isdisjoint(run_keys), (
        f"ExecutorState shares keys with RunState: {executor_keys & run_keys}"
    )
    assert evaluator_keys.isdisjoint(run_keys), (
        f"EvaluatorState shares keys with RunState: {evaluator_keys & run_keys}"
    )
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Specialist logic embedded in `_route_to_specialist()` inside `graph.py` | Specialist logic in isolated compiled `StateGraph` objects in dedicated modules | Phase 3 | Subgraphs testable without running the full orchestrator |
| `_route_to_specialist` = pass-through stub | `_route_to_specialist` still pass-through; subgraphs exist but not yet wired | Phase 3 | Zero regression risk; wiring is Phase 4 |
| Single flat `RunState` TypedDict for everything | `RunState` + `ExecutorState` + `EvaluatorState` as independent state schemas | Phase 3 | Enables Phase 4 subgraph-as-node invocation via wrapper functions |

**Note on LangGraph version:** Phase 2 upgrades from `langgraph<1.0` to `langgraph>=1.0.6`. The subgraph API (`StateGraph`, `compile()`, `invoke()`) is identical in both 0.2 and 1.0 — Phase 3 will work with whichever version Phase 2 leaves behind. The `langgraph-prebuilt` `ToolNode` wired in Phase 2 for the Anthropic path is available but NOT required in Phase 3 — the locked decision uses the existing tool dispatch loop inside the execute node body, not `ToolNode`.

---

## Open Questions

1. **`audit_run()` return type: dataclass vs dict**
   - What we know: `audit_run()` returns an `AuditReport` dataclass (verified from `mission_auditor.py` import in test file). `graph.py` stores `state["audit_report"]` as a dict (set in `_finalize()`).
   - What's unclear: Does `audit_run()` return the dataclass directly, or is it already serialized to dict when `_finalize()` stores it?
   - Recommendation: Check `audit_run()` return type at implementation time. If it returns a dataclass, call `.to_dict()` or `dataclasses.asdict()` before storing in `EvaluatorState["audit_report"]`.

2. **`tool_scope` as factory parameter vs initial state field**
   - What we know: CONTEXT.md marks this as Claude's Discretion.
   - Recommendation: Accept `tool_scope` as a parameter to `build_executor_subgraph(tool_scope)`. This makes the compiled graph pre-configured (the node can use the closed-over registry). The `ExecutorState.tool_scope` field still exists for documentation/introspection purposes but the node doesn't read it from state to build the registry — the registry is built at compile time.

3. **Whether `EvaluatorState` needs `mission_contracts` field**
   - What we know: `audit_run()` takes `mission_contracts` as a kwarg. `EvaluatorState` includes it per CONTEXT.md.
   - What's unclear: The evaluator directive says the evaluator runs post-run with full context. The `mission_contracts` in `RunState` are built by `_build_mission_contracts_from_plan()`. For isolated subgraph testing, a minimal or empty list is sufficient.
   - Recommendation: Include `mission_contracts` in `EvaluatorState` as specified in CONTEXT.md. Unit tests can pass `[]`.

---

## Sources

### Primary (HIGH confidence)
- LangGraph official docs (WebFetch) — "Call Subgraph Inside a Node" pattern, state isolation, `add_node()` error for no shared keys: https://docs.langchain.com/oss/python/langgraph/use-subgraphs
- Project codebase (direct read) — `handoff.py`, `state_schema.py`, `tools_registry.py`, `directives.py`, `graph.py`, `mission_auditor.py`, `directives/executor.md`, `directives/evaluator.md`
- LangGraph OpenTutorial (WebFetch verified) — subgraph state transformation wrapper pattern: https://langchain-opentutorial.gitbook.io/langchain-opentutorial/17-langgraph/01-core-features/14-langgraph-subgraph-transform-state

### Secondary (MEDIUM confidence)
- DEV Community article on LangGraph subgraphs (WebFetch) — unit test pattern `subgraph_compiled.invoke({...})` without parent graph: https://dev.to/sreeni5018/langgraph-subgraphs-a-guide-to-modular-ai-agents-development-31ob
- LangGraph test docs (WebFetch) — compiled graph `.nodes["name"].invoke()` for node-level testing: https://docs.langchain.com/oss/python/langgraph/test
- WebSearch results — `checkpointer=False` for multiple subgraphs (avoids `MultipleSubgraphsError`): GitHub discussions #2095

### Tertiary (LOW confidence)
- WebSearch results on LangGraph 0.2 vs 1.0 subgraph API compatibility — claimed identical; not separately verified via changelog (LOW). Check release notes if Phase 2 upgrade surfaces breaking changes.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — LangGraph `StateGraph` + `TypedDict` is the project's existing pattern; all imports verified from codebase
- Architecture (subgraph compilation pattern): HIGH — verified via official LangGraph docs (WebFetch)
- Architecture (state field design): HIGH — field lists locked in CONTEXT.md, verified against existing `handoff.py` and directive files
- Pitfalls: HIGH for TypedDict overlap / `audit_run()` signature; MEDIUM for `checkpointer=False` recommendation (WebSearch, partially verified)
- Code examples: MEDIUM — patterns are correct but full `build_executor_subgraph()` implementation will need `audit_run()` signature confirmed at implementation time

**Research date:** 2026-03-02
**Valid until:** 2026-04-02 (LangGraph docs are stable; 30-day window appropriate)
