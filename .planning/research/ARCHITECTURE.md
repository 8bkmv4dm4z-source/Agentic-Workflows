# Architecture Patterns: Production LangGraph Multi-Agent System

**Domain:** Graph-based multi-agent orchestration platform
**Researched:** 2026-03-02
**Confidence:** HIGH (LangGraph official docs + GitHub source + verified patterns)

---

## Recommended Architecture

The target architecture is a three-tier hierarchy: a **supervisor graph** that owns the run lifecycle,
**specialist subgraphs** that execute domain-specific work, and a **FastAPI service layer** that wraps
the supervisor as an HTTP endpoint.

```
HTTP Client
    |
    v
FastAPI Service Layer
  - POST /run         → submit mission(s), returns run_id
  - GET  /run/{id}   → poll result
  - GET  /run/{id}/stream  → SSE event stream
    |
    v
Supervisor Graph (LangGraphOrchestrator, existing graph.py)
  plan → execute → policy → finalize
  |
  ├── Executor Subgraph  (new: StateGraph, own schema)
  |     plan_step → tool_dispatch → record_result
  ├── Evaluator Subgraph (new: StateGraph, own schema)
  |     assess → score → recommend
  └── (future) Supervisor Subgraph for mid-level routing
    |
    v
Tools Layer (deterministic Python, no LLM)
  - Tool base class, tools_registry, write_file, sort_array, ...

Observability (cross-cutting)
  - Langfuse CallbackHandler passed in graph.invoke() config
  - @observe() decorators on ChatProvider.generate() and run()
```

### Component Boundaries

| Component | Responsibility | Owns | Does NOT Own |
|-----------|---------------|------|-------------|
| FastAPI service | HTTP lifecycle, request validation, response shaping, SSE | app startup, lifespan, route handlers | Graph logic, state |
| Supervisor graph (`graph.py`) | Top-level plan/execute/policy/finalize, mission tracking, policy enforcement, audit | RunState, MissionReport, audit_report | Subgraph internals |
| Specialist subgraphs | Domain-specific tool execution loop for a single task handoff | SpecialistState (own TypedDict), tools used | RunState, other specialists |
| Model router (`model_router.py`) | Dispatch to strong vs fast ChatProvider by task complexity | Provider selection logic | Tool calls, state |
| Tools layer (`tools/`) | Deterministic computation | Tool.execute() output | Any LLM calls |
| Observability (`observability.py`) | Trace/span emission | @observe() decorator, Langfuse callback | Business logic |

---

## Patterns to Follow

### Pattern 1: Specialist Subgraph as Compiled StateGraph

**What:** Each specialist (executor, evaluator) is an independent `StateGraph` compiled to a
`CompiledGraph`. The supervisor invokes the compiled subgraph inside a node function (not as a
direct `add_node(subgraph)`) when the state schemas have no shared keys.

**Why:** The current `_route_to_specialist` node calls `_execute_action` directly inside
`graph.py`. This is the stub pattern. Real subgraph delegation moves specialist logic into its
own StateGraph with its own nodes, edges, and state schema. The parent graph sees the subgraph
as a black box, receiving only output keys it cares about.

**When:** State schemas differ between parent and specialist (the common case — supervisor needs
`RunState`; executor only needs task + tool result).

**Pattern:**
```python
# specialist_executor.py  (new file)
class ExecutorState(TypedDict):
    task: str
    allowed_tools: list[str]
    tool_result: dict | None
    error: str | None

def build_executor_subgraph(tools_registry) -> CompiledGraph:
    builder = StateGraph(ExecutorState)
    builder.add_node("dispatch", dispatch_tool_node)
    builder.add_node("record", record_result_node)
    builder.add_edge(START, "dispatch")
    builder.add_conditional_edges("dispatch", route_dispatch)
    builder.add_edge("record", END)
    return builder.compile()

# Inside LangGraphOrchestrator._route_to_specialist():
def _route_to_specialist(self, state: RunState) -> RunState:
    specialist = self._select_specialist_for_action(action)
    subgraph = self._subgraphs[specialist]          # pre-compiled at __init__
    subgraph_input = self._build_specialist_input(state, action, specialist)
    subgraph_output = subgraph.invoke(subgraph_input)
    return self._merge_specialist_output(state, subgraph_output)
```

**Build prerequisite:** The supervisor graph's `_route_to_specialist` method must be refactored
before subgraphs can be plugged in. The current `execute` node does everything inline; extracting
the specialist boundary is the critical first step.

**Confidence:** HIGH — pattern matches official LangGraph hierarchical agent teams documentation.

---

### Pattern 2: Map-Reduce via Send() for Parallel Missions

**What:** When multiple missions arrive (multi-mission workload), use LangGraph's `Send()` API
to dispatch them to a specialist node in parallel rather than running them sequentially in a loop.

**When:** Multi-mission prompts (existing `StructuredPlan` already parses them). Currently
missions run sequentially inside the `plan → execute` loop. True parallelism needs `Send()`.

**Pattern:**
```python
from langgraph.types import Send

def fan_out_missions(state: RunState) -> list[Send]:
    """Map phase: one Send per mission."""
    return [
        Send("execute_mission", {"mission": m, "run_id": state["run_id"]})
        for m in state["structured_plan"]["missions"]
    ]

def merge_mission_results(state: RunState) -> RunState:
    """Reduce phase: collect results from all parallel branches."""
    # state["mission_reports"] is a list with Annotated[list, operator.add] reducer
    return state

builder.add_conditional_edges(START, fan_out_missions)
builder.add_edge("execute_mission", "merge")
```

**State requirement:** The `mission_reports` field on `RunState` must use `Annotated[list,
operator.add]` as its reducer so parallel updates merge correctly rather than overwriting.

**Pitfall:** Without an explicit reducer, parallel branches write to the same key and last-write
wins, silently dropping mission results. This is the primary cause of "dropped results" in the
current sequential implementation when timing issues occur.

**Confidence:** HIGH — official LangGraph map-reduce how-to, December 2025 documentation.

---

### Pattern 3: Shared State Keys for Supervisor-Specialist Communication

**What:** For the `messages` channel (and other shared keys), the parent graph and subgraph can
share a key directly when both state schemas include that key. LangGraph merges updates on
shared keys automatically.

**When to use shared keys:** When the specialist needs to see conversation history or partial
results from the supervisor. For this project: `mission_id` and `allowed_tools` are natural
pass-through keys.

**When to use node-function invocation (no shared keys):** When specialist state is private
(e.g., internal retry counter, scratch variables). Use this for executor and evaluator to keep
RunState clean.

**Decision for this project:** Invoke subgraphs inside node functions (no shared keys). The
supervisor maintains RunState; specialist receives a slimmed `TaskHandoff` dict and returns a
`HandoffResult` dict. `_merge_specialist_output()` translates back.

**Confidence:** HIGH — LangGraph subgraph documentation, verified against forum discussions.

---

### Pattern 4: FastAPI Lifespan for Graph Initialization

**What:** Compile the supervisor graph once at application startup inside FastAPI's `lifespan`
async context manager and store it on `app.state`. Route handlers retrieve it via
`request.app.state.graph`. Never compile the graph per-request.

**Why:** Compiling a `StateGraph` is expensive (validation, edge resolution). Doing it per
request adds 50-200ms latency and wastes memory.

**Pattern:**
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    checkpointer = AsyncSqliteSaver.from_conn_string("./runs.db")
    orchestrator = LangGraphOrchestrator(provider=build_provider(), ...)
    app.state.orchestrator = orchestrator
    app.state.checkpointer = checkpointer
    yield
    # Shutdown
    await checkpointer.conn.close()

app = FastAPI(lifespan=lifespan)

@app.post("/run")
async def submit_run(request: RunRequest, req: Request):
    orchestrator = req.app.state.orchestrator
    result = await asyncio.to_thread(orchestrator.run, request.mission)
    return RunResponse(run_id=result["run_id"], ...)
```

**Confidence:** HIGH — FastAPI official lifespan docs + community pattern for LangGraph production.

---

### Pattern 5: SSE Streaming from Graph Events

**What:** Expose a `/run/{id}/stream` endpoint that streams LangGraph node transitions as
Server-Sent Events using `astream_events(version="v2")`.

**Why:** Callers need progress visibility for long-running multi-mission runs. SSE works over a
single long-lived HTTP connection; no WebSocket complexity required.

**Pattern:**
```python
from fastapi.responses import StreamingResponse

@app.get("/run/{run_id}/stream")
async def stream_run(run_id: str, req: Request):
    orchestrator = req.app.state.orchestrator
    config = {"configurable": {"thread_id": run_id}}

    async def event_generator():
        async for event in orchestrator.compiled.astream_events(
            None, config=config, version="v2"
        ):
            node = event.get("metadata", {}).get("langgraph_node", "unknown")
            yield f"data: {json.dumps({'node': node, 'type': event['event']})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

**Key event fields:** `event["metadata"]["langgraph_node"]`, `event["metadata"]["langgraph_path"]`,
`event["event"]` (e.g., `"on_chain_start"`, `"on_tool_end"`).

**Pitfall:** `astream_events` only works on an already-running graph checkpoint OR must be
invoked fresh. For polling-style APIs (submit → poll), prefer `ainvoke` in a background task and
store the result. Only use `astream_events` for the streaming endpoint.

**Confidence:** HIGH — official LangGraph streaming docs, verified with astream_events v2 spec.

---

### Pattern 6: Langfuse Observability via Callback Handler

**What:** Pass a `CallbackHandler` from Langfuse to the graph invocation config. This
automatically traces all node transitions, LLM calls, and tool executions without modifying
node code.

**Pattern:**
```python
from langfuse.callback import CallbackHandler

langfuse_handler = CallbackHandler(
    public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
    secret_key=os.environ["LANGFUSE_SECRET_KEY"],
)

# In orchestrator.run():
result = self._compiled.invoke(
    state,
    config={
        "recursion_limit": self.max_steps * 3,
        "callbacks": [langfuse_handler],
    }
)
```

**For custom spans** (e.g., the `@observe()` decorator on `ChatProvider.generate()`), the
decorator approach works independently and emits spans to Langfuse. Both approaches can
coexist: the callback handler covers graph-level tracing; `@observe()` covers provider-level
spans with custom metadata (token counts, model name, latency).

**Integration point:** The `observability.py` module should expose:
1. `get_langfuse_callback()` → returns `CallbackHandler | None` (None if keys not configured)
2. `observe()` decorator → wraps async or sync function with a Langfuse span

**Confidence:** HIGH — Langfuse official LangGraph integration guide, verified against Langfuse docs.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Specialist Logic Inline in Graph Nodes

**What:** Keeping `_execute_action`, `_select_specialist_for_action`, and tool dispatch all
inside `graph.py`.

**Why bad:** `graph.py` is already ~1700 lines. Adding real subgraph logic without extraction
makes it unmaintainable. Specialist logic cannot be tested in isolation. Cannot be parallelized
with `Send()` without major refactor.

**Instead:** Extract each specialist as its own `StateGraph` in `specialist_executor.py`,
`specialist_evaluator.py`. Keep `graph.py` as the supervisor only — it orchestrates but does not
execute.

---

### Anti-Pattern 2: Compiling Subgraphs Per Request

**What:** Creating and compiling `StateGraph` objects inside request handlers or inside the
`_route_to_specialist` node.

**Why bad:** Compilation is expensive. Multi-mission workloads would recompile the same
subgraph dozens of times per run.

**Instead:** Compile all subgraphs once in `LangGraphOrchestrator.__init__()` and store in
`self._subgraphs: dict[str, CompiledGraph]`.

---

### Anti-Pattern 3: No Reducer on Parallel-Written State Fields

**What:** Using a plain `list` type annotation on `mission_reports` or `tool_history` in
`RunState` when parallel `Send()` branches write to those fields.

**Why bad:** Last writer wins. Mission results are silently dropped. This is undetectable
without the auditor — the state looks complete but has missing data.

**Instead:** Use `Annotated[list[MissionReport], operator.add]` for any field written by
parallel branches.

---

### Anti-Pattern 4: Graph Reuse Across Thread IDs Without Checkpointer

**What:** Invoking the same compiled graph with different `thread_id` values without a
checkpointer.

**Why bad:** Without a checkpointer, `thread_id` is meaningless — all runs share the same
in-memory state. Two concurrent API requests corrupt each other's `RunState`.

**Instead:** Always compile with a checkpointer (`SqliteSaver` for dev, `PostgresSaver` for
production). Each API request gets a unique `run_id` as its `thread_id`.

---

### Anti-Pattern 5: Synchronous graph.invoke() in FastAPI Async Handler

**What:** Calling `orchestrator.run()` (which calls `self._compiled.invoke()` synchronously)
directly inside an `async def` route handler.

**Why bad:** Blocks the FastAPI event loop. Under load, concurrent requests queue behind the
running graph. A 10-second run blocks all other requests for 10 seconds.

**Instead:** Use `await asyncio.to_thread(orchestrator.run, ...)` to offload to a thread pool,
or migrate `graph.py` to use `ainvoke()` and make the orchestrator async-native.

---

## Component Build Order

This is the critical sequencing for the milestone roadmap. Each row depends on the rows above.

| Order | Component | Builds On | Unlocks |
|-------|-----------|-----------|---------|
| 1 | LangGraph upgrade (remove `<1.0` pin) | Nothing | `ToolNode`, `tools_condition`, `langchain-anthropic` |
| 2 | `SpecialistState` TypedDicts (executor, evaluator) | State schema knowledge | Subgraph definitions |
| 3 | Specialist subgraph builders (`build_executor_subgraph`, `build_evaluator_subgraph`) | SpecialistState, tools_registry | Real delegation |
| 4 | `RunState` reducer annotations (`Annotated[list, operator.add]`) on parallel-written fields | LangGraph 1.0 | Safe parallel execution |
| 5 | `_route_to_specialist` refactor in `graph.py` (invoke compiled subgraph, merge output) | Steps 2, 3, 4 | Specialist delegation live |
| 6 | `Send()` fan-out for multi-mission parallelism | Step 5, Step 4 | True parallel missions |
| 7 | Observability wiring (`get_langfuse_callback()`, `@observe()` on provider/run) | Step 5 | Full trace visibility |
| 8 | FastAPI lifespan + `/run` POST + `/run/{id}` GET | Step 5 | HTTP access |
| 9 | FastAPI `/run/{id}/stream` SSE endpoint | Step 8 + LangGraph `ainvoke` migration | Streaming |
| 10 | Containerization (Dockerfile, docker-compose) | Step 8 | Deployable artifact |
| 11 | CI pipeline (lint, typecheck, test) | Step 10 | Automated quality gates |
| 12 | Stress testing framework | Step 10 | Load + failure validation |

**Critical path:** Steps 1 → 2 → 3 → 4 → 5 are purely sequential. Steps 6, 7, and 8 can run
in parallel after step 5. Steps 9, 10, 11, 12 can overlap with each other after step 8.

---

## State Flow Across Subgraph Boundaries

```
Supervisor graph RunState
  ├── structured_plan: dict          # StructuredPlan from mission_parser
  ├── pending_action_queue: list[dict]
  ├── mission_reports: list[MissionReport]
  ├── tool_history: list[ToolRecord]
  ├── handoff_queue: list[dict]      # TaskHandoff records (audit trail)
  ├── handoff_results: list[dict]    # HandoffResult records (audit trail)
  ├── active_specialist: str
  └── audit_report: dict | None

When _route_to_specialist fires:
  1. Supervisor extracts action from pending_action_queue
  2. Builds TaskHandoff (task, specialist, allowed_tools, context_snapshot)
  3. Builds ExecutorState from TaskHandoff  ← BOUNDARY: supervisor → specialist
  4. Calls executor_subgraph.invoke(ExecutorState)
  5. Receives ExecutorState back with tool_result, error
  6. Builds HandoffResult from ExecutorState  ← BOUNDARY: specialist → supervisor
  7. Appends HandoffResult to handoff_results
  8. Updates mission_reports, tool_history from HandoffResult
  9. Returns updated RunState

ExecutorState (internal to specialist subgraph — never stored in RunState directly)
  ├── task: str
  ├── allowed_tools: list[str]
  ├── tool_name: str | None
  ├── tool_args: dict | None
  ├── tool_result: dict | None
  ├── error: str | None
  └── retry_count: int
```

**Key invariant:** `tool_history` (with args) lives on `RunState` and is populated by the
supervisor from `HandoffResult`. The specialist subgraph never writes directly to `RunState`.
This preserves the existing "tool_history is source of truth for args" convention.

---

## Scalability Considerations

| Concern | Dev (SQLite) | Staging (Postgres) | Production (Postgres + workers) |
|---------|-------------|-------------------|--------------------------------|
| Checkpointer | SqliteSaver sync | AsyncPostgresSaver | AsyncPostgresSaver + connection pool |
| Concurrency | Single process, thread pool | Multiple uvicorn workers | K8s pods + shared DB |
| Graph compilation | Once at startup | Once per process | Once per process |
| Mission parallelism | Send() threads in same process | Send() threads in same process | Same (LangGraph manages) |
| Observability | Langfuse local or cloud | Langfuse cloud | Langfuse cloud + alerting |
| LLM timeouts | P1_PROVIDER_TIMEOUT_SECONDS env | Same + retry | Same + circuit breaker |

---

## Sources

- [LangGraph Hierarchical Agent Teams](https://langchain-ai.github.io/langgraph/tutorials/multi_agent/hierarchical_agent_teams/) — HIGH confidence
- [LangGraph Agent Supervisor Tutorial](https://langchain-ai.github.io/langgraph/tutorials/multi_agent/agent_supervisor/) — HIGH confidence
- [LangGraph Subgraphs Documentation](https://docs.langchain.com/oss/python/langgraph/use-subgraphs) — HIGH confidence
- [LangGraph Map-Reduce How-To (JS, same API)](https://langchain-ai.github.io/langgraphjs/how-tos/map-reduce/) — HIGH confidence
- [LangGraph Send API: Map-Reduce in Python (Dec 2025)](https://medium.com/ai-engineering-bootcamp/map-reduce-with-the-send-api-in-langgraph-29b92078b47d) — MEDIUM confidence
- [LangGraph Command for Multi-Agent Routing](https://blog.langchain.com/command-a-new-tool-for-multi-agent-architectures-in-langgraph/) — HIGH confidence
- [Langfuse LangGraph Integration](https://langfuse.com/guides/cookbook/integration_langgraph) — HIGH confidence
- [Langfuse LangGraph Cookbook](https://langfuse.com/guides/cookbook/example_langgraph_agents) — HIGH confidence
- [FastAPI Production-Ready LangGraph Template](https://github.com/wassim249/fastapi-langgraph-agent-production-ready-template) — MEDIUM confidence
- [FastAPI LangGraph Production Guide (Zestminds)](https://www.zestminds.com/blog/build-ai-workflows-fastapi-langgraph/) — MEDIUM confidence
- [FastAPI Lifespan Events (official)](https://fastapi.tiangolo.com/advanced/events/) — HIGH confidence
- [LangGraph Streaming (SSE, astream_events v2)](https://docs.langchain.com/oss/python/langgraph/streaming) — HIGH confidence
- [Scaling LangGraph: Parallelization, Subgraphs, Map-Reduce Tradeoffs](https://aipractitioner.substack.com/p/scaling-langgraph-agents-parallelization) — MEDIUM confidence
- [LangGraph v1 Migration Guide](https://docs.langchain.com/oss/python/migrate/langgraph-v1) — HIGH confidence
- [LangGraph Checkpoint Persistence](https://pypi.org/project/langgraph-checkpoint/) — HIGH confidence
- [langgraph-supervisor PyPI](https://pypi.org/project/langgraph-supervisor/) — HIGH confidence (official)
