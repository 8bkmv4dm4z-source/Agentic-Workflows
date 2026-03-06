# ADR-002: ToolNode Adoption — Anthropic Path Only

**Status:** Accepted
**Date:** 2026-03-02

## Context
The manual XML/JSON envelope parser in `graph.py` (`_execute_tool()`, `_handle_tool_calls()`)
is the most fragile part of the Phase 1 codebase. LangGraph 1.0 provides `ToolNode` from
`langgraph-prebuilt` as a standard, well-tested replacement that handles format differences
across providers. However, migrating all three provider paths at once increases risk of
regressions and testing complexity.

## Decision
Adopt `ToolNode` + `tools_condition` for the Anthropic provider path only in Phase 2.
Ollama (primary dev provider), OpenAI, and Groq stay on the existing `ChatProvider` pattern.
The `langchain-anthropic` `ChatAnthropic` binding is used for Anthropic to produce tool-call
messages in the format ToolNode expects. `ToolNode` is always constructed with
`handle_tool_errors=True` (default in prebuilt 1.0.1 is `False` — GitHub Issue #6486).

## Consequences
- XML/JSON envelope parser is retired for the Anthropic path; remains active for other paths
- `ScriptedProvider` and all 208 existing tests are unaffected (ScriptedProvider is not the Anthropic path)
- `seen_tool_signatures` deduplication must be preserved as a pre-check before ToolNode executes
- OpenAI and Groq ToolNode migration deferred to a future phase
- One migration at a time reduces debugging surface
