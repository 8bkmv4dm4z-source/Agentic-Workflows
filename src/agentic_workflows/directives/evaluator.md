# Role: Evaluator

Result validation, post-run audit, quality scoring, and mission completion verification.

## Tool Scope
Read-only tools + `audit_run()` from `mission_auditor.py`. The evaluator does not execute write operations or call the planner.

Allowed: `retrieve_memo`, `text_analysis` (read-only operations), `data_analysis` (read-only operations), `json_parser` (parse/validate operations), `regex_matcher` (match/find operations), `audit_run()`.

## Input Contract
- `state["mission_reports"]`: completed mission reports with used_tools and tool_results
- `state["tool_history"]`: full tool execution audit trail (includes args for content verification)
- `state["missions"]`: original mission strings for contract comparison
- `state["mission_contracts"]`: expected tools and files per mission
- `state["structured_plan"]`: plan steps with dependencies for completion tracking

## Output Contract
- `state["audit_report"]`: AuditReport dict with findings (pass/warn/fail per check per mission)
- Quality score metadata: passed/warned/failed counts

## Behavioral Rules

1. **Post-run only**: The evaluator runs after all missions have been attempted (in _finalize). It does not intervene during execution.
2. **Deterministic checks**: All checks are keyword-driven and heuristic. No LLM calls. Results are reproducible given the same state.
3. **Check catalog**:
   - `tool_presence`: Warn if keyword-implied tools were not used
   - `count_match`: Fail if requested N items but result has != N
   - `chain_integrity`: Fail if data_analysis→sort_array pipeline dropped items
   - `fibonacci_count`: Fail/warn if fibonacci file has wrong number count
   - `mean_reuse`: Warn if math_stats computed mean on a subset
   - `write_file_success`: Fail on write errors, warn on 0-char writes
   - `missing_required_outputs`: Fail if contract-required files/tools are absent
   - `output_content_mismatch`: Fail if pattern_report arithmetic is inconsistent
   - `mission_attribution_consistency`: Fail if mission report misses its own contract tools
4. **Tolerance-based comparison**: Use `_approx_equal()` for float comparisons (rel_tol=1e-4, abs_tol=0.01). Never use exact float equality.
5. **Context-aware filtering**: For ambiguous keywords ("analysis", "analyze"), only warn when the mission text contains an explicit tool name. Genuinely ambiguous keywords ("order", "stats") are always suppressed.
6. **No false positive bias**: When in doubt, downgrade from fail to warn. The evaluator's job is to surface real issues, not block runs.
7. **Audit report format**: Each finding has mission_id, mission text, level (pass/warn/fail), check name, and human-readable detail.

## Usage in This Repo

- Implemented by:
  - `orchestration/langgraph/mission_auditor.py::audit_run`
  - `orchestration/langgraph/graph.py::_finalize` (stores `state["audit_report"]`)
- Audit summaries are displayed in
  `orchestration/langgraph/run.py::_print_audit_panel`.
- Historical run summaries can be exported with
  `python -m agentic_workflows.orchestration.langgraph.run_audit`.
