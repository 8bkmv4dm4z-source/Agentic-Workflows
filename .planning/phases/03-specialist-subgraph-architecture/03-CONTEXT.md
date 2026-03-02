# Phase 3: Specialist Subgraph Architecture - Context

**Gathered:** 2026-03-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Create `ExecutorState` and `EvaluatorState` TypedDicts in dedicated modules with no key overlap with `RunState`. Implement `build_executor_subgraph()` and `build_evaluator_subgraph()` functions that compile to independently runnable `StateGraph` instances — testable in isolation via `TaskHandoff` input / `HandoffResult` output. No routing from the main graph is wired in this phase; `_route_to_specialist` remains a pass-through. WALKTHROUGH updated for every file touched.

</domain>

<decisions>
## Implementation Decisions

### State Isolation Depth
- **Rich TypedDicts mirroring the directive input/output contracts** — not thin wrappers
- `ExecutorState` contains the fields the executor directive defines as input/output: `task_id`, `specialist`, `mission_id`, `tool_scope`, `input_context`, `token_budget`, `tool_history`, `seen_tool_signatures`, `result`, `tokens_used`, `status`
- `EvaluatorState` contains the evaluator directive's contract fields: `task_id`, `specialist`, `mission_id`, `mission_reports`, `tool_history`, `missions`, `mission_contracts`, `audit_report`, `tokens_used`, `status`
- Neither state inherits from `RunState` — overlap is intentional but each field is independently declared
- A unit test must assert `set(ExecutorState.__annotations__) & set(RunState.__annotations__) == set()` (and same for EvaluatorState)

### Tool Scope Enforcement
- **Strict enforcement in the executor subgraph** — only tools listed in `tool_scope` from the `TaskHandoff` are registered into the subgraph's `ToolNode`
- The existing `tools_registry.py` `build_tool_registry()` is reused; the subgraph filters by `tool_scope` before passing to `ToolNode`
- Rationale: makes the subgraph self-documenting and testable in isolation without needing the full 12-tool registry

### Subgraph Node Count
- **Minimal single-node design** for this phase — one `execute` node (executor) and one `evaluate` node (evaluator)
- Phase 3's goal is isolation + testability, not behavioral fidelity; multi-node refinement happens in Phase 4
- The single node calls the relevant logic directly (tool dispatch for executor, `audit_run()` for evaluator)
- This keeps the graph structure simple enough to verify in a unit test without mocking many inter-node transitions

### WALKTHROUGH Target
- **New standalone `docs/WALKTHROUGH_PHASE3.md`** — not appended to `P1_WALKTHROUGH.md`
- `P1_WALKTHROUGH.md` documents Phase 1 decisions; Phase 3 introduces a distinct architectural layer
- The Phase 3 WALKTHROUGH covers: what changed, why, which LangGraph classes implement it (StateGraph, ToolNode, tools_condition), and how the subgraphs connect to the main graph interface

### Claude's Discretion
- Exact TypedDict field ordering
- Node naming conventions inside the subgraphs
- Import structure between `specialist_executor.py`, `specialist_evaluator.py`, and `handoff.py`
- Test fixture design for the unit tests (mock vs real tool registry)
- Whether `build_executor_subgraph()` accepts `tool_scope` as a parameter or reads it from the initial state

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `handoff.py`: `TaskHandoff` / `HandoffResult` TypedDicts + `create_handoff()` / `create_handoff_result()` factories — use these as the subgraph entry/exit contract directly; no new types needed
- `tools_registry.py::build_tool_registry()` — reuse to get tool instances, then filter by `tool_scope`
- `model_router.py::ModelRouter` — stub exists, Anthropic path with `ToolNode` available after Phase 2
- `directives/executor.md` and `directives/evaluator.md` — detailed behavioral rules, use as spec for the node implementations

### Established Patterns
- `StateGraph` + `TypedDict` state is the project's LangGraph pattern (see `graph.py`)
- `ensure_state_defaults()` pattern from `state_schema.py` — apply the same repair-at-entry pattern in subgraph nodes
- `Annotated[list[T], operator.add]` reducers (added in Phase 2) must be used for any list fields in `ExecutorState` / `EvaluatorState` that could be written from multiple branches

### Integration Points
- `graph.py::_route_to_specialist` — currently a pass-through; Phase 3 does NOT change this; Phase 4 will wire it to call `build_executor_subgraph().invoke(handoff)`
- `state_schema.py::RunState` — `handoff_queue` and `handoff_results` fields already exist; Phase 3 does not modify these
- `tests/unit/` — new test files follow existing naming: `test_specialist_executor.py`, `test_specialist_evaluator.py`

</code_context>

<specifics>
## Specific Ideas

- The unit test for executor subgraph: create a `TaskHandoff` with `tool_scope=["sort_array"]`, invoke `build_executor_subgraph()`, pass it a handoff with a sort task in `input_context`, assert `HandoffResult` with `status="success"` and sorted output
- The unit test for evaluator subgraph: pass a minimal `TaskHandoff` with populated `mission_reports` in `input_context`, invoke, assert `HandoffResult` with `audit_report` populated
- State key overlap test: `assert set(ExecutorState.__annotations__).isdisjoint(set(RunState.__annotations__))` — the ROADMAP success criterion makes this the primary acceptance gate

</specifics>

<deferred>
## Deferred Ideas

- Wiring `_route_to_specialist` to actually invoke the subgraphs — Phase 4
- Multi-node subgraph refinement (supervisor→execute→record inside executor) — Phase 4
- Parallel mission `Send()` map-reduce using the specialist subgraphs — Phase 4
- Model routing into the subgraphs (strong vs fast provider) — Phase 4

</deferred>

---

*Phase: 03-specialist-subgraph-architecture*
*Context gathered: 2026-03-02*
