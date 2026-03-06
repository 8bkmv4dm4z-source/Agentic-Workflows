# Quick Task 2: Improve tools for multi-task missions and add advanced DB navigation tools - Context

**Gathered:** 2026-03-04
**Status:** Ready for planning

<domain>
## Task Boundary

Improve the agent's tool inventory to handle real-world multi-task missions better:
1. Add fuzzy/typo-tolerant file search (search_files is glob-only, no regex, no fuzzy)
2. Add regex mode to search_files for pattern-based file discovery
3. Add a Postgres-ready SQL query tool (current query_db is a Q&A store, not general SQL)
4. Update system prompt tool reference, mission_parser keyword map, and tests

JSX reference (`agent-planner-pe-methods.jsx`) tools reviewed:
- Database/SQL pattern: list_tables -> get_schema -> run_query -> check_query
- File System: already covered
- Human-in-the-Loop: for write safety on DB mutations

</domain>

<decisions>
## Implementation Decisions

### Fuzzy Search Scope
- Enhance existing `search_files` tool with regex mode + fuzzy matching mode
- Use `difflib` (stdlib) for Levenshtein-like similarity — no new dependencies
- Keep search_files as the single entry point for file discovery

### DB Tool Depth
- Build a Postgres-ready `query_sql` tool that works with SQLite now and Postgres later
- Supports: list_tables, get_schema, run_query operations in one tool
- Read-only by default; write operations require explicit `allow_writes=True` flag
- Connection via URI string (sqlite:///path or postgresql://...)

### Phase Boundary
- Add all tools now (fuzzy search + regex search_files + query_sql)
- ~15% prompt token increase is acceptable; Phase 6 prompt caching will offset
- Tool arg reference in system prompt must be updated
- mission_parser _TOOL_KEYWORD_MAP must be updated

### Claude's Discretion
- Exact fuzzy threshold (0.6 similarity ratio is standard for difflib)
- SQL query timeout default (5 seconds)
- Whether to add query validation (check_query) as a sub-operation or separate concern

</decisions>

<specifics>
## Specific Ideas

- JSX Database/SQL pattern recommends: list_tables -> get_schema -> check_query -> run_query as a 4-step workflow
- Consolidate into single `query_sql` tool with `operation` arg (matches existing tool patterns like `string_ops`, `data_analysis`)
- Fuzzy matching: `difflib.SequenceMatcher` with ratio threshold, applied to filename stems
- search_files enhancement: add `mode` arg ("glob" default, "regex", "fuzzy") — backward compatible

</specifics>
