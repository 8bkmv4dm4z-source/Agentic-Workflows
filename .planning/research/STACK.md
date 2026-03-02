# Technology Stack

**Project:** Agent Phase0 — Multi-Agent Orchestration Platform
**Researched:** 2026-03-02
**Research Mode:** Ecosystem + Upgrade Path
**Overall Confidence:** MEDIUM-HIGH (LangGraph upgrade path HIGH; supporting stack MEDIUM)

---

## Executive Summary

This project needs to evolve from a pinned `langgraph<1.0` foundation to a full production stack.
LangGraph 1.0 released in October 2025 and is now at 1.0.9 as of early 2026. The upgrade is
**largely non-breaking** — the main work is migrating from the custom `ChatProvider` protocol to
`langchain-anthropic` / native provider bindings, adopting `ToolNode` + `tools_condition` from
`langgraph-prebuilt`, and adding a FastAPI service layer, PostgreSQL checkpointing, and Langfuse
observability.

---

## Recommended Stack

### Core Orchestration

| Technology | Target Version | Purpose | Why |
|------------|---------------|---------|-----|
| `langgraph` | `>=1.0.9` | Graph runtime, state machine, checkpoints | v1.0 is stable, no breaking changes from 0.2.x; removes `<1.0` pin that blocks Phase 2 |
| `langgraph-prebuilt` | bundled with langgraph | `ToolNode`, `tools_condition`, `create_react_agent` | Bundled since langgraph 0.3.1; no separate install needed |
| `langchain-core` | `>=0.3` (pulled by langgraph) | Runnable protocol, message types, tool contracts | Required transitive dep; pin not needed unless you use it directly |

**Confidence:** HIGH — verified against PyPI release history and official LangChain blog announcement.

**Upgrade impact on current code:** The `langgraph>=0.2.67,<1.0` pin is the only blocker. Removing it
and updating to `>=1.0.9` is the unlock. LangGraph v1.0 is explicitly documented as backwards-compatible
with v0.2.x; no state schema, graph builder, or node API changes required.

### LLM Provider Bindings

| Technology | Target Version | Purpose | Why |
|------------|---------------|---------|-----|
| `langchain-anthropic` | `>=0.3` | Claude models via LangChain protocol | Needed for `bind_tools()`, `ToolNode` compatibility, and Phase 2 native tool calling |
| `openai` | `>=2.0` (already pinned) | OpenAI models (already integrated) | Keep; ChatProvider protocol wraps it fine today |
| `groq` | `>=1.0` (already pinned) | Groq fast inference | Keep; same wrapper path |

**Confidence:** MEDIUM — `langchain-anthropic` PyPI page confirms active maintenance through Feb 2026.
Exact minimum version for Claude 3.5/3.7 compatibility needs validation against `langchain-anthropic` changelog.

**Why `langchain-anthropic` now:** The current `ChatProvider` protocol does raw `anthropic` SDK calls
and manually parses tool envelopes. `langchain-anthropic` gives `ChatAnthropic.bind_tools()`, which
produces `AIMessage` objects that `ToolNode` can dispatch natively — eliminating the XML/JSON envelope
parsing hacks documented in CLAUDE.md.

**What NOT to use:** Do not pull in `langchain` (the full package) unless forced by a dependency.
LangGraph + `langchain-core` + provider packages is the correct minimal graph. The monolithic
`langchain` package adds 30+ transitive dependencies for features this project doesn't need.

### Structured Output

| Technology | Target Version | Purpose | Why |
|------------|---------------|---------|-----|
| `pydantic` | `>=2.12,<3.0` (already pinned) | Schema validation, state typing, tool arg validation | Already in use; Pydantic 2.x with `model.with_structured_output(MySchema)` is the LangChain-native pattern |

**Confidence:** HIGH — already in project, no change needed.

**Note on `instructor`:** The PROJECT.md mentions `instructor` as a Phase 2 dependency. Research shows
that `model.with_structured_output(PydanticModel)` via `langchain-anthropic` covers the same use case
without an extra library. Reserve `instructor` for cases where you need retry logic on malformed
structured outputs — it is not required for the standard path.

### Service Layer

| Technology | Target Version | Purpose | Why |
|------------|---------------|---------|-----|
| `fastapi` | `>=0.115` | HTTP API surface for mission submission and result retrieval | Standard for Python async services; plays well with LangGraph's async graph interface |
| `uvicorn` | `>=0.34` | ASGI server | FastAPI's standard runtime; production: uvicorn workers managed by gunicorn |
| `python-multipart` | `>=0.0.20` | Form data parsing (if needed for file uploads) | FastAPI optional dep for multipart |

**Confidence:** MEDIUM — FastAPI + uvicorn is industry standard; specific versions pulled from FastAPI docs.

**Why FastAPI, not Flask or bare HTTP:** LangGraph's `astream_events()` produces an async generator.
FastAPI `StreamingResponse` + Server-Sent Events is the idiomatic integration. Flask requires workarounds
to expose async generators. The project is already async-aware (pytest-asyncio in dev deps).

**What NOT to use:** `langgraph-api` (LangGraph Cloud API server) — this is LangGraph's hosted
deployment product; too opinionated and introduces platform lock-in. Build a thin FastAPI wrapper instead.

### Persistence / Checkpointing

| Technology | Dev | Production | Why |
|------------|-----|------------|-----|
| `langgraph-checkpoint-sqlite` | yes (current) | no | Already in use implicitly; fine for single-node dev |
| `langgraph-checkpoint-postgres` | `>=3.0.2` | yes | PostgreSQL for multi-node; `AsyncPostgresSaver` supports connection pools |
| PostgreSQL | 15+ | yes | LangGraph checkpoint table structure tested against PG 15+; asyncpg driver recommended |

**Confidence:** MEDIUM — `langgraph-checkpoint-postgres` 3.0.2 confirmed on PyPI (Dec 2025). Async
adapter requirement verified in LangChain docs.

**Migration path:** SQLite → Postgres is a checkpointer swap only:
```python
# Dev (current)
from langgraph.checkpoint.sqlite import SqliteSaver
checkpointer = SqliteSaver.from_conn_string(":memory:")

# Production
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
import psycopg_pool
pool = psycopg_pool.AsyncConnectionPool(conninfo="postgresql://...")
checkpointer = AsyncPostgresSaver(pool)
await checkpointer.setup()  # creates tables on first run
```

No graph logic changes required — `LangGraphOrchestrator` passes `checkpointer` at compile time.

### Observability

| Technology | Target Version | Purpose | Why |
|------------|---------------|---------|-----|
| `langfuse` | `>=3.0` (already in observability extra) | LLM tracing, span visualization, cost tracking | Open-source, self-hostable, native LangGraph integration via `CallbackHandler`; already chosen |

**Confidence:** HIGH — Langfuse 3.x `CallbackHandler` for LangChain/LangGraph is documented and
actively maintained. Self-hostable via Docker.

**Integration pattern:**
```python
from langfuse.langchain import CallbackHandler
langfuse_handler = CallbackHandler()  # reads LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST

# Pass as config to graph invocation
result = graph.invoke(state, config={"callbacks": [langfuse_handler]})
```

This wires the `@observe()` gap noted in CLAUDE.md: the callback handler automatically traces every
LangGraph node invocation without manual decorator placement.

**LangSmith vs Langfuse:** Do not add LangSmith. It is SaaS-only (no self-hosting), and the project
already has Langfuse in the optional deps. Stick with Langfuse.

### Multi-Agent Coordination

| Technology | Target Version | Purpose | Why |
|------------|---------------|---------|-----|
| Built-in LangGraph subgraphs | — | Specialist agent delegation | Use LangGraph's native `Send()` API and `Command` objects for subgraph routing; no extra library |
| `langgraph-supervisor` | `>=0.0.5` (optional reference) | Supervisor pattern reference | Official LangChain library for hierarchical multi-agent; useful as a reference implementation, but the project's existing routing stub should be built out directly |

**Confidence:** MEDIUM — `langgraph-supervisor` PyPI package confirmed; LangChain now recommends
direct tool-based handoff over the library for production control. The project's existing
`TaskHandoff`/`HandoffResult` TypedDicts and `handoff_queue` state are the right foundation.

**What NOT to use:** Do not use `langgraph-swarm` or experimental multi-agent packages. The graph's
existing `active_specialist` field and `handoff_queue` state are the correct surface for Phase 3.

### Infrastructure / Containerization

| Technology | Target Version | Purpose | Why |
|------------|---------------|---------|-----|
| Docker | 24+ | Container build | Single-stage build from `python:3.12-slim`; no uvicorn-gunicorn base image (deprecated) |
| docker-compose | v2.x | Local multi-container dev | FastAPI + PostgreSQL + Langfuse (optional) |
| gunicorn | `>=23.0` | Production worker manager | `gunicorn -w 4 -k uvicorn.workers.UvicornWorker` for multi-worker ASGI |

**Confidence:** MEDIUM — FastAPI official docs explicitly deprecate the tiangolo uvicorn-gunicorn image
and recommend building from scratch.

**Dockerfile pattern (2025 standard):**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[observability]"
COPY src/ src/
RUN useradd -m appuser && chown -R appuser /app
USER appuser
EXPOSE 8000
CMD ["gunicorn", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", \
     "--timeout", "120", "--bind", "0.0.0.0:8000", \
     "agentic_workflows.api.main:app"]
```

### CI Pipeline

| Technology | Target Version | Purpose | Why |
|------------|---------------|---------|-----|
| GitHub Actions | — | CI runner | Already using GitHub; native integration |
| `ruff` | `>=0.11` (already pinned) | Lint + format | Already in dev deps |
| `mypy` | `>=1.10` (already pinned) | Typecheck | Already in dev deps |
| `pytest` | `>=8.0` (already pinned) | Test runner | Already in dev deps |
| `pytest-asyncio` | `>=0.24` (already pinned) | Async test support | Already in dev deps |
| `httpx` | `>=0.28` (already pinned, in core deps) | FastAPI async test client | `httpx.AsyncClient` + `ASGITransport` is the 2025 standard for testing FastAPI |

**Confidence:** HIGH — all already in project deps; GitHub Actions workflow is the only missing piece.

**CI workflow structure:**
```yaml
# .github/workflows/ci.yml
on: [push, pull_request]
jobs:
  quality:
    steps: [ruff check, ruff format --check, mypy src/]
  test:
    steps: [pytest tests/unit/ -q, pytest tests/integration/ -q]
```

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Graph runtime | `langgraph>=1.0.9` | Stay on 0.2.x | Blocks ToolNode, langchain-anthropic, Phase 2 |
| Graph runtime | LangGraph | CrewAI / AutoGen | LangGraph is already in use; switching would discard 208 tests and all state logic |
| Structured output | Native `with_structured_output()` | `instructor` | Adds a dependency with overlapping functionality; use only if retry-on-parse-failure needed |
| Observability | Langfuse | LangSmith | LangSmith is SaaS-only, no self-hosting; Langfuse already chosen |
| Persistence | PostgreSQL (`langgraph-checkpoint-postgres`) | Redis (`langgraph-redis`) | Redis optimized for sub-ms latency at agent-swarm scale; this project does not need sub-ms checkpoint retrieval; PostgreSQL is simpler and more familiar |
| Service layer | FastAPI | `langgraph-api` (LangGraph Cloud) | Cloud product, no self-hosting, platform lock-in |
| Provider binding | `langchain-anthropic` | Raw `anthropic` SDK | Raw SDK requires manual tool-call envelope parsing (documented bug in CLAUDE.md); `langchain-anthropic.bind_tools()` + ToolNode eliminates this entirely |
| Container base | Build from scratch | `tiangolo/uvicorn-gunicorn-fastapi` | Image is deprecated by author; building from `python:3.12-slim` is the current recommendation |

---

## Upgrade Path: `langgraph<1.0` to `langgraph>=1.0`

This is the critical unblock for Phases 2-4.

### Step 1: Remove the upper-bound pin (pyproject.toml)

```toml
# Before
"langgraph>=0.2.67,<1.0",

# After
"langgraph>=1.0.9",
"langchain-anthropic>=0.3",
```

**Risk:** LOW. LangGraph 1.0 is explicitly documented as backwards-compatible with 0.2.x.
The only deprecation is `create_react_agent` moving from `langgraph.prebuilt` to
`langchain.agents` — which this project does not use.

### Step 2: Add `langchain-anthropic` and adopt `ToolNode`

The current `ChatProvider` protocol wraps the raw `anthropic` SDK. For Phase 2, add `ChatAnthropic`
as an alternative provider that speaks the LangGraph-native message protocol:

```python
# Phase 2: native ToolNode path for Anthropic
from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import ToolNode, tools_condition

model = ChatAnthropic(model="claude-opus-4-6").bind_tools(tool_list)
tool_node = ToolNode(tool_list)

builder.add_node("agent", lambda state: {"messages": [model.invoke(state["messages"])]})
builder.add_node("tools", tool_node)
builder.add_conditional_edges("agent", tools_condition)
builder.add_edge("tools", "agent")
```

The existing `ChatProvider` protocol and `ScriptedProvider` (used in integration tests) can be
kept for non-Anthropic paths and testing — they do not conflict with the new path.

### Step 3: Migrate tool envelope parsing

The documented `JSON contract violations` (XML-ish envelopes from some providers) are handled by
`ToolNode` natively when using `langchain-anthropic`. The manual parser in `graph.py` that
"recovers first balanced JSON object" can be retired for the Anthropic path once `langchain-anthropic`
is the provider. Keep it for Groq/Ollama paths where raw SDK calls remain.

### Step 4: Validate with existing test suite

Run `pytest tests/ -q` after the pin change. With 208 tests passing on the current stack, any
regression will be caught immediately. LangGraph's backwards compatibility guarantee means no
graph logic should break.

---

## Installation

### Core upgrade

```bash
# 1. Update pyproject.toml as shown above
# 2. Reinstall
pip install -e ".[dev,observability]"

# 3. Add new deps
pip install langchain-anthropic>=0.3 fastapi>=0.115 uvicorn>=0.34 gunicorn>=23.0
pip install langgraph-checkpoint-postgres>=3.0.2 psycopg[pool]>=3.2
```

### Full production stack

```bash
pip install -e ".[dev,observability]"
pip install langchain-anthropic fastapi uvicorn[standard] gunicorn
pip install langgraph-checkpoint-postgres "psycopg[pool]"
pip install langfuse>=3.0
```

### For Phase 3 multi-agent reference

```bash
pip install langgraph-supervisor  # reference only; build handoff natively
```

---

## Version Summary Table

| Package | Current Pin | Target Pin | Change |
|---------|-------------|------------|--------|
| `langgraph` | `>=0.2.67,<1.0` | `>=1.0.9` | Remove upper bound — critical unblock |
| `langchain-anthropic` | not installed | `>=0.3` | New — enables ToolNode + native tool calling |
| `fastapi` | not installed | `>=0.115` | New — service layer |
| `uvicorn` | not installed | `>=0.34` | New — ASGI server |
| `gunicorn` | not installed | `>=23.0` | New — production worker manager |
| `langgraph-checkpoint-postgres` | not installed | `>=3.0.2` | New — production persistence |
| `psycopg[pool]` | not installed | `>=3.2` | New — async PostgreSQL driver |
| `langfuse` | `>=3.0` (observability extra) | `>=3.0` | Already correct; promote to default |
| `pydantic` | `>=2.12,<3.0` | unchanged | No change |
| `openai` | `>=2.0` | unchanged | No change |
| `groq` | `>=1.0` | unchanged | No change |
| `httpx` | `>=0.28` | unchanged | Doubles as FastAPI test client |
| `pytest` | `>=8.0` | unchanged | No change |
| `pytest-asyncio` | `>=0.24` | unchanged | No change |
| `ruff` | `>=0.11` | unchanged | No change |
| `mypy` | `>=1.10` | unchanged | No change |

---

## Confidence Assessment

| Area | Confidence | Reason |
|------|------------|--------|
| LangGraph upgrade path | HIGH | PyPI confirms 1.0.9 latest; LangChain blog explicitly states backwards compatibility with 0.2.x |
| `langchain-anthropic` addition | MEDIUM | Package active on PyPI; exact minimum version for Claude 3.5/3.7 needs validation against changelog |
| FastAPI service layer | MEDIUM | Industry standard; specific version numbers from FastAPI docs, not lab-tested against this codebase |
| PostgreSQL checkpointing | MEDIUM | `langgraph-checkpoint-postgres` 3.0.2 confirmed; AsyncPostgresSaver API from LangChain docs |
| Langfuse integration | HIGH | Already chosen; `CallbackHandler` import path confirmed from Langfuse docs |
| CI workflow | HIGH | All tools already installed; GitHub Actions structure is standard |
| Subgraph multi-agent | MEDIUM | `Send()` API and `Command` pattern confirmed in LangGraph docs; integration with existing handoff schema untested |
| Docker/container pattern | MEDIUM | FastAPI official docs confirm base image deprecation; exact Dockerfile untested |

---

## Sources

- [LangGraph PyPI - version 1.0.9](https://pypi.org/project/langgraph/)
- [LangChain & LangGraph 1.0 announcement blog](https://blog.langchain.com/langchain-langgraph-1dot0/)
- [LangGraph v1 migration guide](https://docs.langchain.com/oss/python/migrate/langgraph-v1)
- [langgraph-prebuilt PyPI](https://pypi.org/project/langgraph-prebuilt/)
- [langchain-anthropic PyPI](https://pypi.org/project/langchain-anthropic/)
- [langgraph-checkpoint-postgres PyPI](https://pypi.org/project/langgraph-checkpoint-postgres/)
- [Langfuse LangGraph integration guide](https://langfuse.com/guides/cookbook/integration_langgraph)
- [Langfuse LangChain CallbackHandler docs](https://langfuse.com/integrations/frameworks/langchain)
- [FastAPI Docker deployment docs](https://fastapi.tiangolo.com/deployment/docker/)
- [LangGraph Supervisor library](https://github.com/langchain-ai/langgraph-supervisor-py)
- [FastAPI + LangGraph streaming production template](https://github.com/wassim249/fastapi-langgraph-agent-production-ready-template)
- [LangGraph persistence/checkpointing docs](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph hierarchical agent teams tutorial](https://langchain-ai.github.io/langgraph/tutorials/multi_agent/hierarchical_agent_teams/)
- [FastAPI async testing with httpx](https://fastapi.tiangolo.com/advanced/async-tests/)
