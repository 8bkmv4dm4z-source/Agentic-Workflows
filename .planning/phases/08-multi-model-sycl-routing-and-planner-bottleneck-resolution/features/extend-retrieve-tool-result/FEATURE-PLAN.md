---
phase: 08-multi-model-sycl-routing-and-planner-bottleneck-resolution
feature: extend-retrieve-tool-result
type: execute
wave: 1
depends_on: []
files_modified:
  - src/agentic_workflows/tools/retrieve_tool_result.py
  - src/agentic_workflows/orchestration/langgraph/tools_registry.py
  - src/agentic_workflows/orchestration/langgraph/context_manager.py
  - src/agentic_workflows/orchestration/langgraph/planner_helpers.py
  - tests/unit/test_retrieve_tool_result.py
autonomous: true
requirements:
  - BTLNK-01

must_haves:
  truths:
    - "Planner can call retrieve_tool_result(key='abc12345', offset=0, limit=3000) and receive the stored result chunk"
    - "Response includes result, offset, limit, total, has_more — planner knows if more chunks remain"
    - "Cache miss returns {\"error\": \"cache miss — result expired or not found\"} — no silent empty string"
    - "pool=None path returns cache miss error dict without crashing — safe in SQLite/CI"
    - "ContextManager compact pointer includes all four locked elements: key, total size, summary, suggested chunk size"
    - "retrieve_tool_result appears in the planner's tool list and context management rules"
  artifacts:
    - path: "src/agentic_workflows/tools/retrieve_tool_result.py"
      provides: "RetrieveToolResultTool — planner-callable retrieval with offset/limit chunking"
      exports: ["RetrieveToolResultTool"]
    - path: "src/agentic_workflows/orchestration/langgraph/tools_registry.py"
      provides: "retrieve_tool_result registered when tool_result_cache is provided"
      contains: "retrieve_tool_result"
    - path: "src/agentic_workflows/orchestration/langgraph/context_manager.py"
      provides: "Compact pointer updated to include chunks hint and call example"
      contains: "chunks:"
    - path: "tests/unit/test_retrieve_tool_result.py"
      provides: "Unit tests: successful retrieval, chunked has_more, cache miss, pool=None no-op"
  key_links:
    - from: "src/agentic_workflows/orchestration/langgraph/context_manager.py _compact pointer"
      to: "src/agentic_workflows/tools/retrieve_tool_result.py RetrieveToolResultTool.execute()"
      via: "key emitted in pointer matches args_hash stored by ToolResultCache"
      pattern: "args_hash\\[:8\\]"
    - from: "src/agentic_workflows/orchestration/langgraph/tools_registry.py build_tool_registry()"
      to: "src/agentic_workflows/tools/retrieve_tool_result.py RetrieveToolResultTool"
      via: "conditional registration when tool_result_cache param is not None"
      pattern: "retrieve_tool_result"

rollback_notes: |
  All changes are additive. To revert:
  1. Delete src/agentic_workflows/tools/retrieve_tool_result.py
  2. Remove the retrieve_tool_result import and registry entry from tools_registry.py
  3. Revert context_manager.py compact pointer format to the Phase 08-05 format
     (remove "| chunks: {limit} chars each" and the call example line)
  4. Remove the retrieve_tool_result rule from planner_helpers.py context management rules
  5. Delete tests/unit/test_retrieve_tool_result.py
  No database schema changes, no state schema changes, no graph wiring changes.
---

<objective>
Complete BTLNK-01 retrieval side: add `retrieve_tool_result` tool so the planner can fetch stored
large results by key using offset/limit chunking, and update the compact pointer format to include
all four locked elements from FEATURE-CONTEXT.md.

Purpose: The Phase 08-05 BTLNK-01 work wires interception and storage. This feature closes the
loop — the planner can now retrieve what was stored. Without this, compact pointers are dead ends.
Output: RetrieveToolResultTool, registry wiring, updated pointer format, unit tests.
</objective>

<context>
@.planning/phases/08-multi-model-sycl-routing-and-planner-bottleneck-resolution/features/extend-retrieve-tool-result/FEATURE-CONTEXT.md
@.planning/STATE.md

<interfaces>
<!-- Exact code patterns the executor needs. Extracted from codebase. -->

From src/agentic_workflows/storage/tool_result_cache.py:
```python
class ToolResultCache:
    def __init__(self, pool: ConnectionPool | None = None) -> None: ...

    def get(self, *, tool_name: str, args_hash: str) -> str | None:
        """Returns full_result string, or None on miss/expired."""
```

Note: ToolResultCache.get() takes tool_name + args_hash together. The compact pointer only exposes
args_hash[:8] (the key). RetrieveToolResultTool must scan by args_hash prefix OR store the full
key. Since the planner is given args_hash[:8] as the "key" in the pointer, the tool needs to
accept this 8-char prefix and perform a prefix lookup. However, ToolResultCache.get() requires the
full args_hash (64-char SHA-256 hex). Two design options:

  Option A (recommended): Store the full 64-char args_hash in the pointer as the "key" shown to
  the planner. Display as full key in the pointer. The FEATURE-CONTEXT.md pointer example shows
  "Key: abc12345" — this can be the full 64-char hash; the planner passes it verbatim.
  The "abc12345" in the example is illustrative, not a truncation requirement.

  Option B: Add a get_by_prefix(prefix: str) method to ToolResultCache that does a SQL LIKE query.

  Use Option A — zero new SQL, simpler, consistent. Update context_manager.py to emit the full
  args_hash as the key (not truncated), and update the pointer display hint accordingly.
  The key displayed in the pointer IS the full hash that the tool accepts.

Current pointer format in context_manager.py (line 792-794):
```python
_compact = (
    f"[Result truncated — {len(result_str)} chars stored] "
    f"Tool: {tool_name} | Key: {args_hash[:8]} | Summary: {summary}..."
)
```

Required pointer format per FEATURE-CONTEXT.md (all four elements locked):
```
[Result truncated — 7580 chars stored | chunks: 3000 chars each]
Tool: list_directory | Key: abc12345
Summary: 42 .py files in tools/
→ call retrieve_tool_result(key="abc12345", offset=0, limit=3000) to read full result
```

Updated compact format to implement:
```python
_DEFAULT_CHUNK_SIZE = 3000  # default limit for retrieve_tool_result
_compact = (
    f"[Result truncated — {len(result_str)} chars stored | chunks: {_DEFAULT_CHUNK_SIZE} chars each]\n"
    f"Tool: {tool_name} | Key: {args_hash}\n"
    f"Summary: {summary}...\n"
    f'→ call retrieve_tool_result(key="{args_hash}", offset=0, limit={_DEFAULT_CHUNK_SIZE}) to read full result'
)
```

From src/agentic_workflows/tools/read_file_chunk.py (closest analog for chunked retrieval pattern):
```python
class ReadFileChunkTool(Tool):
    name = "read_file_chunk"
    _args_schema = {
        "path": {"type": "string", "required": "true"},
        "offset": {"type": "number"},
        "limit": {"type": "number"},
    }
    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        # Returns: content, offset, lines_returned, total_lines, has_more, next_offset
```

From src/agentic_workflows/tools/retrieve_run_context.py (stateful tool with injected store):
```python
class RetrieveRunContextTool(Tool):
    def __init__(self, checkpoint_store: Any) -> None:
        self.checkpoint_store = checkpoint_store
```

From src/agentic_workflows/orchestration/langgraph/tools_registry.py build_tool_registry():
```python
def build_tool_registry(
    store: SQLiteMemoStore,
    checkpoint_store: SQLiteCheckpointStore | None = None,
    mission_context_store: Any = None,
    embedding_provider: Any = None,
) -> dict[str, Tool]:
    ...
    if checkpoint_store is not None:
        registry["retrieve_run_context"] = RetrieveRunContextTool(checkpoint_store)
    if mission_context_store is not None:
        registry["query_context"] = QueryContextTool(mission_context_store, embedding_provider)
    return registry
```

The retrieve_tool_result tool follows the same conditional-registration pattern:
```python
if tool_result_cache is not None:
    registry["retrieve_tool_result"] = RetrieveToolResultTool(tool_result_cache)
```

build_tool_registry() signature must gain a new optional param:
```python
def build_tool_registry(
    store: SQLiteMemoStore,
    checkpoint_store: SQLiteCheckpointStore | None = None,
    mission_context_store: Any = None,
    embedding_provider: Any = None,
    tool_result_cache: Any = None,  # ADD
) -> dict[str, Tool]:
```

From src/agentic_workflows/orchestration/langgraph/orchestrator.py (caller of build_tool_registry):
The orchestrator already holds self._tool_result_cache (wired in Phase 08-05). It calls
build_tool_registry() in __init__. Pass tool_result_cache=self._tool_result_cache there.

From planner_helpers.py context management rules block (line 236-243) — append one rule:
```python
"- When a tool result was too large, a compact pointer is injected with a key. "
"Call retrieve_tool_result(key=\"<key>\", offset=0, limit=3000) to read the full result. "
"Use has_more and increment offset by limit to page through chunks.\n"
```

Also add to the tool_args_block (alongside read_file_chunk entry):
```python
'- retrieve_tool_result: {"key":"<hash>", "offset":0, "limit":3000} — fetch stored large result by key; use has_more+offset to page\n'
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Create RetrieveToolResultTool and unit tests</name>
  <files>
    src/agentic_workflows/tools/retrieve_tool_result.py,
    tests/unit/test_retrieve_tool_result.py
  </files>
  <behavior>
    - Test: execute({"key": valid_hash}) with pool=None cache returns {"error": "cache miss — result expired or not found"}
    - Test: execute({}) missing key returns {"error": "key is required"}
    - Test: execute({"key": hash, "offset": 0, "limit": 3000}) with real result returns {"result": chunk, "offset": 0, "limit": 3000, "total": N, "has_more": bool}
    - Test: has_more=True when total > offset + limit, has_more=False when chunk covers remainder
    - Test: offset > total returns {"result": "", "offset": N, "limit": 3000, "total": N, "has_more": False}
    - Test: pool=None ToolResultCache always returns cache-miss error dict (not None, not empty string)
    - Test: RetrieveToolResultTool(cache) where cache=ToolResultCache(pool=None) — constructor does not raise
  </behavior>
  <action>
    Write tests FIRST (RED), then implement (GREEN).

    RED — create tests/unit/test_retrieve_tool_result.py with NotImplementedError stubs:
    - TestRetrieveToolResultToolMiss: key missing, pool=None miss
    - TestRetrieveToolResultToolChunking: successful retrieval, has_more=True, has_more=False, offset beyond total
    All stubs raise NotImplementedError to guarantee RED state.

    GREEN — create src/agentic_workflows/tools/retrieve_tool_result.py:

    ```python
    from __future__ import annotations
    """retrieve_tool_result — planner-callable cache retrieval with offset/limit chunking."""
    from typing import Any
    from .base import Tool

    _DEFAULT_LIMIT = 3000

    class RetrieveToolResultTool(Tool):
        name = "retrieve_tool_result"
        _args_schema = {
            "key": {"type": "string", "required": "true"},
            "offset": {"type": "number"},
            "limit": {"type": "number"},
        }
        description = (
            "Retrieve a stored large tool result by its cache key. "
            "Required args: key (str, the hash from the compact pointer). "
            "Optional: offset (int, char offset into the result, default 0), "
            "limit (int, max chars to return, default 3000). "
            "Returns: result (str chunk), offset, limit, total (total chars), has_more (bool). "
            "Use has_more=True to loop: increment offset by limit until has_more is False."
        )

        def __init__(self, tool_result_cache: Any) -> None:
            self._cache = tool_result_cache

        def execute(self, args: dict[str, Any]) -> dict[str, Any]:
            key = str(args.get("key", "")).strip()
            if not key:
                return {"error": "key is required"}

            try:
                offset = max(0, int(args.get("offset", 0)))
                limit = max(1, int(args.get("limit", _DEFAULT_LIMIT)))
            except (ValueError, TypeError):
                return {"error": "offset and limit must be integers"}

            # Look up by args_hash directly. The key IS the full args_hash emitted in the pointer.
            # ToolResultCache.get() requires tool_name + args_hash; we stored both but the pointer
            # only exposes the hash. Use a sentinel tool_name "" and a dedicated get_by_key() path.
            # Since ToolResultCache.get() needs tool_name, add a get_by_key() method OR
            # store the full result under a key-only lookup. Per discretion, add get_by_key() to
            # ToolResultCache that queries only by args_hash column (unique enough — SHA-256).
            full_result = self._cache.get_by_key(args_hash=key)

            if full_result is None:
                return {"error": "cache miss — result expired or not found"}

            total = len(full_result)
            chunk = full_result[offset: offset + limit]
            chars_returned = len(chunk)
            end = offset + chars_returned
            has_more = end < total

            return {
                "result": chunk,
                "offset": offset,
                "limit": limit,
                "total": total,
                "has_more": has_more,
            }
    ```

    IMPORTANT — ToolResultCache needs get_by_key(). Add to
    src/agentic_workflows/storage/tool_result_cache.py:
    ```python
    def get_by_key(self, *, args_hash: str) -> str | None:
        """Retrieve cached full result by args_hash alone (tool_name not required).
        Returns None on miss, expired, or pool=None.
        Logs WARNING if result was expired and deleted."""
        if self._pool is None:
            return None
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT full_result, expires_at FROM tool_result_cache WHERE args_hash = %s",
                (args_hash,),
            ).fetchone()
        if row is None:
            return None
        full_result, expires_at = row
        if expires_at < datetime.now(tz=UTC):
            import logging as _logging  # noqa: PLC0415
            _logging.getLogger(__name__).warning(
                "retrieve_tool_result: key %s expired at %s — evicting", args_hash[:8], expires_at
            )
            with self._pool.connection() as conn:
                conn.execute(
                    "DELETE FROM tool_result_cache WHERE args_hash = %s", (args_hash,)
                )
            return None
        return full_result
    ```

    The pool=None path in get_by_key() returns None, which the tool translates to the cache-miss
    error dict. This is the correct behavior — planner sees a clear error, not a silent empty string.

    Run: pytest tests/unit/test_retrieve_tool_result.py -q
    Run: ruff check src/agentic_workflows/tools/retrieve_tool_result.py src/agentic_workflows/storage/tool_result_cache.py
  </action>
  <verify>
    <automated>cd /home/nir/dev/agent_phase0 && pytest tests/unit/test_retrieve_tool_result.py -q 2>&1 | tail -10</automated>
  </verify>
  <done>
    All tests in test_retrieve_tool_result.py pass (no NotImplementedError stubs remaining).
    RetrieveToolResultTool.execute() returns correct chunk dict on hit, cache-miss error on miss.
    get_by_key() added to ToolResultCache — pool=None returns None, expired entries evicted with WARNING.
    ruff check clean on both files.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Register tool, update pointer format, add planner hint</name>
  <files>
    src/agentic_workflows/orchestration/langgraph/tools_registry.py,
    src/agentic_workflows/orchestration/langgraph/orchestrator.py,
    src/agentic_workflows/orchestration/langgraph/context_manager.py,
    src/agentic_workflows/orchestration/langgraph/planner_helpers.py
  </files>
  <behavior>
    - build_tool_registry() accepts tool_result_cache=None param; registers "retrieve_tool_result" when non-None
    - orchestrator.py passes self._tool_result_cache to build_tool_registry()
    - context_manager.py compact pointer includes all four locked elements per FEATURE-CONTEXT.md
    - planner_helpers.py tool_args_block includes retrieve_tool_result entry
    - planner_helpers.py context management rules include retrieve_tool_result retrieval hint
    - pytest tests/ -q still passes all existing tests (no regressions)
  </behavior>
  <action>
    STEP 1 — tools_registry.py:
    Add import at top (alongside existing conditional-tool imports):
    ```python
    from agentic_workflows.tools.retrieve_tool_result import RetrieveToolResultTool
    ```
    Add tool_result_cache parameter to build_tool_registry() signature:
    ```python
    def build_tool_registry(
        store: SQLiteMemoStore,
        checkpoint_store: SQLiteCheckpointStore | None = None,
        mission_context_store: Any = None,
        embedding_provider: Any = None,
        tool_result_cache: Any = None,  # ADD — passed through from orchestrator
    ) -> dict[str, Tool]:
    ```
    At the end of the function, after the existing conditional registrations:
    ```python
    if tool_result_cache is not None:
        registry["retrieve_tool_result"] = RetrieveToolResultTool(tool_result_cache)
    ```

    STEP 2 — orchestrator.py:
    Find the build_tool_registry() call in LangGraphOrchestrator.__init__ (already passes
    checkpoint_store, mission_context_store, embedding_provider). Add:
    ```python
    tool_result_cache=self._tool_result_cache,
    ```
    The orchestrator already holds self._tool_result_cache from Phase 08-05 wiring.

    STEP 3 — context_manager.py:
    Update the _compact pointer format (lines 792-794). Replace with the four-element format:
    ```python
    _DEFAULT_CHUNK_SIZE = 3000  # module-level constant, placed near _LARGE_RESULT_THRESHOLD
    ...
    _compact = (
        f"[Result truncated — {len(result_str)} chars stored | chunks: {_DEFAULT_CHUNK_SIZE} chars each]\n"
        f"Tool: {tool_name} | Key: {args_hash}\n"
        f"Summary: {summary}...\n"
        f'→ call retrieve_tool_result(key="{args_hash}", offset=0, limit={_DEFAULT_CHUNK_SIZE}) to read full result'
    )
    ```
    Place _DEFAULT_CHUNK_SIZE as a module-level constant near _LARGE_RESULT_THRESHOLD (at top of file).
    Do NOT truncate the key to args_hash[:8] — emit the full 64-char hash so the planner can pass it
    verbatim to retrieve_tool_result.

    STEP 4 — planner_helpers.py:
    In _build_full_system_prompt() tool_args_block, add after the read_file_chunk line:
    ```python
    '- retrieve_tool_result: {"key":"<hash>", "offset":0, "limit":3000} — fetch stored large result; use has_more+offset to page\n'
    ```
    In the context management rules block, after the read_file_chunk looping rule, add:
    ```python
    "- When a compact pointer appears with [Result truncated], call retrieve_tool_result(key=\"<key>\", offset=0, limit=3000) to fetch the full result. Page using has_more and offset.\n"
    ```

    After all changes, run the full test suite:
    pytest tests/ -q
    ruff check src/agentic_workflows/orchestration/langgraph/tools_registry.py
                src/agentic_workflows/orchestration/langgraph/orchestrator.py
                src/agentic_workflows/orchestration/langgraph/context_manager.py
                src/agentic_workflows/orchestration/langgraph/planner_helpers.py
  </action>
  <verify>
    <automated>cd /home/nir/dev/agent_phase0 && pytest tests/ -q 2>&1 | tail -10</automated>
  </verify>
  <done>
    pytest tests/ -q passes all existing tests (1594+) with no regressions.
    python -c "from agentic_workflows.orchestration.langgraph.tools_registry import build_tool_registry; print('ok')" — no ImportError.
    ruff check clean on all four modified files.
    context_manager.py compact pointer contains "chunks:" and the full retrieve_tool_result call hint.
    planner_helpers.py tool_args_block contains "retrieve_tool_result".
  </done>
</task>

</tasks>

<verification>
- pytest tests/unit/test_retrieve_tool_result.py -q — all green, no NotImplementedError stubs
- pytest tests/ -q — all existing tests pass unchanged (no regressions)
- python -c "from agentic_workflows.tools.retrieve_tool_result import RetrieveToolResultTool; t = RetrieveToolResultTool.__new__(RetrieveToolResultTool); print(t.name)" — prints "retrieve_tool_result"
- ruff check src/agentic_workflows/tools/retrieve_tool_result.py src/agentic_workflows/storage/tool_result_cache.py src/agentic_workflows/orchestration/langgraph/tools_registry.py src/agentic_workflows/orchestration/langgraph/context_manager.py src/agentic_workflows/orchestration/langgraph/planner_helpers.py
- grep "chunks:" src/agentic_workflows/orchestration/langgraph/context_manager.py — confirms four-element pointer format
- grep "retrieve_tool_result" src/agentic_workflows/orchestration/langgraph/planner_helpers.py — confirms planner hint present
</verification>

<success_criteria>
- retrieve_tool_result tool exists and is registered when tool_result_cache is provided
- Tool accepts key, offset, limit; returns result/offset/limit/total/has_more chunk dict
- Cache miss (pool=None or unknown key) returns {"error": "cache miss — result expired or not found"}
- Compact pointer emitted by ContextManager includes all four FEATURE-CONTEXT.md locked elements
- Planner hint in planner_helpers.py tells planner how to use the tool
- All 1594+ existing tests pass unchanged
- ruff clean on all modified files
</success_criteria>

<output>
After completion, create `.planning/phases/08-multi-model-sycl-routing-and-planner-bottleneck-resolution/features/extend-retrieve-tool-result/FEATURE-SUMMARY.md`
</output>
