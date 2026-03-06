# Agent Architect Memory — agent_phase0

## Current Phase Status (2026-03-03)
- **381 tests passing**, ruff: 6 violations in tests (SIM117/SIM105/F401 — fixable, not blocking CI)
- **Phase 1**: Complete
- **Phase 2**: FULLY COMPLETE including LGUP-02 (ToolNode + tools_condition edges WIRED on Anthropic path)
  - `_parse_all_actions_json()` gated out for Anthropic path (line 753 in graph.py)
  - `builder.add_conditional_edges("plan", tools_condition)` + `builder.add_edge("tools", "plan")` confirmed in graph.py
- **Phase 3** (multi-agent): Scaffolded — specialist subgraphs built + invoked (parallel-invoke pattern); NOT true subgraph execution
- **Phase 4**: FULLY COMPLETE (all 7 sub-plans + 04-07 post-completion tools)
- **Phase 5**: FULLY COMPLETE (Langfuse wiring + architecture snapshot + concurrency regression fix)
- **Phase 6+**: No plans exist yet

## Key Files
- `src/agentic_workflows/orchestration/langgraph/graph.py` — 2534 lines (grew from 1700)
- `src/agentic_workflows/orchestration/langgraph/state_schema.py` — RunState TypedDict
- `src/agentic_workflows/orchestration/langgraph/user_run.py` — NEW: persistent conversational UserSession (prior_context injection)
- `src/agentic_workflows/orchestration/langgraph/run_ui.py` — NEW: extracted UI render functions
- `src/agentic_workflows/orchestration/langgraph/tools_registry.py` — NOW 20 tools registered (was ~7)
- `docs/architecture/PHASE_PROGRESSION.md` — 625-line standalone architecture narrative

## New State Fields (added Phases 4-5)
- `context_clear_requested: bool` — set True when clear_context tool fires; consumed by UserSession
- `mission_ledger: list[dict]` — per-mission {mission_id, mission_text, status, completed_tools}
- `ToolRecord.via_subgraph: NotRequired[bool]` — tags entries added via specialist subgraph invocation

## New run() Signature
- `run(user_input, run_id=None, *, rerun_context=None, prior_context=None)`
- `prior_context: list[AgentMessage] | None` — injected between system prompt and user msg

## Tool Registry — Current Count: 20 registered tools
Core: write_file, read_file, update_file_section, text_analysis, data_analysis, sort_array, math_stats
Extended: string_ops, regex_matcher, json_parser, task_list_parser, echo
Phase 4+: datetime_ops, fill_template, hash_content, extract_table, recognize_pattern
DB/code: parse_code_structure, describe_db_schema, query_db, http_request, run_bash, clear_context

## Architecture Patterns
- `_sequential_node()` wrapper: zero-out Annotated list fields in sequential nodes to prevent doubling
- `_plan_semaphore = threading.Semaphore(1)`: serializes LLM calls, prevents 429 cascades
- Parallel-invoke pattern: `_executor_subgraph.invoke(exec_state, {})` first (for log transitions), then `_execute_action()` for real pipeline
- Executor subgraph callbacks inherited from parent (NOT re-injected — avoids double-spans)
- `prior_context` injection: UserSession builds compact prior-run summary for multi-turn conversations
- `clarify` action type: `clarify_node → finalize` edge for confusion-loop recovery

## Critical Conventions
- `_sequential_node()` must NOT be used on Send() parallel sub-nodes
- Specialist subgraphs compiled WITHOUT checkpointer (parent propagates)
- Annotated reducers required on any new RunState list field
- tools_condition routing is Anthropic-path only (other providers use JSON parse path)

## Open Issues / Ruff
- 6 ruff violations in tests/unit/test_observability.py (SIM117, SIM105) and test_parse_code_structure.py (F401 unused import)
- These are in tests only; CI uses `ruff check src/ tests/` so they DO affect CI status

## Graph Node Topology (Phase 5 current)
START → plan → execute → policy → plan (loop)
plan → finalize (when all missions done)
plan → tools → plan (Anthropic ReAct loop via tools_condition)
plan → clarify → finalize
finalize → END
