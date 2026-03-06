# Phase 4: Multi-Agent Integration and Model Routing - Research

**Researched:** 2026-03-03
**Domain:** LangGraph subgraph invocation (wrapper-function pattern), RunState merge safety, model routing signals
**Confidence:** HIGH (based on complete codebase read + Phase 3 WALKTHROUGH; LangGraph API verified via existing compiled subgraph patterns)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Subgraph Invocation Pattern**
- Wrapper-function pattern — as specified in `docs/WALKTHROUGH_PHASE3.md` Phase 4 preview
- `_route_to_specialist()` constructs `ExecutorState` or `EvaluatorState` from the incoming `TaskHandoff`, calls `build_executor_subgraph().invoke(exec_state)` or `build_evaluator_subgraph().invoke(eval_state)`, and maps the result back to a `HandoffResult`
- Subgraphs are NOT added as nodes via `builder.add_node(compiled_subgraph)` — they are called as plain Python callables from within the node function
- Subgraphs compiled WITHOUT a checkpointer argument — parent graph propagates checkpointing

**State Merge Strategy**
- `exec_tool_history` entries from the returned `ExecutorState` are **copied into `RunState.tool_history`** after `.invoke()` returns — this keeps the `MissionAuditor` chain_integrity check working unchanged
- Each copied entry is tagged with `"via_subgraph": True` to distinguish real subgraph invocations from legacy direct calls
- `HandoffResult.output` contains `{tool_name, tool_result, status}` — a summary, not the full history
- `eval_audit_report` from `EvaluatorState` is copied into `RunState.audit_report` — consistent with how `_finalize()` works today

**Claude's Discretion**
- Model routing signals and wiring — use `TaskComplexity` literals already defined in `model_router.py`; choose sensible signals (keyword detection on mission text + token budget threshold); wire `ModelRouter.route()` at the point where provider is selected for a task
- Subgraph node topology — keep single-node design from Phase 3; multi-node refinement is explicitly deferred; Phase 4 success criteria are satisfiable with the current single-node subgraphs
- Exact field mapping details in the wrapper function (how `input_context` is built from `TaskHandoff`)
- Integration test fixture design for multi-mission + model routing coverage

### Deferred Ideas (OUT OF SCOPE)

- Parallel `Send()` fan-out for multi-mission execution — v2 requirements (PRLL-01, PRLL-02)
- Multi-node subgraph refinement (supervisor→execute→record inside executor) — explicitly deferred from Phase 3
- Langfuse CallbackHandler for graph-level tracing — Phase 5
- OpenAI/Groq provider paths to ToolNode — future phase
- Human-in-the-loop `interrupt()` API — v2 requirements
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| MAGT-05 | `_route_to_specialist()` in `graph.py` invokes the compiled specialist subgraph via `TaskHandoff` input and merges the `HandoffResult` output back into `RunState` — not stubs | Wrapper-function pattern fully documented in WALKTHROUGH_PHASE3.md; ExecutorState/EvaluatorState field mappings verified from source; merge path for tool_history and audit_report confirmed safe |
| MAGT-06 | Multi-mission workloads complete without dropping results — all mission reports and tool history entries are preserved across a multi-mission run | `Annotated[list, operator.add]` reducers already on `tool_history` and `mission_reports`; `_sequential_node()` zero-delta wrapper prevents doubling; `via_subgraph` tag added to copies; `MissionAuditor._map_tool_history_to_missions()` uses ordered cursor so ordering must be preserved |
| OBSV-03 | Model-strength routing makes real routing decisions based on task complexity signals (not the existing stub) | `ModelRouter` class and `TaskComplexity` literals exist; `self.provider` is the single call site; `_select_specialist_for_action()` provides the mission context needed for complexity classification |
</phase_requirements>

---

## Summary

Phase 4 is a wiring phase: the infrastructure from Phases 2 and 3 is complete and correct — the task is connecting it. Three targeted changes satisfy all three requirements. First, `_route_to_specialist()` in `graph.py` must call `.invoke()` on the compiled subgraph instead of falling through to `_execute_action()`, then copy the resulting `exec_tool_history` entries into `RunState.tool_history` with a `via_subgraph: True` tag. Second, multi-mission result preservation is already architecturally safe due to the `Annotated[list, operator.add]` reducers installed in Phase 2 and the `_sequential_node()` zero-delta wrapper — the risk is in the copy logic getting the ordering wrong and confusing `MissionAuditor._map_tool_history_to_missions()`. Third, `ModelRouter.route()` needs to be called at the one point where `self.provider` is used for planning (`_generate_with_hard_timeout`), with complexity classification driven by mission text keyword detection and `token_budget_remaining`.

The subgraph pattern is validated: `build_executor_subgraph().invoke(state_dict)` is the exact invocation used in the Phase 3 unit tests, and both subgraphs already compile without a checkpointer argument — satisfying MAGT-05's success criterion #4 (checkpoint replay after two-mission run). The main implementation risk is the state copy-back logic: tool history entries copied from `exec_tool_history` into `RunState.tool_history` must appear in chronological order relative to other entries so the auditor's cursor-based matching algorithm succeeds.

For model routing, the `ModelRouter` class already has `route(task_complexity: TaskComplexity) -> ChatProvider` implemented correctly — the stub comment in the file is misleading; the routing logic IS real (lines 46-50). What is missing is instantiation of a `ModelRouter` inside `LangGraphOrchestrator.__init__()` and a call to `self._router.route(complexity)` at the provider-call site. The classification signal is straightforward: planning calls are `"planning"` complexity (strong provider), tool-dispatch calls are `"tool_selection"` (fast provider).

**Primary recommendation:** Implement in three focused tasks: (1) wire subgraph invocation in `_route_to_specialist()` with copy-back logic, (2) add multi-mission integration test verifying MissionAuditor passes after real subgraph calls, (3) instantiate ModelRouter in orchestrator init and route at `_generate_with_hard_timeout()`.

---

## Standard Stack

### Core (already installed — no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| langgraph | 1.0.10 | `CompiledStateGraph.invoke()`, `StateGraph`, `START`/`END` sentinels | Already in use; subgraph pattern is standard LangGraph API |
| langgraph-prebuilt | 1.0.8 | `ToolNode`, `tools_condition` | Already installed for Phase 2 Anthropic path |
| langchain-anthropic | 1.3.4 | Provider adapter | Already installed |
| pytest | (existing) | Integration test framework | Project standard |

### No New Dependencies

Phase 4 requires zero new packages. All subgraph, state, and routing infrastructure is already in place. The work is pure wiring.

### Installation

```bash
# No new installs required — all dependencies already in pyproject.toml
# Verify with:
.venv/bin/pip show langgraph langgraph-prebuilt
```

---

## Architecture Patterns

### Pattern 1: Wrapper-Function Subgraph Invocation

**What:** `_route_to_specialist()` builds an `ExecutorState` or `EvaluatorState` dict from the `TaskHandoff` already appended to `state["handoff_queue"]`, calls `.invoke()` on the compiled subgraph, and copies result fields back into `RunState`.

**When to use:** Any time a node function in the parent graph needs to delegate execution to a separately-compiled subgraph without sharing state schema keys.

**Why not `builder.add_node(compiled_subgraph)`:** `ExecutorState` and `RunState` share zero keys (enforced by `test_state_isolation.py`). The `add_node` shortcut requires the subgraph's output keys to be a subset of the parent state keys — that constraint is deliberately violated by the `exec_` / `eval_` prefix convention. The wrapper function is the only valid integration approach.

**Sketch (from WALKTHROUGH_PHASE3.md Phase 4 preview):**

```python
# Source: docs/WALKTHROUGH_PHASE3.md (Phase 4 preview section)
from agentic_workflows.orchestration.langgraph.specialist_executor import build_executor_subgraph

def _route_to_specialist(self, state: RunState) -> RunState:
    # ... existing TaskHandoff construction stays ...
    handoff = state["handoff_queue"][-1]  # already appended above

    if specialist == "executor":
        exec_graph = build_executor_subgraph(
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
        result = exec_graph.invoke(exec_state)

        # Copy exec_tool_history into RunState.tool_history with via_subgraph tag
        for entry in result.get("exec_tool_history", []):
            tagged_entry = dict(entry)
            tagged_entry["via_subgraph"] = True
            # call must be the global index so auditor cursor works
            tagged_entry["call"] = len(state["tool_history"]) + 1
            state["tool_history"].append(tagged_entry)

        status = result.get("status", "error")
        output = {
            "tool_name": exec_state["input_context"].get("tool_name", ""),
            "tool_result": result.get("result", {}),
            "status": status,
        }

    elif specialist == "evaluator":
        eval_graph = build_evaluator_subgraph()
        eval_state = {
            "task_id": handoff["task_id"],
            "specialist": "evaluator",
            "mission_id": handoff.get("mission_id", 0),
            "eval_mission_reports": [r for r in state.get("mission_reports", [])],
            "eval_tool_history": list(state.get("tool_history", [])),
            "eval_missions": list(state.get("missions", [])),
            "eval_mission_contracts": list(state.get("mission_contracts", [])),
            "eval_audit_report": None,
            "tokens_used": 0,
            "status": "success",
        }
        result = eval_graph.invoke(eval_state)
        state["audit_report"] = result.get("eval_audit_report")
        status = result.get("status", "error")
        output = {"tool_name": "audit_run", "tool_result": state["audit_report"], "status": status}

    # Update HandoffResult (already appended as placeholder) or append new one
    state["handoff_results"].append(
        create_handoff_result(
            task_id=handoff["task_id"],
            specialist=specialist,
            status=status,
            output=output,
            tokens_used=result.get("tokens_used", 0),
        )
    )
    return state
```

**Critical implementation detail:** The current `_route_to_specialist()` calls `_execute_action()` after appending to `handoff_queue` and `handoff_results`. In Phase 4, the subgraph `.invoke()` replaces the `_execute_action()` call for tool-type actions — not-tool actions (finish) still go through `_execute_action()`.

### Pattern 2: Sequential Copy-Back for Annotated List Fields

**What:** Because `RunState.tool_history` uses `Annotated[list[ToolRecord], operator.add]` and the node is wrapped by `_sequential_node()`, any mutation to `state["tool_history"]` inside the node is already committed in-place. The `_sequential_node()` wrapper returns `[]` for all annotated list fields in the returned dict, so the reducer applies `operator.add(existing, [])` — a no-op.

**Implication for copy-back:** Appending to `state["tool_history"]` inside `_route_to_specialist()` is safe and correct. The entries will be present in the next node's state without duplication.

**Example showing correct field zero-ing (already in graph.py lines 94-99):**

```python
# Source: graph.py lines 83-99 (_sequential_node wrapper)
def wrapper(state: RunState) -> RunState:
    result = fn(state)
    if isinstance(result, dict):
        for field in _ANNOTATED_LIST_FIELDS:
            if field in result:
                result[field] = []   # zero the delta — in-place mutation already committed
    return result
```

### Pattern 3: ModelRouter Wiring

**What:** `ModelRouter` is instantiated in `LangGraphOrchestrator.__init__()` alongside `self.provider`. The single provider call site (`_generate_with_hard_timeout()` / `self.provider.generate()`) is replaced by `self._router.route(complexity).generate()` where `complexity` is derived from calling context.

**The existing ModelRouter is NOT a stub in the routing logic sense** — `route()` correctly returns `self._strong` for planning/evaluation/error_recovery and `self._fast` for tool_selection/continuation. What is missing is:
1. A `ModelRouter` instance stored on `self`
2. A call to `route()` at the provider invocation site
3. A second provider instance (when running dual-provider; if only one provider is configured, `fast_provider=None` defaults to the same instance — no behavior change)

**Complexity classification signals (Claude's Discretion area):**

| Call Site | Complexity | Rationale |
|-----------|------------|-----------|
| `_plan_next_action()` → planning model call | `"planning"` | High-complexity reasoning; needs strong provider |
| `_route_to_specialist()` → tool dispatch (via subgraph) | `"tool_selection"` | Deterministic dispatch; fast provider sufficient |
| `_enforce_memo_policy()` → retry reasoning | `"error_recovery"` | Recovery needs strong provider |
| Token budget low (< 20% remaining) | Escalate to `"planning"` | Conservative routing under resource pressure |

**Signal detection approach:**

```python
# Source: model_router.py (existing TaskComplexity literals)
# Classification is call-site-based, not mission-text based
# (mission-text keyword detection is not needed since call sites are typed)

def _classify_plan_call(self, state: RunState) -> TaskComplexity:
    """Classify the planning call for model routing."""
    budget_remaining = int(state.get("token_budget_remaining", 100_000))
    budget_used = int(state.get("token_budget_used", 0))
    total = budget_remaining + budget_used
    budget_fraction = budget_remaining / total if total > 0 else 1.0
    if budget_fraction < 0.20:
        return "planning"  # conservative: use strong provider when budget is tight
    return "planning"  # planning calls always use strong provider
```

For the integration test demonstrating two task types routing to different models, the cleanest approach is: construct a `ModelRouter` with distinct `strong_provider` and `fast_provider` instances and verify `router.route("planning") is strong` and `router.route("tool_selection") is fast`.

### Anti-Patterns to Avoid

- **Rebuilding subgraph on every call:** `build_executor_subgraph()` compiles a new graph each invocation (includes tool registry construction). Cache the compiled graph as an instance attribute `self._executor_subgraph` and `self._evaluator_subgraph` initialized in `__init__()`, not rebuilt per action. This is essential for performance in multi-mission runs with many tool calls.

- **Copying `exec_tool_history` with wrong `call` index:** The `MissionAuditor._map_tool_history_to_missions()` uses a monotonic `cursor` across the global `tool_history`. If copied entries have `call` values that don't reflect their actual position in the global list, the auditor's ordered matching will miss entries. Set `call = len(state["tool_history"]) + i` (where `i` is the 1-based index of the entry being copied) before appending.

- **Calling `_execute_action()` AND the subgraph:** The current `_route_to_specialist()` calls `_execute_action()` after the handoff setup. Phase 4 replaces `_execute_action()` for tool actions — if both are called, the tool will execute twice (once via subgraph, once via direct dispatch). Ensure the code paths are mutually exclusive.

- **Adding subgraph as a graph node:** `builder.add_node("executor_subgraph", build_executor_subgraph(...))` would cause LangGraph to treat the compiled subgraph as a node, requiring its output keys to be a subset of `RunState` keys. Since `ExecutorState` shares zero keys with `RunState` (test-enforced), this will fail at compile time or produce incorrect merges at runtime. The wrapper-function pattern is mandatory.

- **Forgetting the `_sequential_node()` wrapping for the execute node:** `_route_to_specialist()` is already wrapped via `_sequential_node(self._route_to_specialist)` in `_compile_graph()`. Any new list mutations inside it are safe. Do not add the wrapper again.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Subgraph execution | Custom dispatcher that calls tool directly | `build_executor_subgraph().invoke(exec_state)` | Subgraph handles tool registry scoping, error handling, `exec_tool_history` recording — already tested |
| Tool deduplication in subgraph | Re-implement `seen_tool_signatures` check inside wrapper | `ExecutorState.exec_seen_signatures` field in the subgraph | Already defined in `ExecutorState`; just pass existing signatures |
| Audit report generation | Custom audit inside `_route_to_specialist` | `build_evaluator_subgraph().invoke(eval_state)` | `audit_run()` is already tested; subgraph wraps it correctly |
| Model selection logic | Custom if/else on provider name | `ModelRouter.route(task_complexity)` | `ModelRouter` already has correct `_STRONG_TASKS` frozenset and dual-provider fallback |
| Test ScriptedProvider | New mock class | Existing `ScriptedProvider` from `tests/integration/test_langgraph_flow.py` | Already used in 354 passing tests; handles both single and multi-response scripting |

**Key insight:** Every component needed for Phase 4 is already implemented and tested in isolation. The phase is integration wiring, not new construction.

---

## Common Pitfalls

### Pitfall 1: tool_history Copy-Back Breaks MissionAuditor Cursor

**What goes wrong:** After copying `exec_tool_history` entries into `RunState.tool_history`, the `MissionAuditor._map_tool_history_to_missions()` fails to match them because the cursor advances past positions where matches are expected.

**Why it happens:** `_map_tool_history_to_missions()` uses a monotonic `cursor` variable that advances to `match_idx + 1` after each match. If copied entries are appended in a different order than the `mission_reports[].tool_results` records, the strict-then-loose matching fails. In the legacy path, tool history was written sequentially as tools were called, so report order and history order matched. In the subgraph path, if entries are appended in bulk after all subgraph execution, the ordering relationship must be preserved.

**How to avoid:** Append `exec_tool_history` entries to `RunState.tool_history` immediately after each subgraph invocation, in the same sequence they appear in `exec_tool_history`. Do not batch all copies to the end of the run.

**Warning signs:** `chain_integrity` check in MissionAuditor fails; `mission_attribution_mismatch` findings appear for missions that did use the required tools.

### Pitfall 2: Subgraph Rebuilt Per Tool Call (Performance)

**What goes wrong:** A multi-mission run with 20+ tool calls takes 5-10x longer than expected because `build_executor_subgraph()` recompiles a new `StateGraph` (including `build_tool_registry()`) on every invocation.

**Why it happens:** `build_executor_subgraph()` creates and compiles a new graph object every call. `build_tool_registry()` instantiates all tool objects. These are not expensive in isolation but add up in a hot loop.

**How to avoid:** Cache `self._executor_subgraph = build_executor_subgraph(memo_store=self.memo_store)` in `LangGraphOrchestrator.__init__()`. For tool_scope variations, either cache a full-scope graph and filter at dispatch time, or cache by frozenset of tool_scope.

**Warning signs:** Slow integration tests; logs show `build_executor_subgraph` called hundreds of times.

### Pitfall 3: HandoffResult Appended Twice

**What goes wrong:** `state["handoff_results"]` accumulates two entries per tool call — one from the existing `_route_to_specialist()` code and one from the new subgraph wrapper path.

**Why it happens:** The existing `_route_to_specialist()` already appends a `HandoffResult` after `_execute_action()`. If the subgraph wrapper also appends one without removing the existing append, each action generates two results.

**How to avoid:** The Phase 4 rewrite of `_route_to_specialist()` should have a single `handoff_results.append()` call at the end of each branch (executor/evaluator). Remove the existing `create_handoff_result()` call in the current code when replacing with the subgraph path.

**Warning signs:** `len(state["handoff_results"]) == 2 * len(state["handoff_queue"])` after a run.

### Pitfall 4: eval_audit_report Overwrites Earlier Intermediate Audit

**What goes wrong:** The evaluator subgraph writes `state["audit_report"]` from its `eval_audit_report`. If `_finalize()` also calls `audit_run()` and writes `state["audit_report"]`, there will be two competing audit reports.

**Why it happens:** `_finalize()` currently calls `audit_run()` directly (via `from agentic_workflows.orchestration.langgraph.mission_auditor import audit_run`). If the evaluator subgraph is invoked mid-run, its audit report will be overwritten by the finalize-time audit.

**How to avoid:** Keep the evaluator subgraph invocation as an optional mid-run quality check. The final `audit_report` on `RunState` should come from `_finalize()` — which already has the complete run context. The `eval_audit_report` from the evaluator can be stored in a different field or logged, but should not overwrite the final audit. Alternatively, only invoke the evaluator subgraph in the `finalize` phase, not during tool routing.

**Warning signs:** `audit_report` in final state reflects partial-run data rather than full-run data.

### Pitfall 5: ModelRouter With Single Provider Appears to Not Route

**What goes wrong:** Integration test asserts two tasks route to different providers, but both use the same provider instance because `fast_provider` was not provided to `ModelRouter.__init__()`.

**Why it happens:** `ModelRouter.__init__()` defaults `fast_provider = strong_provider` when `fast_provider=None`. With a single configured provider, all routing returns the same object.

**How to avoid:** For the integration test demonstrating dual routing, construct `ModelRouter` with two distinct `ScriptedProvider` instances. For production, allow the `fast_provider` to be `None` (falls back to same provider) so single-provider users see no behavior change.

**Warning signs:** `router.has_dual_providers` returns `False` in a test that expects dual routing.

---

## Code Examples

Verified patterns from existing codebase sources:

### ExecutorState input construction from TaskHandoff

```python
# Source: docs/WALKTHROUGH_PHASE3.md Phase 4 preview + specialist_executor.py field definitions
# All 11 ExecutorState fields — missing any will produce a LangGraph schema error
exec_state = {
    "task_id": handoff["task_id"],           # str — from TaskHandoff
    "specialist": "executor",                # Literal["executor"]
    "mission_id": handoff["mission_id"],     # int
    "tool_scope": handoff["tool_scope"],     # list[str] — tool whitelist
    "input_context": handoff["input_context"],  # {"tool_name": str, "args": dict, "step": int}
    "token_budget": handoff["token_budget"], # int
    "exec_tool_history": [],                 # list — starts empty; subgraph populates
    "exec_seen_signatures": list(state.get("seen_tool_signatures", [])),  # carry dedup state
    "result": {},                            # dict — starts empty
    "tokens_used": 0,                        # int — starts at 0
    "status": "success",                     # Literal["success","error","timeout"]
}
```

### EvaluatorState input construction from RunState

```python
# Source: specialist_evaluator.py field definitions + evaluate_node() kwarg names
eval_state = {
    "task_id": handoff["task_id"],
    "specialist": "evaluator",
    "mission_id": handoff["mission_id"],
    "eval_mission_reports": [dict(r) for r in state.get("mission_reports", [])],
    "eval_tool_history": [dict(h) for h in state.get("tool_history", [])],
    "eval_missions": list(state.get("missions", [])),
    "eval_mission_contracts": list(state.get("mission_contracts", [])),
    "eval_audit_report": None,
    "tokens_used": 0,
    "status": "success",
}
```

### Copy-back from exec_tool_history to RunState.tool_history

```python
# Source: state_schema.py ToolRecord definition
# ToolRecord has: call, tool, args, result
# exec_tool_history entries have: tool, args, result (no "call" field — assign here)
for i, entry in enumerate(result.get("exec_tool_history", [])):
    tagged_entry: dict = dict(entry)
    tagged_entry["via_subgraph"] = True
    tagged_entry["call"] = len(state["tool_history"]) + i + 1
    state["tool_history"].append(tagged_entry)
```

### ModelRouter instantiation in LangGraphOrchestrator

```python
# Source: model_router.py ModelRouter class + provider.py ChatProvider Protocol
# In __init__():
from agentic_workflows.orchestration.langgraph.model_router import ModelRouter, TaskComplexity

self.provider = provider or build_provider()
fast_provider = fast_provider or None  # None means ModelRouter defaults to strong
self._router = ModelRouter(
    strong_provider=self.provider,
    fast_provider=fast_provider,
)
```

### ModelRouter call at provider invocation site

```python
# Source: graph.py _generate_with_hard_timeout() (lines 1085-1112)
# Replace: self.provider.generate(messages)
# With:    self._router.route(complexity).generate(messages)

def _generate_with_hard_timeout(
    self,
    messages: list[dict[str, str]],
    complexity: TaskComplexity = "planning",
) -> str:
    timeout_seconds = self.plan_call_timeout_seconds
    active_provider = self._router.route(complexity)
    if timeout_seconds <= 0:
        return active_provider.generate(messages)
    # ... rest of timeout logic uses active_provider instead of self.provider ...
```

### Integration test fixture for model routing verification

```python
# Source: tests/integration/test_langgraph_flow.py ScriptedProvider pattern
# Two distinct ScriptedProvider instances to verify routing

class TrackedScriptedProvider:
    """ScriptedProvider that records which complexity levels it was called for."""
    def __init__(self, responses: list[dict], name: str) -> None:
        self._responses = [json.dumps(r) for r in responses]
        self._index = 0
        self.name = name
        self.call_count = 0

    def generate(self, messages):
        self.call_count += 1
        value = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return value

def test_model_router_routes_planning_to_strong() -> None:
    from agentic_workflows.orchestration.langgraph.model_router import ModelRouter
    strong = TrackedScriptedProvider([{"action": "finish", "answer": "done"}], "strong")
    fast = TrackedScriptedProvider([{"action": "finish", "answer": "done"}], "fast")
    router = ModelRouter(strong_provider=strong, fast_provider=fast)
    assert router.route("planning") is strong
    assert router.route("evaluation") is strong
    assert router.route("tool_selection") is fast
    assert router.route("continuation") is fast
```

### Integration test fixture for multi-mission result preservation

```python
# Source: tests/integration/test_langgraph_flow.py LangGraphFlowTests pattern
# Three-mission run using ScriptedProvider; assert MissionAuditor chain_integrity passes

def test_multi_mission_subgraph_preserves_all_tool_history() -> None:
    provider = ScriptedProvider([
        # Mission 1: sort_array call
        {"action": "tool", "tool_name": "sort_array", "args": {"items": [3,1,2]}},
        # Mission 2: repeat_message call
        {"action": "tool", "tool_name": "repeat_message", "args": {"message": "hello"}},
        # Mission 3: finish
        {"action": "finish", "answer": "done"},
    ])
    orch = LangGraphOrchestrator(provider=provider, max_steps=15, missions=["m1", "m2", "m3"])
    result = orch.run(...)
    # All tool_history entries must be present
    tools_used = [e["tool"] for e in result["state"]["tool_history"]]
    assert "sort_array" in tools_used
    assert "repeat_message" in tools_used
    # via_subgraph tag must be set
    assert all(e.get("via_subgraph") for e in result["state"]["tool_history"] if e["tool"] != "finish")
    # Audit must pass chain_integrity
    assert result["audit_report"]["failed"] == 0
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `_route_to_specialist()` calls `_execute_action()` directly (stub) | `_route_to_specialist()` calls subgraph `.invoke()` (real delegation) | Phase 4 | Logs will show subgraph node transitions; tool_history tagged `via_subgraph=True` |
| `self.provider` called directly at every generate site | `self._router.route(complexity).generate(messages)` | Phase 4 | Two task types demonstrably route to different providers in integration test |
| `build_executor_subgraph()` not called at runtime | Cached on `self._executor_subgraph` | Phase 4 | Performance-safe multi-mission runs |

**Deprecated behavior after Phase 4:**
- The `_route_to_specialist()` call to `_execute_action()` for tool-type actions is replaced — the fallthrough path to `_execute_action()` is for non-tool (finish) actions only.

---

## Open Questions

1. **Should evaluator subgraph be invoked per-mission or only at finalize?**
   - What we know: `_finalize()` already calls `audit_run()` directly and writes `state["audit_report"]`. The evaluator subgraph also calls `audit_run()` internally.
   - What's unclear: If the evaluator subgraph is invoked mid-run (during `_route_to_specialist()`), its `eval_audit_report` would contain only partial run data and would be overwritten by `_finalize()`. The success criteria (MAGT-05) says `eval_audit_report → RunState.audit_report` — but this conflicts with the `_finalize()` path.
   - Recommendation: Invoke the evaluator subgraph only at finalize time, or store its result in a separate field (`eval_audit_snapshot`) to avoid collision. `_finalize()` remains the canonical source for `RunState.audit_report`. This resolves Pitfall 4 above.

2. **Tool scope per invocation vs cached full-scope subgraph**
   - What we know: `build_executor_subgraph(tool_scope=...)` filters the registry at compile time. Different tool scopes would require different compiled graphs.
   - What's unclear: Whether the cost of recompiling (one compile per distinct tool_scope) is acceptable at runtime.
   - Recommendation: Cache the full-scope subgraph. The tool-scope enforcement during Phase 4 can be handled by the existing `_is_tool_allowed_for_specialist()` check before calling the subgraph, rather than filtering the registry at compile time. This trades compile-time scoping for a pre-invoke check, which is acceptable for Phase 4 (strict tool scoping is a Phase 5+ hardening concern).

3. **`fast_provider` constructor argument for LangGraphOrchestrator**
   - What we know: Current `__init__` takes only `provider`. ModelRouter needs `strong_provider` and optionally `fast_provider`.
   - What's unclear: How to surface a second provider without breaking existing call sites (run.py, tests).
   - Recommendation: Add `fast_provider: ChatProvider | None = None` to `LangGraphOrchestrator.__init__()`. When `None`, ModelRouter defaults to using the same provider for all calls — existing behavior preserved, zero breaking changes.

---

## Implementation Sequence (for Planner)

Based on dependency analysis, the three requirements map cleanly to three sequential plans:

**Plan 04-01: Wire subgraph invocation in `_route_to_specialist()` (MAGT-05)**
- Add `fast_provider: ChatProvider | None = None` to `__init__`
- Cache `self._executor_subgraph` and `self._evaluator_subgraph` on init
- Replace `_execute_action()` call in the tool-dispatch branch with subgraph `.invoke()`
- Copy-back `exec_tool_history` → `RunState.tool_history` with `via_subgraph=True` tag
- Write unit test: `_route_to_specialist()` with a sort_array action produces `via_subgraph=True` entry in tool_history
- Update WALKTHROUGH_PHASE3.md (per LRNG-01 convention)

**Plan 04-02: Multi-mission integration test + auditor validation (MAGT-06)**
- Write integration test: 3-mission ScriptedProvider run completes without dropping any tool_history entry
- Assert MissionAuditor `chain_integrity` check passes after real subgraph invocations
- Assert checkpoint replay after 2-mission run restores all mission_reports
- Fix any ordering issues in copy-back discovered during test

**Plan 04-03: ModelRouter instantiation and provider routing (OBSV-03)**
- Add `self._router = ModelRouter(strong_provider=..., fast_provider=...)` to `__init__`
- Update `_generate_with_hard_timeout()` signature to accept `complexity: TaskComplexity`
- Call `self._router.route(complexity)` at all `provider.generate()` sites
- Write integration test: two distinct `TrackedScriptedProvider` instances confirm routing split
- Write unit test: `ModelRouter.route("planning")` returns strong; `route("tool_selection")` returns fast

---

## Sources

### Primary (HIGH confidence)

- Codebase — `src/agentic_workflows/orchestration/langgraph/specialist_executor.py` — `ExecutorState` field definitions and `build_executor_subgraph()` factory
- Codebase — `src/agentic_workflows/orchestration/langgraph/specialist_evaluator.py` — `EvaluatorState` field definitions and `build_evaluator_subgraph()` factory
- Codebase — `src/agentic_workflows/orchestration/langgraph/model_router.py` — `ModelRouter`, `TaskComplexity`, `_STRONG_TASKS`
- Codebase — `src/agentic_workflows/orchestration/langgraph/graph.py` — `_route_to_specialist()` at lines 1130-1216; `_sequential_node()` wrapper; `_ANNOTATED_LIST_FIELDS`; `_generate_with_hard_timeout()` at lines 1085-1112
- Codebase — `src/agentic_workflows/orchestration/langgraph/state_schema.py` — `RunState` fields, `ToolRecord`, `Annotated[list, operator.add]` reducers
- Codebase — `src/agentic_workflows/orchestration/langgraph/mission_auditor.py` — `_map_tool_history_to_missions()` cursor algorithm (lines 45-88)
- Codebase — `src/agentic_workflows/orchestration/langgraph/handoff.py` — `TaskHandoff`, `HandoffResult`, `create_handoff`, `create_handoff_result`
- Codebase — `docs/WALKTHROUGH_PHASE3.md` — Phase 4 preview wrapper function sketch (lines 148-183)
- Codebase — `.planning/phases/04-multi-agent-integration-and-model-routing/04-CONTEXT.md` — Locked decisions and field mappings

### Secondary (MEDIUM confidence)

- Codebase — `tests/unit/test_specialist_executor.py` — Confirms `build_executor_subgraph().invoke()` API works with the 11-field ExecutorState dict; `exec_tool_history` is populated correctly
- Codebase — `tests/integration/test_langgraph_flow.py` — `ScriptedProvider` pattern for integration test fixtures; `LangGraphOrchestrator` constructor signature

### Tertiary (LOW confidence — training knowledge)

- LangGraph `CompiledStateGraph.invoke()` behavior with missing optional fields: training knowledge suggests missing TypedDict fields are tolerated if `_ensure_executor_defaults()` or equivalent runs; verified by the existing unit tests passing

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; all libraries already installed and tested at 354 passing tests
- Architecture: HIGH — wrapper function pattern is documented in WALKTHROUGH_PHASE3.md with exact code sketch; subgraph API confirmed by existing unit tests
- Pitfalls: HIGH — derived from direct codebase reading of the auditor cursor algorithm, `_sequential_node()` wrapper, and the existing `_route_to_specialist()` control flow
- Model routing: HIGH — `ModelRouter` implementation is complete and correct; the "stub" comment in the file header is misleading (routing logic itself is real); missing pieces are only instantiation and call-site wiring

**Research date:** 2026-03-03
**Valid until:** 2026-04-03 (stable codebase; no external library changes expected)
