# Phase 4: Multi-Agent Integration and Model Routing - Context

**Gathered:** 2026-03-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire `_route_to_specialist()` in `graph.py` to invoke real compiled specialist subgraphs via the wrapper-function pattern. Merge `HandoffResult` outputs back into `RunState` correctly. Ensure multi-mission runs preserve all results. Implement real model routing decisions. No FastAPI, no Langfuse CallbackHandler (Phase 5), no parallel `Send()` fan-out (deferred).

</domain>

<decisions>
## Implementation Decisions

### Subgraph Invocation Pattern
- **Wrapper-function pattern** — as specified in `docs/WALKTHROUGH_PHASE3.md` Phase 4 preview
- `_route_to_specialist()` constructs `ExecutorState` or `EvaluatorState` from the incoming `TaskHandoff`, calls `build_executor_subgraph().invoke(exec_state)` or `build_evaluator_subgraph().invoke(eval_state)`, and maps the result back to a `HandoffResult`
- Subgraphs are NOT added as nodes via `builder.add_node(compiled_subgraph)` — they are called as plain Python callables from within the node function
- Subgraphs compiled WITHOUT a checkpointer argument — parent graph propagates checkpointing

### State Merge Strategy
- `exec_tool_history` entries from the returned `ExecutorState` are **copied into `RunState.tool_history`** after `.invoke()` returns — this keeps the `MissionAuditor` chain_integrity check working unchanged
- Each copied entry is tagged with `"via_subgraph": True` to distinguish real subgraph invocations from legacy direct calls
- `HandoffResult.output` contains `{tool_name, tool_result, status}` — a summary, not the full history
- `eval_audit_report` from `EvaluatorState` is copied into `RunState.audit_report` — consistent with how `_finalize()` works today

### Claude's Discretion
- Model routing signals and wiring — use `TaskComplexity` literals already defined in `model_router.py`; choose sensible signals (keyword detection on mission text + token budget threshold); wire `ModelRouter.route()` at the point where provider is selected for a task
- Subgraph node topology — keep single-node design from Phase 3; multi-node refinement is explicitly deferred; Phase 4 success criteria are satisfiable with the current single-node subgraphs
- Exact field mapping details in the wrapper function (how `input_context` is built from `TaskHandoff`)
- Integration test fixture design for multi-mission + model routing coverage

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `specialist_executor.py::build_executor_subgraph(tool_scope, memo_store)` — compiled, unit-tested, ready to invoke
- `specialist_evaluator.py::build_evaluator_subgraph()` — compiled, unit-tested, ready to invoke
- `handoff.py::create_handoff()` / `create_handoff_result()` — factories already used in `_route_to_specialist()`
- `model_router.py::ModelRouter` — stub with `_STRONG_TASKS` / `_FAST_TASKS` classification; needs `.route()` wired into provider selection path
- `graph.py::_route_to_specialist()` (lines 1130+) — currently creates `TaskHandoff`, logs it, then calls `_execute_action()` directly; subgraph call replaces `_execute_action()` call

### Established Patterns
- `ensure_state_defaults()` pattern — apply same repair-at-entry in subgraph wrapper
- `Annotated[list[T], operator.add]` reducers — already in `RunState.tool_history`; the copy-back from `exec_tool_history` appends safely
- `via_subgraph: True` tag — new convention; auditor should not break on unknown keys in tool_history records

### Integration Points
- `graph.py::_route_to_specialist()` — primary change target
- `state_schema.py::RunState` — `handoff_queue` and `handoff_results` already exist; `tool_history` and `audit_report` are the merge targets
- `mission_auditor.py::audit_run()` — must continue to pass `chain_integrity` check after real subgraph invocations; reads `tool_history` from `RunState`

</code_context>

<specifics>
## Specific Ideas

- Phase 4 success criterion #1: "logs show real subgraph node transitions" — the `via_subgraph: True` tag in `tool_history` and the subgraph's own `execute` node logging satisfy this
- Phase 4 success criterion #4: "compiled without checkpointer argument" — `build_executor_subgraph()` and `build_evaluator_subgraph()` already compile without checkpointer; the wrapper just calls them
- WALKTHROUGH_PHASE3.md contains the exact sketch of the Phase 4 wrapper function — use it as the implementation spec

</specifics>

<deferred>
## Deferred Ideas

- Parallel `Send()` fan-out for multi-mission execution — v2 requirements (PRLL-01, PRLL-02)
- Multi-node subgraph refinement (supervisor→execute→record inside executor) — explicitly deferred from Phase 3
- Langfuse CallbackHandler for graph-level tracing — Phase 5
- OpenAI/Groq provider paths to ToolNode — future phase
- Human-in-the-loop `interrupt()` API — v2 requirements

</deferred>

---

*Phase: 04-multi-agent-integration-and-model-routing*
*Context gathered: 2026-03-03*
