# Fork-Runs Reviewer Memory

## Session 2026-03-03: First full analysis of 105 event files

### Key Architecture Notes
- Event files live in `/home/nir/dev/agent_phase0/events/` (not in repo root)
- Each file is `{run_id}_events.txt` — one per orchestrator run
- Event types: PLAN_OUTPUT, SPECIALIST_SELECT, TOOL_EXECUTE, MISSION_ATTRIBUTION, MISSION_STATUS, FINALIZE
- `run-retrieve-hit_events.txt` is a persistent fixture file; it contains 2 FINALIZE events (reused across test runs)
- `lastRun.txt` exists and shows full mission results for the most recent real (live-provider) run

### Fork-Run Structure (105 files, all from 2026-03-03)
- Almost all files come in near-duplicate pairs (same logic, different run_ids/timestamps/tmp paths)
- This is a deliberate fork-run test harness: same ScriptedProvider inputs run twice to test determinism
- 52 near-duplicate pairs confirmed; 1 group of 10 near-dups (finish-loop pattern), 1 group of 8

### Failure Taxonomy (from 105 files)
1. **Duplicate-finish loop** (n=10 files, 10% of corpus): Planner emits `{"action":"finish","answer":"done"}` 5-7 times in rapid succession; dedup check does NOT block finish actions; final FINALIZE has missions_completed=0. All are near-identical ScriptedProvider tests.
2. **Deduplication swallows tool** (n=~30 SPECIALIST_SELECT events across many files): SPECIALIST_SELECT fires, then a new PLAN_OUTPUT arrives before TOOL_EXECUTE — the duplicate-signature check blocks execution silently; no TOOL_EXECUTE emitted.
3. **Content validation failure → fib number wrong** (n=4 files): ScriptedProvider writes `"0, 1, 1, 2, 3, 5, 110"` (wrong fib), gets `failed` status, then corrects; but auditor still sees the failed write_file and fails the audit.
4. **Planner produces bad fib for fib.txt** (n=2 paired files, `5012d64d`, `87fe3815`): Writes integers 0-126 instead of Fibonacci sequence; mission completes (no fibonacci count check on fib.txt, only on fib50.txt).
5. **Run crash without FINALIZE** (n=2 files: `56d8e6f7`, `7a9a9b9f`): sort_array SPECIALIST_SELECT gets queued but PLAN_OUTPUT keeps replacing it before execution; run terminates abruptly (no FINALIZE).
6. **Infinite duplicate-tool loop** (n=2 most recent: `2a9cb5d4`, `17e089e0`): data_analysis/text_analysis called once, then replanned 6-8 more times with identical args; dedup blocks execution; planner never progresses; missions_completed=0 at FINALIZE.
7. **retrieve_memo false-starts** (n=4 files: `cae83753`, `d4df2c34`): ScriptedProvider retrieves memo key "write_file:fib.txt" which doesn't exist (found=False); audit warns. Paired.

### Recurring Bugs
- **SPECIALIST_SELECT without TOOL_EXECUTE** is the #1 symptom in failing runs. Caused by dedup blocking OR by a new PLAN_OUTPUT arriving (via queue drain) before the previous tool executes.
- **Finish-loop on ScriptedProvider**: finish action is allowed to repeat 7 times before graph yields. The finish-rejection logic does NOT engage because the ScriptedProvider's mission has no contracts requiring tools.
- **Content validation fail persists in audit**: Even when the agent self-corrects (write_file fails → retries successfully), the auditor's `write_file_success` check fires on the first failure and permanently fails the mission.
- **Fib.txt content not validated**: `fib.txt` missions accept any write_file content (no count check), so the agent can write sequential integers and pass.

### Stable Behaviors
- All clean runs (audit_pass >= missions_completed) follow perfect PLAN_OUTPUT → SPECIALIST_SELECT → TOOL_EXECUTE → MISSION_ATTRIBUTION → MISSION_STATUS sequence
- `write_file` + `memoize` pattern works correctly in all runs that reach it
- `sort_array` result consistently includes `original` array
- Multi-action queue (queue_size_before=0, queue_size_after=3) correctly dispatches 3 tools in `1a12ca51`

### Links
- See `patterns.md` for detailed failure patterns with evidence
