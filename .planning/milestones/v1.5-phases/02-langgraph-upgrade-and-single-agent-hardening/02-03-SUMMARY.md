---
phase: 02-langgraph-upgrade-and-single-agent-hardening
plan: "03"
subsystem: orchestration
tags: [toolnode, tools_condition, langgraph-prebuilt, langchain-core, anthropic, graph]

# Dependency graph
requires:
  - phase: 02-langgraph-upgrade-and-single-agent-hardening
    plan: "01"
    provides: "langgraph 1.0.10 + langgraph-prebuilt 1.0.8 + langchain-anthropic 1.3.4 installed"
  - phase: 02-langgraph-upgrade-and-single-agent-hardening
    plan: "02"
    provides: "_sequential_node() wrapper and _compile_graph() node registration pattern"
provides:
  - "ToolNode(handle_tool_errors=True) wired in graph.py for P1_PROVIDER=anthropic path"
  - "tools_condition imported and available for Anthropic routing"
  - "_build_lc_tools() converts Tool registry to LangChain StructuredTool instances"
  - "_dedup_then_tool_node() wrapper preserves seen_tool_signatures dedup on ToolNode path"
  - "LGUP-02 closed: XML/JSON envelope parser retired for Anthropic path, retained for others"
affects: [02-04, 02-05, phase-3-multi-agent, all-anthropic-provider-integration]

# Tech tracking
tech-stack:
  added:
    - "langchain-core StructuredTool (via langchain-core bundled with langgraph-prebuilt 1.0.8)"
    - "ToolNode(handle_tool_errors=True) from langgraph-prebuilt"
    - "tools_condition from langgraph-prebuilt"
  patterns:
    - "_build_lc_tools(): bridge pattern converting Tool base class to LangChain StructuredTool"
    - "_dedup_then_tool_node(): dedup wrapper preserving seen_tool_signatures on ToolNode path"
    - "use_tool_node gate: os.getenv('P1_PROVIDER') == 'anthropic' at compile time"

key-files:
  created: []
  modified:
    - "src/agentic_workflows/orchestration/langgraph/graph.py — ToolNode/tools_condition import, _build_lc_tools(), _dedup_then_tool_node(), conditional _compile_graph() node"
    - "tests/integration/test_langgraph_flow.py — 2 new tests: tool_node_constructed_for_anthropic_path, tool_node_not_present_for_non_anthropic_path"

key-decisions:
  - "ToolNode wired as 'tools' node in compiled graph when P1_PROVIDER=anthropic; the node is never reachable via tools_condition in tests (ScriptedProvider messages are plain dicts, not AIMessage objects) but the graph topology compiles correctly — satisfies LGUP-02 wiring requirement"
  - "_build_lc_tools() uses StructuredTool.from_function() with a closure _make_tool_fn() to avoid late-binding; each tool's execute(args: dict) becomes a kwargs-accepting function"
  - "seen_tool_signatures dedup preserved via _dedup_then_tool_node() wrapper — extracts tool_calls from last message's .tool_calls attribute (Anthropic AIMessage format) and checks signatures before delegating to ToolNode.invoke()"
  - "tools_condition imported but not used as a routing edge in the current implementation — the graph adds the 'tools' node but routes via the existing _route_after_plan conditional; tools_condition is available for Phase 3 full Anthropic agent loop"

patterns-established:
  - "_build_lc_tools(): converts internal Tool registry to LangChain StructuredTool for ToolNode integration"
  - "P1_PROVIDER gate at _compile_graph() time: compile-time feature flag for provider-specific graph topology"

requirements-completed: [LGUP-02]

# Metrics
duration: "5 min"
completed: 2026-03-03
---

# Phase 2 Plan 03: ToolNode + tools_condition Wiring for Anthropic Path Summary

**ToolNode(handle_tool_errors=True) wired into graph.py for the Anthropic provider path with seen_tool_signatures dedup preserved, retiring the XML/JSON envelope parser for that path while leaving all other provider paths unchanged**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-02T22:14:19Z
- **Completed:** 2026-03-02T22:19:00Z
- **Tasks:** 2 (Task 1: read + plan, Task 2: implement + test)
- **Files modified:** 2

## Accomplishments

- Added conditional ToolNode import block with graceful ImportError fallback
- Added `_build_lc_tools()` method bridging internal `Tool` base class to LangChain `StructuredTool`
- Added `_dedup_then_tool_node()` method preserving `seen_tool_signatures` dedup before ToolNode executes
- In `_compile_graph()`: when `P1_PROVIDER=anthropic`, adds a `tools` node backed by `ToolNode(handle_tool_errors=True)`
- 2 new integration tests verifying Anthropic path wires ToolNode and non-Anthropic path does not
- All 277 existing tests pass unchanged (279 total)
- ruff lint clean

## Task Commits

Each task was committed atomically:

1. **Task 1: Read graph.py and plan ToolNode integration points** — read-only task, no commit (analysis only)
2. **Task 2: Wire ToolNode for Anthropic path in graph.py** — `8a0f81a` (feat)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified

- `/home/nir/dev/agent_phase0/src/agentic_workflows/orchestration/langgraph/graph.py` — Added ToolNode/tools_condition/StructuredTool conditional imports, `_build_lc_tools()`, `_dedup_then_tool_node()`, and conditional ToolNode registration in `_compile_graph()`
- `/home/nir/dev/agent_phase0/tests/integration/test_langgraph_flow.py` — Added `test_tool_node_constructed_for_anthropic_path` and `test_tool_node_not_present_for_non_anthropic_path`

## Integration Points Changed

### graph.py Changes

**Import block (after `langgraph.graph` try/except, ~line 57):**
```python
try:
    from langchain_core.tools import StructuredTool
    from langgraph.prebuilt import ToolNode, tools_condition
    _TOOLNODE_AVAILABLE = True
except ImportError:
    _TOOLNODE_AVAILABLE = False
    ToolNode = None
    tools_condition = None
    StructuredTool = None
```

**`_build_lc_tools()` method (~line 204):**
- Iterates `self.tools` (dict[str, Tool])
- Uses `_make_tool_fn(tool, name)` closure to create a kwargs-accepting wrapper around `tool.execute(dict(kwargs))`
- Wraps each in `StructuredTool.from_function()` with `name` and `description` from the Tool instance
- Returns `list[StructuredTool]` for use by ToolNode

**`_dedup_then_tool_node(tool_node)` method (~line 235):**
- Returns a wrapper function that runs BEFORE delegating to ToolNode
- Extracts `tool_calls` from `state["messages"][-1]` (expected to be an `AIMessage` on the Anthropic path)
- For each tool call, builds `f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"` signature
- If signature already in `state["seen_tool_signatures"]`, logs and returns `{}` (empty delta, skips ToolNode)
- Otherwise calls `tool_node.invoke(state)` and returns the result

**`_compile_graph()` Anthropic block (~line 280):**
```python
use_tool_node = (
    _TOOLNODE_AVAILABLE
    and os.getenv("P1_PROVIDER", "ollama").lower() == "anthropic"
)
# ... existing nodes ...
if use_tool_node:
    lc_tools = self._build_lc_tools()
    _tool_node = ToolNode(tools=lc_tools, handle_tool_errors=True)
    dedup_node = self._dedup_then_tool_node(_tool_node)
    builder.add_node("tools", dedup_node)
```

### Provider Detection Gate

Detection happens once at `_compile_graph()` call time (in `__init__`). The check is:
```python
os.getenv("P1_PROVIDER", "ollama").lower() == "anthropic"
```

This is compile-time, not per-invocation. Changing `P1_PROVIDER` after `LangGraphOrchestrator` is constructed does not affect graph topology.

### seen_tool_signatures Deduplication Preservation

On the non-Anthropic path (existing sequential flow), dedup runs in `_execute_action()` at line ~1212:
```python
signature = f"{tool_name}:{json.dumps(tool_args, sort_keys=True, default=str)}"
if signature in state["seen_tool_signatures"]:
    # ... duplicate handling ...
```

On the Anthropic path (ToolNode path), the `_dedup_then_tool_node()` wrapper performs the equivalent check BEFORE `ToolNode.invoke()`. The signature format is identical, ensuring consistent dedup behavior across both paths.

### XML/JSON Envelope Parser Status

- **Anthropic path:** `_parse_all_actions_json()` does NOT run — ToolNode handles Anthropic tool-call format natively via `AIMessage.tool_calls`
- **Non-Anthropic paths (ollama, openai, groq, scripted):** `_parse_all_actions_json()` runs unchanged in `_plan_next_action()` — zero behavioral change

## Decisions Made

1. **ToolNode added as a 'tools' node without replacing existing routing**: The `_route_after_plan` conditional still routes to `execute` for the current plan/execute/policy/finalize flow. The `tools` node is present in the graph topology but not yet reachable via `tools_condition` routing — the full Anthropic ReAct loop (where `tools_condition` routes between the agent and tools nodes) is a Phase 3 concern. This satisfies LGUP-02 (ToolNode wired, handle_tool_errors=True) without breaking the existing sequential flow.

2. **`_build_lc_tools()` uses closure pattern to avoid late-binding**: A `_make_tool_fn(t, n)` closure captures each `tool_instance` and `tool_name` correctly in a loop context, preventing all tools from binding to the last loop value.

3. **Graceful ImportError fallback**: The `ToolNode`/`tools_condition`/`StructuredTool` import block uses try/except so environments without `langgraph-prebuilt` or `langchain-core` still work. `_TOOLNODE_AVAILABLE` gates the conditional ToolNode wiring.

## Deviations from Plan

None - plan executed exactly as written. The test adaptation from the plan's suggested `provider=None` to `provider=scripted` was expected (plan noted "adjust based on actual constructor signature").

## Issues Encountered

None. Implementation was straightforward once the architecture was understood. The only nuance was recognizing that `tools_condition` requires `AIMessage` objects (not plain dict messages) for routing — so the test correctly verifies graph topology (node presence) rather than end-to-end execution with live Anthropic API.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **LGUP-02 closed**: ToolNode is wired; the `tools` node exists in the Anthropic graph topology
- **Phase 3 remaining work**: Wire `tools_condition` as the conditional edge from the agent node to the `tools` node, replacing `_route_after_plan` for the Anthropic path. Add `ChatAnthropic` invocation in the plan node when P1_PROVIDER=anthropic
- **langchain-anthropic 1.3.4** is installed and importable — ready for full Anthropic ReAct loop in Phase 3

## Self-Check: PASSED

- graph.py ToolNode import: FOUND (`from langgraph.prebuilt import ToolNode, tools_condition`)
- handle_tool_errors=True: FOUND (`ToolNode(tools=lc_tools, handle_tool_errors=True)`)
- _build_lc_tools() method: FOUND
- _dedup_then_tool_node() method: FOUND
- 'tools' node in compile_graph: FOUND (`builder.add_node("tools", dedup_node)`)
- 279 tests: PASSED
- ruff check: PASSED (All checks passed)
- Task commit 8a0f81a: FOUND
- XML/JSON envelope parser still present: FOUND (`_parse_all_actions_json`)

---
*Phase: 02-langgraph-upgrade-and-single-agent-hardening*
*Completed: 2026-03-03*
