# ADR-001: Remove langgraph<1.0 Version Pin

**Status:** Accepted
**Date:** 2026-03-02

## Context
The `langgraph<1.0` pin was added during Phase 1 to maintain stability while the
LangGraph 1.0 API surface stabilized. Phase 2 requires `ToolNode`, `tools_condition`,
and `Annotated` reducer annotations — all of which are only available in langgraph>=1.0.
The pin became the master blocker for the entire roadmap.

## Decision
Remove the `langgraph<1.0` pin. Pin to `langgraph>=1.0.6,<2.0` and
`langgraph-prebuilt>=1.0.1,<1.0.2` (stable combination: prebuilt 1.0.2 broke the
`ToolNode.afunc` signature — GitHub Issue #6363). Add `langchain-anthropic>=0.3.0`
as a new dependency required for the Anthropic ToolNode path.

## Consequences
- ToolNode and tools_condition become available from langgraph-prebuilt
- Annotated reducer syntax is supported for RunState list fields
- langgraph-prebuilt is pinned to 1.0.1 (not 1.0.2+) until the afunc fix is confirmed in a higher version
- All 208 existing tests must pass unchanged — LangGraph 1.0 is backwards-compatible with 0.2.x APIs used in this codebase
- Upgrade is applied in isolation (no behavioral changes in the same commit)
