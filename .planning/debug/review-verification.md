---
status: resolved
trigger: "review-verification — verify every claim in langgraph_orchestrator_review.md against actual codebase"
created: 2026-03-04T00:00:00Z
updated: 2026-03-04T00:00:00Z
---

## Current Focus

hypothesis: The prior review described a completely different, simpler codebase — not this one
test: Checked every claim in the review against graph.py (~2100 lines) and state_schema.py
expecting: Most claims are DEBUNKED (wrong architecture) or NOT APPLICABLE (fictitious patterns)
next_action: COMPLETE — verification done; findings written below

## Symptoms

expected: A review that accurately describes the actual graph.py architecture, its real strengths, real weaknesses, and actionable recommendations
actual: The review describes fictitious patterns (AgentState, workflow_registry, build_swarm, astream, setup_node/step_executor_node/decide_next_step) that do not exist in this codebase
errors: No runtime errors — this is a document accuracy verification task
reproduction: Read langgraph_orchestrator_review.md and compare every claim to graph.py + state_schema.py
started: Review was created by a prior agent; user wants verification now

## Eliminated

- hypothesis: "Review was generated from a different version of graph.py"
  evidence: Graph.py is 2100+ lines with RunState, LangGraphOrchestrator, plan/execute/policy/finalize nodes. No version of this file could have had the 7-field AgentState or register_workflow decorator — those patterns are from a generic LangGraph tutorial, not this codebase.
  timestamp: 2026-03-04

## Evidence

- timestamp: 2026-03-04
  checked: state_schema.py — RunState definition
  found: RunState has 27+ fields (run_id, step, messages, completed_tasks, tool_history, memo_events, retry_counts, policy_flags, seen_tool_signatures, tool_call_counts, missions, mission_reports, active_mission_index, active_mission_id, mission_contracts, structured_plan, rerun_context, pending_action, pending_action_queue, final_answer, audit_report, handoff_queue, handoff_results, active_specialist, token_budget_remaining, token_budget_used). Messages field is list[AgentMessage] with operator.add reducer — NOT Annotated[list[AnyMessage], add_messages].
  implication: Review's AgentState(TypedDict) with 7 fields is completely fictitious.

- timestamp: 2026-03-04
  checked: graph.py imports and class definitions (lines 1-70)
  found: No workflow_registry import, no register_workflow decorator, no AgentState class. Imports are: action_parser, content_validator, directives, fallback_planner, memo_manager, mission_tracker, text_extractor, SQLiteCheckpointStore, handoff, SQLiteMemoStore, mission_auditor, mission_parser, model_router, policy, provider, specialist_evaluator, specialist_executor, state_schema, tools_registry.
  implication: The entire "Workflow Registry Pattern" section of the review is fabricated.

- timestamp: 2026-03-04
  checked: graph.py node names in _compile_graph() (lines 313-377)
  found: Nodes are "plan", "execute", "policy", "finalize", "tools" (Anthropic path only), "clarify". No "setup_node", "step_executor_node", or "decide_next_step" functions exist.
  implication: Review's "Entry Point: setup_node / Main Loop: step_executor_node / Conditional Routing: decide_next_step" is entirely fabricated.

- timestamp: 2026-03-04
  checked: graph.py for astream(), StreamEvent, StepCompleted
  found: Zero occurrences of astream(). run() method uses self._compiled.invoke() (synchronous). No StreamEvent or StepCompleted types anywhere in the codebase.
  implication: Review's "Flexible State Streaming" strength is DEBUNKED — streaming does not exist.

- timestamp: 2026-03-04
  checked: graph.py for build_swarm, swarm, arun()
  found: Zero occurrences of build_swarm, swarm, or arun anywhere. The only multi-agent patterns are build_executor_subgraph and build_evaluator_subgraph (lines 158-159), which are invoked synchronously via .invoke(), not .arun().
  implication: Review's "Agent Swarm Integration" strength and the performance bottleneck concern about "swarm blocking main thread" are entirely fabricated.

- timestamp: 2026-03-04
  checked: graph.py for loop protection / max_iterations
  found: Loop protection exists but works differently than described. No state["iteration"] or state["max_iterations"]. Protection is via: (1) step budget: state["step"] > self.max_steps triggers fail-closed (line 598), (2) retry_counts dict tracking invalid_json, memo_policy, provider_timeout, content_validation, finish_rejected, consecutive_empty, duplicate_tool with per-counter limits, (3) recursion_limit = max_steps * 9 passed to invoke() (line 436). Default max_steps=80 (line 124), not 10.
  implication: Review's loop protection code snippet `if state["iteration"] >= state.get("max_iterations", 10)` is DEBUNKED — wrong mechanism, wrong field names, wrong default.

- timestamp: 2026-03-04
  checked: graph.py conditional branching implementation
  found: _route_after_plan() (lines 466-476) routes based on pending_action type: "plan"/"execute"/"finish"/"clarify". Anthropic path uses tools_condition from langgraph.prebuilt. Both are real conditional edges. No "decide_next_step" function.
  implication: Conditional branching EXISTS but via _route_after_plan(), not decide_next_step().

- timestamp: 2026-03-04
  checked: state_schema.py — messages field annotation
  found: messages: list[AgentMessage] — plain list, NOT Annotated[list[AnyMessage], add_messages]. The add_messages reducer (LangChain) is NOT used. The Annotated fields using operator.add are: tool_history, memo_events, seen_tool_signatures, mission_reports.
  implication: Review's "Proper LangChain Integration — add_messages reducer" claim is DEBUNKED.

- timestamp: 2026-03-04
  checked: graph.py error handling in _execute_action() (lines 1455-1861)
  found: Extensive error handling exists — unknown tool check (lines 1599-1613), specialist scope violation block (lines 1472-1502), duplicate tool detection with retry counting (lines 1620-1672), memo policy enforcement, content validation with retry/fail-closed logic, ProviderTimeoutError catch in _plan_next_action() (lines 916-995), generic Exception catch with invalid_json retry counting (lines 996-1073), unrecoverable error detection (_is_unrecoverable_plan_error, lines 1914-1928). Tool execution itself (line 1676) is NOT wrapped in try/except but all paths around it are heavily guarded.
  implication: Review's "Error Handling Gaps" concern is PARTIALLY CORRECT in the narrow sense that line 1676 (tool_result = self.tools[tool_name].execute(tool_args)) has no try/except, but the review's described mechanism (workflow_registry.get_step pattern) is completely wrong.

- timestamp: 2026-03-04
  checked: graph.py for state mutation patterns
  found: State IS mutated in-place (e.g. state["messages"].append(...), state["pending_action"] = ...) but nodes return the mutated state dict. The _sequential_node() wrapper (lines 89-110) zeroes out Annotated list fields in the returned dict to prevent operator.add doubling. This is a deliberate, documented pattern — NOT a side-effect bug.
  implication: Review's "State Mutation Side Effects" concern is DEBUNKED as stated — in-place mutation is intentional and handled correctly via _sequential_node().

- timestamp: 2026-03-04
  checked: graph.py for hardcoded magic numbers
  found: max_steps=80 (line 124, constructor default), max_invalid_plan_retries=8 (line 125), max_provider_timeout_retries=3 (line 126), max_content_validation_retries=2 (line 127), max_duplicate_tool_retries=6 (line 128), max_finish_rejections=6 (line 129). All are constructor parameters with defaults. plan_call_timeout_seconds reads P1_PLAN_CALL_TIMEOUT_SECONDS env var (line 148). Message compaction threshold reads P1_MESSAGE_COMPACTION_THRESHOLD env var (state_schema.py line 258). Recursion limit = max_steps * 9 is computed (line 436).
  implication: Review's "Hardcoded Magic Numbers" concern is DEBUNKED — all limits are configurable constructor params or env vars, not hardcoded. Review cited max_iterations=10 at "Line 42" — that line doesn't even exist as described.

- timestamp: 2026-03-04
  checked: graph.py for retry logic
  found: Retry logic exists and is extensive: invalid_json retries up to max_invalid_plan_retries=8 with escalating hint messages, provider_timeout retries up to max_provider_timeout_retries=3, memo_policy retries up to policy.max_policy_retries, content_validation retries up to max_content_validation_retries=2, finish_rejected retries up to max_finish_rejections=6, duplicate_tool retries up to max_duplicate_tool_retries=6. All with deterministic fallback actions and fail-closed terminal paths.
  implication: Review's "No Retry Logic" concern is DEBUNKED — the codebase has extensive multi-category retry logic with escalating feedback.

- timestamp: 2026-03-04
  checked: graph.py for code injection risk
  found: Tool name resolved via dict lookup: self.tools[tool_name] (line 1676). Before lookup, tool_name is validated: if tool_name not in self.tools at line 1599 — unknown tools are rejected with a system message. Specialist scope enforcement via _is_tool_allowed_for_specialist (line 1320-1325) further restricts which tools each specialist can call. No exec(), eval(), or dynamic code execution of tool names.
  implication: Review's "Code Injection — Medium severity" is PARTIALLY CORRECT in identifying the attack surface but overstated — whitelist validation already exists.

- timestamp: 2026-03-04
  checked: state_schema.py message compaction (lines 257-264)
  found: ensure_state_defaults() applies a sliding window compaction: if len(messages) > P1_MESSAGE_COMPACTION_THRESHOLD (default 40), keeps all system messages + last (threshold - system_count) non-system messages. This is applied on every node entry via ensure_state_defaults().
  implication: Review's "State Exhaustion / message accumulation" concern is DEBUNKED — message compaction is already implemented.

- timestamp: 2026-03-04
  checked: graph.py for structured logging
  found: get_logger("langgraph.orchestrator") used throughout (line 141). Logs include step, run_id, tool, action, mission_id, timeout_mode, retry counts. Structured logging exists and is comprehensive — PLANNER STEP START, TOOL EXEC, TOOL RESULT, SPECIALIST REDIRECT, FINISH REJECTED, etc.
  implication: Review's Medium Priority recommendation "Add structured logging with step correlation IDs" is DEBUNKED — already exists.

- timestamp: 2026-03-04
  checked: graph.py for OpenTelemetry/observability
  found: Langfuse tracing integrated via get_langfuse_callback_handler() (lines 391-393) and @observe("langgraph.orchestrator.run") decorator (line 379). Pipeline trace emitted via _emit_trace() at every major decision point (loop_state, planner_output, specialist_route, tool_exec, validator_fail, validator_pass, mission_complete). SQLiteCheckpointStore saves state at every node transition.
  implication: Review's Low Priority recommendation "Add OpenTelemetry tracing" is already partially addressed via Langfuse. The system has deep observability.

- timestamp: 2026-03-04
  checked: graph.py for actual bare tool execution exception handling
  found: Line 1676: `tool_result = self.tools[tool_name].execute(tool_args)` — no try/except wrapping this call. If a tool raises an unexpected exception (not ProviderTimeoutError), it would propagate up through _execute_action -> _route_to_specialist -> graph node -> LangGraph runtime. LangGraph would catch it and fail the run. This IS a real gap.
  implication: A real but narrow concern: tool execution exceptions are not caught at the orchestrator level. The review identified this correctly in spirit but described the wrong code entirely.

## Resolution

root_cause: The prior review was generated from a generic LangGraph tutorial template or a completely different, much simpler codebase. It describes an architecture (AgentState with 7 fields, @register_workflow decorator, setup_node/step_executor_node/decide_next_step flow, astream/StreamEvent/StepCompleted, build_swarm/arun) that has no presence whatsoever in this codebase. Every code snippet cited fabricated line numbers and nonexistent patterns.

fix: N/A — this is a document verification task. The review document should be replaced or clearly annotated as inaccurate. See findings below for the real architecture picture.

verification: All claims cross-checked against graph.py (2100 lines) and state_schema.py (267 lines). Evidence entries above document specific line numbers for each finding.

files_changed: [.planning/debug/review-verification.md]

---

# FULL VERIFICATION REPORT

## Section 1: Architecture Analysis Claims

### Claim: Entry Point = setup_node, Main Loop = step_executor_node, Conditional Routing = decide_next_step

**VERDICT: DEBUNKED**

Actual nodes in `_compile_graph()` (graph.py:313-377):
- "plan" -> `_plan_next_action()` (the actual entry after START)
- "execute" -> `_route_to_specialist()` (the tool executor, not step_executor_node)
- "policy" -> `_enforce_memo_policy()`
- "finalize" -> `_finalize()`
- "clarify" -> `_clarify_node()` (standard path only)
- "tools" -> `_dedup_then_tool_node(ToolNode(...))` (Anthropic path only)

Routing function: `_route_after_plan()` (lines 466-476) — not `decide_next_step`.

None of `setup_node`, `step_executor_node`, or `decide_next_step` exist anywhere in the codebase.

---

### Claim: AgentState(TypedDict) with fields: messages, config, workflow, step_name, step_data, iteration, max_iterations

**VERDICT: DEBUNKED**

Actual state type is `RunState` (state_schema.py:71-110) with 27 fields. Key differences:
- `messages: list[AgentMessage]` — not `Annotated[list[AnyMessage], add_messages]`
- No `config`, `workflow`, `step_name`, `step_data`, `iteration`, or `max_iterations` fields
- Annotated fields (operator.add reducer) are: `tool_history`, `memo_events`, `seen_tool_signatures`, `mission_reports`
- Loop protection uses `step: int` + `retry_counts: dict[str, int]` + `pending_action_queue`, not `iteration/max_iterations`

---

### Claim: Workflow Registry Pattern with @register_workflow decorator

**VERDICT: DEBUNKED (NOT APPLICABLE)**

No such pattern exists. Tool dispatch uses a simple dict lookup: `self.tools[tool_name].execute(tool_args)` where `self.tools` is built by `build_tool_registry()` at orchestrator init time. This is a flat dict of Tool instances — not a decorator-based registry.

---

## Section 2: Strengths

### Strength Claim: Flexible State Streaming — astream(), StreamEvent, StepCompleted

**VERDICT: DEBUNKED**

`run()` (lines 379-455) uses `self._compiled.invoke()` — synchronous. No `astream()` method exists. No `StreamEvent` or `StepCompleted` types exist anywhere in the codebase. The system does NOT stream.

---

### Strength Claim: Agent Swarm Integration — build_swarm, swarm.arun(state)

**VERDICT: DEBUNKED (NOT APPLICABLE)**

No `build_swarm` or `arun()` anywhere. Multi-agent is implemented via:
- `build_executor_subgraph()` (specialist_executor.py) — invoked synchronously
- `build_evaluator_subgraph()` (specialist_evaluator.py) — invoked synchronously
- Handoff metadata via `handoff_queue` / `handoff_results` in RunState
These are compiled subgraphs called with `.invoke()`, not a swarm pattern.

---

### Strength Claim: Loop Protection — state["iteration"] >= state.get("max_iterations", 10)

**VERDICT: DEBUNKED**

Actual loop protection is multi-layered:
1. Step budget: `state["step"] > self.max_steps` (default 80, constructor param) → fail-closed (line 598)
2. Token budget: `state["token_budget_remaining"] <= 0` → switches to `planner_timeout_mode` (line 735)
3. Per-category retry counters: invalid_json (max 8), provider_timeout (max 3), memo_policy, content_validation (max 2), finish_rejected (max 6), duplicate_tool (max 6)
4. LangGraph recursion_limit: `max_steps * 9` passed to `invoke()` (line 436)

No `iteration` or `max_iterations` fields exist. Default is 80 steps, not 10.

---

### Strength Claim: Conditional Branching via decide_next_step

**VERDICT: PARTIALLY CORRECT**

Conditional branching exists and works well — just via `_route_after_plan()`, not `decide_next_step`. The function reads `pending_action["action"]` and returns "plan"/"execute"/"finish"/"clarify". The Anthropic path uses `tools_condition` from langgraph.prebuilt (line 357).

---

### Strength Claim: Proper LangChain Integration — add_messages reducer, compiled graphs

**VERDICT: PARTIALLY CORRECT**

The graph IS compiled via `StateGraph(RunState)` → `builder.compile()`. ToolNode and tools_condition from langgraph.prebuilt ARE used for the Anthropic path. However:
- The `add_messages` reducer is NOT used — messages uses `list[AgentMessage]` without Annotated
- The Annotated list fields use `operator.add`, not LangChain's `add_messages`

---

## Section 3: Concerns

### Concern: Error Handling Gaps — step_func execution unguarded

**VERDICT: PARTIALLY CORRECT (wrong mechanism, real underlying gap)**

The review's described code (`workflow_registry.get_step`, `step_func(state)`) does not exist. However, a real gap exists:

```python
# graph.py line 1676 — tool execution is NOT wrapped in try/except
tool_result = self.tools[tool_name].execute(tool_args)
```

If a tool raises an unexpected exception, it propagates through `_execute_action` → `_route_to_specialist` → the LangGraph node → LangGraph runtime, potentially crashing the run. The review identified the right vulnerability in spirit but described the wrong code entirely.

The outer `_plan_next_action` has proper try/except for `ProviderTimeoutError` and generic `Exception` (lines 916-1073). The `_execute_action` does not have equivalent protection around tool execution.

---

### Concern: Workflow Registry Coupling

**VERDICT: NOT APPLICABLE**

No workflow registry exists to couple. Not relevant to this codebase.

---

### Concern: State Mutation Side Effects

**VERDICT: DEBUNKED**

In-place state mutation is intentional and correctly handled. `_sequential_node()` wrapper (lines 89-110) zeroes Annotated list fields in the returned dict so `operator.add` reducers don't double-append. The pattern is documented in the module docstring.

---

### Concern: Hardcoded Magic Numbers — max_iterations=10 at Line 42

**VERDICT: DEBUNKED**

Line 42 of graph.py is an import statement. All limits are constructor parameters with sensible defaults:
- `max_steps=80`
- `max_invalid_plan_retries=8`
- `max_provider_timeout_retries=3`
- `max_content_validation_retries=2`
- `max_duplicate_tool_retries=6`
- `max_finish_rejections=6`
- `plan_call_timeout_seconds` reads `P1_PLAN_CALL_TIMEOUT_SECONDS` env var
- Message compaction threshold reads `P1_MESSAGE_COMPACTION_THRESHOLD` env var

---

### Concern: No Retry Logic

**VERDICT: DEBUNKED**

Retry logic is one of the most developed parts of this codebase. Six distinct retry categories, each with escalating feedback messages, deterministic fallback actions, and fail-closed terminal conditions. See Evidence section for detail.

---

## Section 4: Security Table

### Code Injection Risk — Medium

**VERDICT: PARTIALLY CORRECT (overstated severity)**

The attack surface is `tool_name` lookup. Validation does exist (line 1599: `if tool_name not in self.tools`), plus specialist scope enforcement (line 1320-1325). The check happens before execution. Risk is LOW, not MEDIUM — the whitelist validation the review recommended is already implemented.

### Infinite Loop Protection — Low

**VERDICT: PARTIALLY CORRECT (mechanism misidentified)**

Protection exists, just via step budget + retry counters, not `iteration/max_iterations`. Review's verdict that risk is Low is correct.

### State Exhaustion / Message Accumulation — Low

**VERDICT: DEBUNKED (already mitigated)**

Message compaction implemented in `ensure_state_defaults()` (state_schema.py:257-264): sliding window, configurable via `P1_MESSAGE_COMPACTION_THRESHOLD` (default 40). Applied on every node entry. Risk is VERY LOW, not Low.

---

## Section 5: Performance Claims

### Streaming Efficiency — astream() is memory-efficient

**VERDICT: DEBUNKED**

No astream(). Synchronous invoke() only. Not applicable.

### Swarm Blocking — build_swarm blocks main thread

**VERDICT: DEBUNKED**

No build_swarm. Subgraphs invoked synchronously via .invoke() which is expected and fine for the current synchronous architecture.

---

## Real Strengths (Based on Actual Code)

### 1. Multi-layer loop protection with deterministic fallback
Six retry categories with independent counters, escalating feedback messages, timeout fallback mode (switches to pre-determined tool calls when planner times out), and explicit fail-closed terminals. The system degrades gracefully under every failure mode.

### 2. Memoization policy engine
MemoizationPolicy enforces that heavy deterministic writes are persisted before the run continues. Auto-memoize logic (lines 1826-1853) removes the burden from the model — even if the model ignores the policy message, the orchestrator memoizes write_file results automatically. Cache reuse logic (`_maybe_complete_next_write_from_cache`) can skip entire tool executions for repeated runs.

### 3. Duplicate tool call prevention
`seen_tool_signatures` (Annotated list with operator.add) tracks the JSON-serialized signature of every tool+args pair. Exact duplicates are blocked with guided recovery. The signature check runs before tool execution on both the standard path and the Anthropic ToolNode path (via `_dedup_then_tool_node` wrapper).

### 4. Mission attribution and structured planning
`parse_missions()` produces a `StructuredPlan` with hierarchical steps. Every tool action is tagged with `__mission_id`. Mission reports track per-mission tool usage, required tools, required files, contract checks, and subtask contracts. The auditor (`audit_run()`) runs 9 checks post-run including chain integrity validation.

### 5. Dual-provider graph topology
`_compile_graph()` forks into two distinct topologies at build time: standard (plan→execute→policy→plan loop) and Anthropic (plan→tools→plan ReAct loop via ToolNode). The dedup wrapper preserves the signature invariant on the ToolNode path. The switch is controlled by `P1_PROVIDER` env var without code changes.

### 6. Annotated list reducers with sequential node correction
`_sequential_node()` wrapper correctly handles the LangGraph operator.add reducer semantics for sequential operation — zeroing out the delta so accumulated lists aren't doubled on each step. This is a non-obvious correctness requirement that is handled elegantly.

### 7. Token budget tracking with graceful degradation
Token usage estimated and tracked per step. When budget exhausted, switches to `planner_timeout_mode` which uses deterministic fallback actions instead of calling the (now-budget-exhausted) model.

### 8. Checkpoint persistence at every decision point
SQLiteCheckpointStore.save() called at every meaningful node transition with the full state. Enables post-mortem analysis and supports future resumption logic.

---

## Real Concerns (Actual Issues Found)

### HIGH: Tool execution exceptions unhandled at orchestrator level

**Location:** `graph.py:1676`

```python
tool_result = self.tools[tool_name].execute(tool_args)
```

No try/except wraps this call. An exception in any tool's `.execute()` method propagates through `_execute_action` → `_route_to_specialist` → the LangGraph node → LangGraph runtime. LangGraph will catch it and mark the run as failed — but without recording what happened in the run state, checkpoints, or mission reports. The tool's output schema validation on line 1677 also runs unguarded.

**Impact:** Any tool that can raise (network tools like http_request, filesystem tools like write_file on permission errors, bash execution, database operations) can crash the run without the graceful fail-closed behavior used elsewhere.

**Fix:** Wrap lines 1676-1677 in try/except, record the error in tool_result, append to tool_history, and return state normally (same pattern used for duplicate detection and scope violations).

---

### MEDIUM: No async execution — synchronous provider calls block the thread

**Location:** `graph.py:1286-1309` (`_generate_with_hard_timeout`)

The hard timeout is implemented via `threading.Thread` with a `queue.Queue(maxsize=1)` — not asyncio. This means each provider call occupies a thread for its full duration (up to `plan_call_timeout_seconds`=45s). For a process handling multiple concurrent runs, this could exhaust the thread pool.

**Impact:** Low risk for single-run CLI usage; real risk if this orchestrator is wrapped in a web server handling concurrent requests.

**Fix:** For future async use, refactor `_generate_with_hard_timeout` to `asyncio.wait_for(provider.agenerate(...), timeout=...)`.

---

### MEDIUM: `_sequential_node` wrapper applied inconsistently

**Location:** `graph.py:335-338, 367`

`_clarify_node` is added without the `_sequential_node` wrapper:
```python
builder.add_node("clarify", self._clarify_node)  # line 367 — no wrapper
```
All other nodes use `_sequential_node(self._xxx)`. If `_clarify_node` ever appends to `tool_history`, `memo_events`, `seen_tool_signatures`, or `mission_reports`, the operator.add reducer would double-append those lists.

Currently `_clarify_node` only sets `final_answer` and `pending_action`, so this does not cause a bug today. But it is a latent correctness hazard if the node is extended.

**Fix:** Wrap `self._clarify_node` with `_sequential_node`.

---

### MEDIUM: Recursion limit set to max_steps * 9

**Location:** `graph.py:436`

```python
config={"recursion_limit": self.max_steps * 9, ...}
```

With `max_steps=80`, this sets `recursion_limit=720`. LangGraph counts every node invocation toward this limit. In the standard path (plan→execute→policy→plan), each iteration uses 3 node transitions. 720 / 3 = 240 outer iterations — far more than max_steps=80. The step budget check (`state["step"] > self.max_steps`) is the real guard, not the recursion limit.

This is not a bug, but the 9x multiplier is opaque and the comment doesn't explain why 9 was chosen. If the graph topology changes (adding more nodes per iteration), the multiplier could become insufficient.

**Fix:** Document why 9x is the chosen multiplier, or compute it explicitly from the graph topology depth.

---

### LOW: Bare `contextlib.suppress(Exception)` in specialist routing

**Location:** `graph.py:1344`

```python
with contextlib.suppress(Exception):
    self._on_specialist_route(...)
```

If `_on_specialist_route` raises (e.g., a monitoring callback that fails), the exception is silently swallowed with no log entry. This makes debugging callback failures invisible.

**Fix:** Replace with explicit try/except that logs a warning before suppressing.

---

### LOW: Auto-memoization writes to run_id="shared" for cache invalidation, not per-run

**Location:** `graph.py:228-240` (`_invalidate_known_poisoned_cache_entries`)

Hardcoded poisoned cache entries are deleted at orchestrator init. If new poisoned keys are discovered, they must be added to this list manually in code and deployed. This is a maintenance burden.

**Fix:** Add a runtime mechanism to invalidate cache entries (e.g., an admin tool or config file-based invalidation list).

---

## Recommended Next Steps

### HIGH Priority

1. **Wrap tool execution in try/except** (graph.py:1676-1677)
   Add a try/except around `self.tools[tool_name].execute(tool_args)` and `validate_tool_output(...)`. On exception, record the error in tool_result dict, append to tool_history, log the exception, and return state. This brings tool execution into the same graceful-failure pattern used everywhere else.

2. **Apply `_sequential_node` to `_clarify_node`** (graph.py:367)
   Change `builder.add_node("clarify", self._clarify_node)` to `builder.add_node("clarify", _sequential_node(self._clarify_node))` to prevent latent doubling bug.

### MEDIUM Priority

3. **Document or refactor the 9x recursion limit multiplier** (graph.py:436)
   Either add a comment explaining that the standard path uses 3 nodes per iteration (plan/execute/policy) plus buffer for retries, or compute it as `max(self.max_steps * 4, 200)`.

4. **Log suppressed callback exceptions** (graph.py:1344)
   Replace `contextlib.suppress(Exception)` with try/except that logs a warning before suppressing, so monitoring callback failures are visible in logs.

### LOW Priority

5. **Add async provider support** for future multi-concurrent-run scenarios. Current threading approach is correct for CLI single-run usage but would need refactoring for a web server deployment.

6. **Externalize cache invalidation list** from hardcoded tuples to a config file or database record so poisoned keys can be invalidated without code deployment.

7. **Delete `langgraph_orchestrator_review.md`** from the project root — it describes a nonexistent architecture and will mislead future contributors. Replace with a short ARCHITECTURE.md that accurately describes the plan→execute→policy→finalize topology, RunState fields, and the dual-provider graph fork.
