# Phase 08: Multi-Model SYCL Routing and Planner Bottleneck Resolution — Feature Context

**Mode:** Extend
**Feature:** retrieve_tool_result tool — planner-callable cache retrieval with chunking
**Gathered:** 2026-03-11
**Status:** Ready for planning

<domain>
## Feature Boundary

Phase 08 scope: Resolve planner context bottleneck via ToolResultCache offloading (BTLNK-01/02).

This feature: Completes BTLNK-01 by adding the missing retrieval side — a `retrieve_tool_result`
tool the planner can call using the key from a compact pointer, with offset/limit chunking for
large results that don't fit in a single context window injection.

Does NOT extend phase scope. Does NOT modify ROADMAP.md.

</domain>

<decisions>
## Implementation Decisions

### Tool API
- Tool name: `retrieve_tool_result`
- Args: `key` (str, required) + `offset` (int, default 0) + `limit` (int, default 3000)
- Key comes directly from the pointer already injected by ContextManager — planner doesn't need to re-hash
- Returns: `{"result": "<chunk>", "offset": 0, "limit": 3000, "total": 7580, "has_more": true}`

### Cache Miss Behavior
- On miss (expired or unknown key): return `{"error": "cache miss — result expired or not found"}`
- Planner interprets this as a signal to re-run the original tool
- No silent empty returns

### ContextManager Pointer Format
All four elements included in the pointer injected to the planner:

```
[Result truncated — 7580 chars stored | chunks: 3000 chars each]
Tool: list_directory | Key: abc12345
Summary: 42 .py files in tools/
→ call retrieve_tool_result(key="abc12345", offset=0, limit=3000) to read full result
```

Locked fields:
- **Cache key** — required, the hash to pass to the tool
- **Total size hint** — `7580 chars stored` so planner knows total pages needed
- **Content summary** — short description (the existing Summary: line) so planner can decide if full retrieval is needed
- **Suggested chunk size** — `3000 chars each` tells planner the limit= value to use

### Tool Registration
- New file: `src/agentic_workflows/tools/retrieve_tool_result.py`
- Class: `RetrieveToolResultTool` with `execute(args)` method (follows existing tool base pattern)
- Register in tool registry (wherever list_directory, read_file etc. are registered)
- Tool should be listed in the planner's tool schema so it appears in JSON schema hints

### Claude's Discretion
- Whether `retrieve_tool_result` uses `ToolResultCache` directly or goes through a shared accessor
- Whether the pointer format update is a constant or a formatted f-string in context_manager.py
- TTL/expiry handling: if result expired mid-session, whether to log a warning in addition to returning the error dict

</decisions>

<acceptance_criteria>
## Done When

- [ ] `retrieve_tool_result` tool file exists and is registered in the tool registry
- [ ] Tool takes `key`, `offset`, `limit`; returns chunk dict with `result`, `offset`, `limit`, `total`, `has_more`
- [ ] Cache miss returns `{"error": "cache miss — result expired or not found"}`
- [ ] ContextManager pointer includes all four elements: key, total size, summary, suggested chunk size
- [ ] Planner can call the tool using the key from the pointer and receive the stored result
- [ ] Unit tests cover: successful retrieval, chunked retrieval (has_more=True/False), cache miss, pool=None no-op
- [ ] Existing 1594 tests still pass (no regressions)
- [ ] ruff clean on all modified files

</acceptance_criteria>

<deferred>
## Deferred Ideas

- Auto-paging: planner auto-iterates all chunks without needing to call retrieve_tool_result multiple times
- Cache warming: pre-store known-large tool results before the planner even runs
- Key expiry extension: reset TTL when result is retrieved (read-extends-life)

</deferred>

---

*Phase: 08-multi-model-sycl-routing-and-planner-bottleneck-resolution*
*Feature context gathered: 2026-03-11*
