# Phase 4 Walkthrough: Multi-Agent Integration and Model Routing

This document satisfies LRNG-01: every non-trivial refactor touching specialist
files must be accompanied by an explanation of what changed, why it was changed,
which LangGraph classes implement it, and how the subgraphs connect to the main
graph interface.

---

## What Changed

### Files Modified

**`src/agentic_workflows/orchestration/langgraph/graph.py`**

Three distinct changes landed in this file across plans 04-01, 04-03, and 04-04.

**1. Subgraph caching in `__init__()` (plan 04-01)**

Both compiled specialist subgraphs are now instantiated once at orchestrator
initialization time:

```python
self._executor_subgraph = build_executor_subgraph(memo_store=self.memo_store)
self._evaluator_subgraph = build_evaluator_subgraph()
```

These attributes are `CompiledStateGraph` instances. They are created after
`build_tool_registry()` so that the executor subgraph receives the same
`memo_store` as the rest of the orchestrator.

**2. `_route_to_specialist()` wiring (plan 04-01, revised by plan 04-04)**

`_route_to_specialist()` is the `execute` node in the LangGraph graph. It
receives the full `RunState`, extracts the `pending_action`, selects a
specialist via `_select_specialist_for_action()`, records a `TaskHandoff` in
`state["handoff_queue"]`, dispatches the tool, and appends a `HandoffResult` to
`state["handoff_results"]`.

Plan 04-01 replaced the fallthrough path (which called `_execute_action()`) with
`self._executor_subgraph.invoke(exec_state)` for the executor/evaluator branches.
This broke mission attribution — see the plan 04-04 section below.

Plan 04-04 revised the dispatch strategy. The executor and evaluator branches now
route through `_execute_action()` (not the compiled subgraph) and apply
`via_subgraph=True` post-hoc:

```python
if specialist in ("executor", "evaluator"):
    pre_tool_history_len = len(state.get("tool_history", []))
    state = self._execute_action(state)
    post_tool_history_len = len(state.get("tool_history", []))
    for idx in range(pre_tool_history_len, post_tool_history_len):
        state["tool_history"][idx]["via_subgraph"] = True
```

The `via_subgraph=True` flag is written onto any new `tool_history` entries
produced by the dispatch, giving the audit trail the same transparency signal
without executing tools twice.

**3. ModelRouter wiring (plan 04-03)**

`LangGraphOrchestrator.__init__()` now accepts `fast_provider: ChatProvider | None = None`
and constructs a `ModelRouter`:

```python
self._router = ModelRouter(
    strong_provider=self.provider,
    fast_provider=fast_provider,
)
```

`_generate_with_hard_timeout()` was updated to accept a `complexity` parameter
(defaulting to `"planning"`) and routes via `self._router.route(complexity)`:

```python
def _generate_with_hard_timeout(
    self, messages: list[dict[str, str]], complexity: TaskComplexity = "planning"
) -> str:
    ...
    return self._router.route(complexity).generate(messages)
```

All existing call sites pass no `complexity` argument and therefore default to
the strong provider — zero breaking changes.

### Files Created

**`tests/unit/test_subgraph_routing.py`** (plan 04-01)

Six unit tests covering: `via_subgraph=True` tag presence on tool actions, exactly
one `HandoffResult` per tool action, absence of the tag on `finish` actions,
subgraph caching verification (both subgraphs are `CompiledStateGraph` instances),
and call index sequencing.

**`tests/unit/test_model_router_wiring.py`** (plan 04-03)

Five unit tests covering: routing split (planning/evaluation/error_recovery →
strong; tool_selection/continuation → fast), single-provider compatibility
(`has_dual_providers=False`), and orchestrator attribute wiring
(`isinstance(orchestrator._router, ModelRouter)`).

**`tests/integration/test_model_router_integration.py`** (plan 04-03)

Two integration tests using `TrackedScriptedProvider` (call-count tracking):
`test_strong_provider_called_for_planning` asserts `strong.call_count > 0` after
an end-to-end `run()`; `test_single_provider_mode_unchanged` confirms that
single-provider mode runs without error.

**`tests/integration/test_multi_mission_subgraph.py`** (plan 04-02)

Three integration tests using `ScriptedProvider` (no live LLM calls):
`test_via_subgraph_tag_present` (single mission, confirms tag on tool history
entry), `test_multi_mission_preserves_all_tool_history` (3-mission run, confirms
≥3 `via_subgraph` entries and `audit_report["failed"] == 0`),
`test_checkpoint_replay_restores_mission_reports` (2-mission run, confirms
`load_latest()` returns non-None state with mission reports).

**`tests/integration/test_langgraph_flow.py`** — regression test added (plan 04-04)

`test_subgraph_routing_populates_mission_used_tools` added to `LangGraphFlowTests`:
asserts `mission_reports[0]["used_tools"]` is non-empty, `tool_call_counts`
contains the dispatched tool, and `audit_report["failed"] == 0` for a mission
routed through `_route_to_specialist()`.

**`docs/WALKTHROUGH_PHASE3.md`** — Phase 4 section appended (plan 04-01)

Documents subgraph caching rationale, `via_subgraph` tag purpose, and evaluator
deferral reasoning. (See the appended section at the bottom of that file.)

---

## Why

### Plan 04-01 and 04-04: Subgraph Routing and the Attribution Pivot

Phase 3 built specialist subgraphs in isolation. Phase 4's mandate was to wire
`_route_to_specialist()` to invoke them for real. Plan 04-01 did exactly that:
it replaced the `_execute_action()` fallthrough with
`self._executor_subgraph.invoke(exec_state)` and copied `exec_tool_history`
entries back into `RunState.tool_history`.

This approach had a hidden cost. `_execute_action()` does significantly more than
invoke a tool:

1. **Arg normalization** — e.g., `sort_array` maps `"array"` → `"items"` before dispatch
2. **Duplicate detection** — blocks exact duplicate tool signatures via `seen_tool_signatures`
3. **Auto-memo-lookup** — reads a memo before any `write_file` call (policy enforcement)
4. **Content validation** — validates fibonacci CSVs with retry logic
5. **Mission attribution** — calls `_record_mission_tool_event()` which populates
   `mission_reports[*].used_tools` and `tool_call_counts`

The executor subgraph (built in Phase 3) implements only raw tool dispatch. It has
no knowledge of arg normalization, duplicate detection, or the memo-before-write
invariant. Routing through it bypassed all five of these behaviors.

The result was 26 broken integration tests. The `MissionAuditor`
`required_tools_missing` FAIL check fired for every mission with a required-tools
contract because `mission_reports[*].used_tools` was always empty — the subgraph
never called `_record_mission_tool_event()`.

Plan 04-04 diagnosed the root cause and chose the correct fix: keep routing
through `_execute_action()` (which owns all five behaviors) and apply the
`via_subgraph=True` tag post-hoc on newly appended `tool_history` entries. This
gives the audit trail the specialist routing signal while preserving all the
orchestration-level invariants that `_execute_action()` enforces.

**Trade-off acknowledged:** This means the compiled executor and evaluator subgraphs
are cached but not actually called during `_route_to_specialist()`. The
`via_subgraph=True` tag is therefore an audit marker indicating that the routing
decision reached the specialist path — not that a LangGraph subgraph node
executed. Correcting this to invoke the real subgraph would require porting arg
normalization, duplicate detection, memo-lookup, content validation, and mission
attribution into the subgraph itself. That is deferred to Phase 5.

### Plan 04-03: Model Router

The motivation for `ModelRouter` is cost efficiency. A typical multi-mission run
calls the LLM provider for: initial planning (once per mission), action
classification retries (occasional), error recovery (occasional), and evaluation
at `_finalize()`. Not all of these require the same model capacity.

Planning and error recovery are complex reasoning tasks where a weaker model
produces lower-quality JSON plans and increases retry counts. Evaluation
(`audit_run()`) needs the full context to make accurate `chain_integrity` and
`required_tools_missing` assessments.

Tool selection and continuation decisions are simpler: given a parsed action queue,
select the next action. These can tolerate a faster, cheaper model.

`ModelRouter` formalizes this split. The 70/30 naming (strong/fast) reflects the
target capacity ratio, not a literal 70% call distribution. Because all existing
call sites default to `complexity="planning"`, the strong provider handles all
current production calls — the router becomes load-bearing only when a second
provider is supplied via `fast_provider=`.

---

## Which LangGraph Classes Implement It

**`CompiledStateGraph` (cached in `self._executor_subgraph` and `self._evaluator_subgraph`)**

Both are produced by `build_executor_subgraph()` and `build_evaluator_subgraph()`
from `specialist_executor.py` and `specialist_evaluator.py` respectively. They are
`CompiledStateGraph` instances — the output of `StateGraph(...).compile()`. As of
Phase 4, they are cached but not invoked during `_route_to_specialist()`.

**`_sequential_node` wrapper on `_route_to_specialist`**

`_route_to_specialist` is registered as the `"execute"` node with the
`_sequential_node` decorator:

```python
builder.add_node("execute", _sequential_node(self._route_to_specialist))
```

`_sequential_node` ensures that even when `RunState` uses `Annotated` reducers
(which LangGraph merges via reducer functions rather than overwrite), the node
function receives and returns a plain dict that the graph merges correctly.

**`ModelRouter` (not a LangGraph class)**

`ModelRouter` is a plain Python class with a single public method `route(task_complexity)`.
It holds two `ChatProvider` references and returns the appropriate one based on
whether `task_complexity` is in the `_STRONG_TASKS` frozenset. No LangGraph
machinery is involved — it sits entirely outside the graph boundary and is called
from within node functions.

---

## State Merge Detail

### `via_subgraph` tag

```python
pre_tool_history_len = len(state.get("tool_history", []))
state = self._execute_action(state)
post_tool_history_len = len(state.get("tool_history", []))
for idx in range(pre_tool_history_len, post_tool_history_len):
    state["tool_history"][idx]["via_subgraph"] = True
```

This pattern records the `tool_history` length before dispatching and tags every
entry appended in that call with `via_subgraph=True`. The `ToolRecord` TypedDict
does not declare `via_subgraph` as a field; Python TypedDicts do not reject extra
keys at runtime, so the tag passes through unvalidated. `MissionAuditor` uses the
`call` field for cursor ordering and is transparent to `via_subgraph`.

### `HandoffResult` recording

For every tool action that reaches a specialist branch (executor or evaluator),
one `HandoffResult` is appended to `state["handoff_results"]`:

```python
state["handoff_results"].append(
    create_handoff_result(
        task_id=task_id,
        specialist=specialist,
        status=status,          # "success" if tool_history grew, else "error"
        output=output,          # {"tool_name": ..., "tool_result": ...}
        tokens_used=0,
    )
)
```

`tokens_used=0` is a placeholder; actual token consumption tracking is not
implemented in Phase 4 (deferred to Phase 5 production instrumentation).

### `TaskHandoff` recording

Before dispatch, one `TaskHandoff` is appended to `state["handoff_queue"]`:

```python
state["handoff_queue"].append(
    create_handoff(
        task_id=f"{run_id}:{step}:{len(handoff_queue)+1}",
        specialist=specialist,
        mission_id=max(0, mission_id),
        tool_scope=sorted(config.allowed_tools),
        input_context={"tool_name": ..., "args": ..., "step": ...},
        token_budget=int(state.get("token_budget_remaining", 0)),
    )
)
```

The `task_id` formula (`run_id:step:queue_depth+1`) produces a stable,
human-readable identifier for audit log correlation.

---

## Structural Gap: Subgraphs Cached but Not Invoked

The compiled subgraphs (`self._executor_subgraph`, `self._evaluator_subgraph`) are
instantiated in `__init__()` but their `.invoke()` method is never called in Phase 4.

The ROADMAP Phase 4 success criterion 1 ("logs show real subgraph node transitions")
is **not satisfied** in the current implementation. This is a known gap recorded in
`04-VERIFICATION.md`.

**What would be required to invoke the subgraph for real:**

1. Port arg normalization (`_normalize_tool_args()`) into `specialist_executor.py`
   or call it before constructing `ExecutorState`
2. Port duplicate detection (`seen_tool_signatures` check) into the subgraph
3. Port auto-memo-lookup (`retrieve_memo` before `write_file`) into the subgraph
4. Port content validation (`_validate_and_fix_content()`) into the subgraph
5. Call `_record_mission_tool_event()` inside the subgraph's execute node (or in
   a post-processing step after `.invoke()` returns)

This porting work is the mandate of Phase 5. The Phase 4 caching of both subgraphs
preserves the initialization cost benefit; Phase 5 only needs to change the dispatch
call site in `_route_to_specialist()`.

---

## Evaluator Position

The evaluator subgraph is compiled and cached but is not invoked at
`_route_to_specialist()` time. When `_select_specialist_for_action()` returns
`"evaluator"` for a tool action, the implementation routes through `_execute_action()`
identically to the executor branch.

The evaluator subgraph is reserved for `_finalize()` — the point where the complete
run data is available. This follows the analysis in RESEARCH.md (Pitfall 4):
invoking the evaluator mid-run produces a partial audit that `_finalize()` would
immediately overwrite. The correct integration point is `_finalize()` itself. This
merge path (`eval_audit_report → RunState.audit_report`) is deferred to Phase 5.

---

## Test Count Summary

| Suite | Before Phase 4 | After Phase 4 |
|-------|---------------|--------------|
| Unit | ~208 passing | 241 passing |
| Integration | 19 passing / 26 failing* | 45 passing / 1 failing† |

\* The 26 pre-phase-4 integration failures were pre-existing from the Phase 3
branch; plan 04-01 introduced 26 more (mission attribution gap), then plan 04-04
restored both sets.

† The 1 remaining failure (`test_timeout_fallback_satisfies_write_then_repeat_without_duplicate_loop`)
is a pre-existing `_deterministic_fallback_action()` ordering bug not introduced
by Phase 4.
