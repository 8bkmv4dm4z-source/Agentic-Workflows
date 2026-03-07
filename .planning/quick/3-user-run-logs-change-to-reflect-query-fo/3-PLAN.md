---
phase: quick-3
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/agentic_workflows/cli/user_run.py
  - .planning/STATE.md
autonomous: true
requirements: [QUICK-3]
must_haves:
  truths:
    - "Terminal output shows a dedicated 'Data Access' panel after each run that lists which data tools were called"
    - "Each data-access entry shows the tool name and a short summary of what it returned"
    - "The run log file (.tmp/p2_latest_run.log) includes a DATA_ACCESS section listing queried tools"
    - "Non-data tools (plan, finish, clarify) are not included in the data-access panel"
  artifacts:
    - path: "src/agentic_workflows/cli/user_run.py"
      provides: "Updated _render_event and _write_run_report with data-access visibility"
      contains: "_DATA_ACCESS_TOOLS"
  key_links:
    - from: "run_complete SSE event"
      to: "_render_event in user_run.py"
      via: "result.tools_used (tool_history list)"
      pattern: "_DATA_ACCESS_TOOLS"
---

<objective>
Make data-querying tool calls visually distinct in the terminal and run log.

Purpose: When watching a live agent session, users cannot currently tell whether the agent accessed data (read files, ran analysis, sorted arrays) vs purely planned. This change adds a dedicated "Data Access" Rich panel and log section that lists every data-access tool call with tool name, key args, and result summary.

Output:
- Updated user_run.py with _DATA_ACCESS_TOOLS set, new _render_data_access_panel helper, updated _render_event run_complete branch, updated _write_run_report
- STATE.md updated to record this quick task under the phase 7.1 section
</objective>

<execution_context>
@/home/nir/.claude/get-shit-done/workflows/execute-plan.md
@/home/nir/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@src/agentic_workflows/cli/user_run.py

<interfaces>
<!-- Key data available in the run_complete SSE event result dict -->
<!-- result["tools_used"] == state["tool_history"] — list of ToolRecord dicts -->
<!-- Each ToolRecord: {"call": str, "tool": str, "args": dict, "result": any} -->
<!-- result["mission_report"] — list of MissionReport dicts -->
<!--   Each: {"mission_id": int, "mission": str, "used_tools": list[str], "tool_results": list[{"tool":str, "result":any}]} -->
<!-- result["answer"] — str final answer -->
<!-- result["audit_report"] — dict | None -->

<!-- Data-access tools to highlight (conservative list, no new deps needed): -->
<!--   read_file, write_file, data_analysis, sort_array, run_bash, search_files, http_request, hash_content -->
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Commit pre-existing uncommitted changes</name>
  <files>
    .planning/config.json
    Shared_plan.md
    docker-compose.yml
    src/agentic_workflows/api/app.py
    src/agentic_workflows/api/routes/run.py
    src/agentic_workflows/api/routes/runs.py
    src/agentic_workflows/cli/user_run.py
    src/agentic_workflows/logger.py
    src/agentic_workflows/orchestration/langgraph/provider.py
    src/agentic_workflows/tools/run_bash.py
    src/agentic_workflows/tools/write_file.py
    tests/eval/conftest.py
    tests/eval/test_eval_harness.py
    tests/integration/test_api_service.py
  </files>
  <action>
    Stage and commit the 14 modified files that represent phase 7.1 work completed in prior sessions but never committed. These are legitimate phase work artifacts — not experimental or broken code.

    Run:
    ```
    git add .planning/config.json Shared_plan.md docker-compose.yml \
      src/agentic_workflows/api/app.py \
      src/agentic_workflows/api/routes/run.py \
      src/agentic_workflows/api/routes/runs.py \
      src/agentic_workflows/cli/user_run.py \
      src/agentic_workflows/logger.py \
      src/agentic_workflows/orchestration/langgraph/provider.py \
      src/agentic_workflows/tools/run_bash.py \
      src/agentic_workflows/tools/write_file.py \
      tests/eval/conftest.py \
      tests/eval/test_eval_harness.py \
      tests/integration/test_api_service.py

    git commit -m "chore(07.1): commit phase 7.1 work from prior sessions"
    ```

    Do NOT stage the untracked files (fib.sh, run.bash, script.sh, .claude/agent-memory/, .planning/phases/07.1-*/.gitkeep) — those are scratch files.
  </action>
  <verify>
    <automated>git status --short | grep -c "^M" || echo "0 staged modifications remain"</automated>
  </verify>
  <done>The 14 pre-existing modified files are committed. `git status` shows no staged changes for those paths. Untracked scratch files remain untracked.</done>
</task>

<task type="auto">
  <name>Task 2: Add data-access visibility to _render_event and _write_run_report</name>
  <files>src/agentic_workflows/cli/user_run.py</files>
  <action>
    Modify user_run.py to highlight data-querying tool calls. No new dependencies — use only existing Rich imports (Panel, Console already imported).

    **Step 1 — Add module-level constant after the `console = Console()` line:**

    ```python
    # Tools that represent data-access / data-query operations
    _DATA_ACCESS_TOOLS = frozenset({
        "read_file",
        "write_file",
        "data_analysis",
        "sort_array",
        "run_bash",
        "search_files",
        "http_request",
        "hash_content",
    })
    ```

    **Step 2 — Add a helper function `_render_data_access_panel` before `_render_event`:**

    ```python
    def _render_data_access_panel(tools_used: list[dict]) -> None:
        """Render a Rich panel summarising data-access tool calls from tool_history."""
        hits = [t for t in tools_used if isinstance(t, dict) and t.get("tool") in _DATA_ACCESS_TOOLS]
        if not hits:
            return
        lines = []
        for entry in hits:
            tool = entry.get("tool", "?")
            args = entry.get("args", {})
            result = entry.get("result", "")
            # Build a short arg summary — show "path" or "query" key if present, else first key
            arg_summary = ""
            if isinstance(args, dict):
                for key in ("path", "query", "command", "url", "content"):
                    if key in args:
                        arg_summary = f"{key}={str(args[key])[:60]}"
                        break
                if not arg_summary and args:
                    first_key = next(iter(args))
                    arg_summary = f"{first_key}={str(args[first_key])[:60]}"
            result_str = str(result)[:120] if result else "(no output)"
            lines.append(f"[bold]{tool}[/]({arg_summary})\n  -> {result_str}")
        body = "\n".join(lines)
        console.print(Panel(body, title=f"Data Access ({len(hits)} calls)", style="bold magenta"))
    ```

    **Step 3 — In `_render_event`, inside the `elif event_type == "run_complete":` branch, call the helper AFTER the mission report panels and BEFORE the audit panel:**

    Find the existing block:
    ```python
        # Audit panel
        audit = result.get("audit_report")
    ```

    Insert BEFORE it:
    ```python
        # Data access panel — shows data-querying tool calls
        tools_used_list = result.get("tools_used", [])
        if isinstance(tools_used_list, list):
            _render_data_access_panel(tools_used_list)
    ```

    **Step 4 — In `_write_run_report`, after the existing audit block and before the `ANSWER:` line, add a DATA_ACCESS section:**

    Find:
    ```python
    answer = result.get("answer", "")
    lines.append(f"ANSWER: {str(answer)[:500]}")
    ```

    Insert BEFORE those two lines:
    ```python
    tools_used_list = result.get("tools_used", [])
    data_hits = [t for t in tools_used_list if isinstance(t, dict) and t.get("tool") in _DATA_ACCESS_TOOLS]
    if data_hits:
        lines.append(f"DATA_ACCESS: {len(data_hits)} call(s)")
        for entry in data_hits:
            tool = entry.get("tool", "?")
            result_snippet = str(entry.get("result", ""))[:100]
            lines.append(f"  {tool}: {result_snippet}")
    ```

    After all edits, run `ruff check src/agentic_workflows/cli/user_run.py` and fix any issues. Then run the unit tests to confirm nothing is broken:
    ```
    pytest tests/unit/ -q --tb=short 2>&1 | tail -20
    ```
  </action>
  <verify>
    <automated>python -c "from agentic_workflows.cli.user_run import _DATA_ACCESS_TOOLS, _render_data_access_panel; assert 'read_file' in _DATA_ACCESS_TOOLS; assert 'data_analysis' in _DATA_ACCESS_TOOLS; print('OK')"</automated>
  </verify>
  <done>
    - `_DATA_ACCESS_TOOLS` frozenset defined at module level with 8 tool names
    - `_render_data_access_panel` helper renders a magenta "Data Access (N calls)" Rich panel
    - `_render_event` calls the helper in run_complete before the audit panel
    - `_write_run_report` writes DATA_ACCESS section to .tmp/p2_latest_run.log
    - `ruff check` passes
    - Unit tests still pass
  </done>
</task>

<task type="auto">
  <name>Task 3: Update STATE.md to record this quick task under phase 7.1</name>
  <files>.planning/STATE.md</files>
  <action>
    Append a record of this quick enhancement to the STATE.md file. Find the `## Session Continuity` section at the bottom and insert BEFORE it a new entry in the Phase Features table, and update last_activity in the frontmatter.

    **Frontmatter update** — change these two lines:
    ```yaml
    last_updated: "2026-03-07T14:40:26.372Z"
    last_activity: 2026-03-07 — ContextManager lifecycle hooks wired, 657 tests passing
    ```
    to:
    ```yaml
    last_updated: "2026-03-07T15:00:00.000Z"
    last_activity: 2026-03-07 — Data-access visibility added to user_run.py (quick task 3, phase 7.1)
    ```

    **Phase Features table** — append a new row at the end of the table (before the blank line that follows it):
    ```
    | 7.1 | Data-access log visibility in user_run.py: _DATA_ACCESS_TOOLS panel + run log section | Enhance | 2026-03-07 | (quick-3) | ✓ Complete |
    ```

    **Pending Todos** — remove or mark done the item "Validate run.py and user_run.py work end-to-end with live provider" if the changes here satisfy it partially (leave it as-is if unsure — do not fabricate).

    Append to **Session Continuity** section:
    ```
    Last session: 2026-03-07 (quick task 3)
    Stopped at: quick-3 data-access visibility
    Resume file: None
    ```
    (overwrite the existing Session Continuity values)
  </action>
  <verify>
    <automated>grep -c "_DATA_ACCESS_TOOLS\|Data-access\|quick-3" /home/nir/dev/agent_phase0/.planning/STATE.md</automated>
  </verify>
  <done>STATE.md records the quick task under phase 7.1. Phase Features table has a new row. last_activity updated. Session Continuity updated.</done>
</task>

</tasks>

<verification>
After all tasks complete:

1. Import check: `python -c "from agentic_workflows.cli.user_run import _DATA_ACCESS_TOOLS, _render_data_access_panel; print('imports OK')"`
2. Ruff clean: `ruff check src/agentic_workflows/cli/user_run.py`
3. Unit tests: `pytest tests/unit/ -q --tb=short 2>&1 | tail -5`
4. Log check: `grep DATA_ACCESS .planning/STATE.md`
5. Git log: `git log --oneline -3` shows the pre-existing commit and any new commit
</verification>

<success_criteria>
- Terminal shows a magenta "Data Access (N calls)" panel after any run that invoked read_file, data_analysis, sort_array, run_bash, write_file, search_files, http_request, or hash_content
- Each entry in the panel shows: tool name, key argument snippet, result snippet (120 chars)
- .tmp/p2_latest_run.log contains a DATA_ACCESS section when data tools were used
- ruff check passes
- Unit tests still pass
- 14 pre-existing modified files are committed
- STATE.md updated with quick-3 record under phase 7.1
</success_criteria>

<output>
After completion, create `.planning/quick/3-user-run-logs-change-to-reflect-query-fo/3-SUMMARY.md` following the standard summary template.
</output>
