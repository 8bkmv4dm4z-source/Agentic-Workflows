# Phase 2: LangGraph Upgrade and Single-Agent Hardening - Context

**Gathered:** 2026-03-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Remove the `langgraph<1.0` pin, adopt `ToolNode`/`tools_condition` via `langchain-anthropic`, add `Annotated[list[T], operator.add]` reducers to all `RunState` list fields, implement message history compaction, wire `@observe()` on `run()` and `provider.generate()`, establish `docs/ADR/` with the first ADR, and add a GitHub Actions CI pipeline. No multi-agent work enters this phase.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion

All implementation areas delegated to Claude based on research findings. Constraints below are hard requirements; everything else is Claude's call.

### Provider Migration Strategy
- **Keep `ChatProvider` protocol and `ScriptedProvider` in place** — they are the test safety net for all 208 existing tests and must not be removed
- Add `langchain-anthropic` as a parallel path alongside `ChatProvider`, not a replacement
- `ScriptedProvider` remains the default for all tests; no live LLM calls in the test suite
- The XML/JSON envelope parser in `graph.py` can be retired only for the Anthropic path once `ToolNode` is confirmed working

### ToolNode Scope
- **Anthropic path first** — wire `langchain-anthropic` + `ToolNode` for the Anthropic provider only in Phase 2
- OpenAI and Groq provider paths stay on the existing `ChatProvider` pattern for now
- Ollama (primary dev provider) stays on existing pattern — Ollama does not need langchain-anthropic
- Rationale: one migration at a time; Anthropic path has the most parser fragility

### RunState Reducers
- All four plain list fields must get `Annotated[list[T], operator.add]` reducers: `tool_history`, `mission_reports`, `memo_events`, `seen_tool_signatures`
- **`ensure_state_defaults()` must remain** — it repairs state at each node entry and is independent of reducer annotations
- Add an integration test that asserts no branch results are dropped after a two-branch merge
- Existing sequential tests must pass unchanged after reducer annotations are added

### Message Compaction
- **Sliding window / drop oldest** — when `messages` list exceeds 40 entries, drop the oldest messages to bring it back to the threshold
- No LLM summarization (adds latency and a live-LLM dependency in what should be deterministic state management)
- Threshold is configurable via env var `P1_MESSAGE_COMPACTION_THRESHOLD` (default 40)
- Compaction fires at node entry in `ensure_state_defaults()` so it is automatic and centralized

### Observability Wiring
- `@observe()` decorator goes on `run()` in `run.py` and `generate()` in `provider.py`
- The existing `observability.py` graceful-degradation stub is already correct — just wire the decorator
- Langfuse `CallbackHandler` is Phase 5 (graph-level tracing); Phase 2 only closes the open `@observe()` item
- No Langfuse account required in CI — graceful degradation means it's a no-op when `LANGFUSE_PUBLIC_KEY` is absent

### ADR Log
- Location: `docs/ADR/` directory, one file per decision
- Format: simple markdown with sections: **Status**, **Context**, **Decision**, **Consequences**
- First ADR: `ADR-001-langgraph-version-upgrade.md` documenting the `<1.0` pin removal
- Each subsequent significant architectural decision in Phase 2 gets its own ADR

### CI Pipeline
- **Full suite gate**: `ruff check src/ tests/` + `mypy src/` + `pytest tests/ -q` — all three must pass
- Uses `ScriptedProvider` — zero live LLM calls, no provider API keys required in CI secrets
- Trigger: push to any branch + pull request to `main`
- File: `.github/workflows/ci.yml` (separate from existing `claude.yml`)
- Python version: 3.12 (matches dev environment)
- No caching in v1 — keep it simple, add pip cache in Phase 7

### LangGraph Upgrade Safety
- Set `handle_tool_errors=True` explicitly when constructing `ToolNode` (langgraph-prebuilt >=1.0.1 disables this by default — GitHub Issue #6486)
- Pin to `langgraph==1.0.6, langgraph-prebuilt==1.0.1` initially (stable combination confirmed in research), then move to latest after 208 tests pass
- `seen_tool_signatures` deduplication logic must be preserved — `ToolNode` has no built-in deduplication

</decisions>

<specifics>
## Specific Ideas

- User wants free toolchain throughout: Ollama for LLM, Langfuse free/self-hosted for observability, GitHub Actions free tier for CI
- User wants the development process itself to be educational: each refactor should be documented so they understand what changed and why
- The ADR log is part of the learning system — it makes architectural decisions explicit and reviewable
- Research confirmed: LangGraph 1.0 is backwards-compatible with 0.2.x; the 208-test suite is the regression safety net

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `observability.py`: `@observe()` decorator stub already exists with graceful degradation — just apply it to `run()` and `generate()`
- `ScriptedProvider`: existing test double for all 208 tests — must be preserved as-is
- `ensure_state_defaults()` in `state_schema.py`: natural home for message compaction logic (fires at every node entry)
- `.github/workflows/claude.yml`: existing workflow file — add `ci.yml` separately, don't modify this one

### Established Patterns
- `ChatProvider` Protocol: all providers implement `generate() → JSON`; `ToolNode` integration is additive alongside this, not a replacement
- `tool_history` as source of truth for args: `tool_results` inside `mission_reports` intentionally excludes args — reducer annotations must not change this contract
- Recursion limit = `max_steps × 3`: do not raise `max_steps` to fix any recursion errors during upgrade

### Integration Points
- `graph.py` `_execute_tool()` and `_handle_tool_calls()`: where XML/JSON envelope parsing lives — this is what `ToolNode` replaces for the Anthropic path
- `provider.py` `generate()`: where `@observe()` goes
- `run.py` `run()`: where outer `@observe()` span goes
- `state_schema.py` `RunState` TypedDict + `ensure_state_defaults()`: where reducer annotations and compaction go

</code_context>

<deferred>
## Deferred Ideas

- Langfuse `CallbackHandler` for graph-level node tracing — Phase 5
- OpenAI and Groq provider paths to `ToolNode` — future phase
- Human-in-the-loop `interrupt()` API — v2 requirements
- Parallel mission `Send()` map-reduce — Phase 4 (after reducers are in place)
- Stress testing framework — v2 requirements

</deferred>

---

*Phase: 02-langgraph-upgrade-and-single-agent-hardening*
*Context gathered: 2026-03-02*
