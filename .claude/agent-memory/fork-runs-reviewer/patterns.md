# Detailed Failure Patterns — Fork-Runs Reviewer

## Pattern 1: Infinite Duplicate-Tool Loop (dedup silently stalls planner)

**Files**: `2a9cb5d4`, `17e089e0` (the 2 most recent runs)
**Symptom**: PLAN_OUTPUT emits the same tool call 6-8 times; SPECIALIST_SELECT fires each time; TOOL_EXECUTE fires only once (first time); subsequent SS→no-TOOL_EXECUTE
**Root Cause**: `seen_tool_signatures` blocks re-execution of identical args, but the planner is not told the tool already ran — it keeps replanning the same action
**Evidence** (2a9cb5d4 lines 9-26):
```
[21:00:04.158] PLAN_OUTPUT ... data_analysis outliers ... queue_size_after=1
[21:00:04.180] SPECIALIST_SELECT specialist=evaluator tool_name=data_analysis
[21:00:09.019] PLAN_OUTPUT ... data_analysis outliers ... (AGAIN)
[21:00:09.052] SPECIALIST_SELECT ... (no TOOL_EXECUTE follows)
```
**Final state**: FINALIZE audit_pass=0 missions_completed=0
**Fix needed**: When dedup blocks, the system-message feedback to the planner (graph.py:1683) is not being injected quickly enough, or the message is not surfaced to the ScriptedProvider (which ignores messages). The real provider path hits this during live runs too.

## Pattern 2: Finish-Loop (planner emits finish 5-10 times, no tools)

**Files**: 10 files all from same ScriptedProvider fixture (e.g. `0a4c6935`, `1aef7e7b`, `3a8acc1d`, `61e59d32`, `eea551bf`, `bc7d9b7b`, `f88afcbd`, `fd808293`, `05332587`, `12eb5c91`)
**Symptom**: 7x identical `{"action":"finish","answer":"done"}` in < 1ms each; no tools; missions_completed=0
**Root Cause**: ScriptedProvider is configured to replay `finish` action; `_reject_finish_and_recover` should catch this but the mission contracts are empty (no required_tools) so `_all_missions_completed()` returns True prematurely OR the missions list is empty
**Evidence** (0a4c6935):
```
[20:55:20.225] PLAN_OUTPUT finish queue_size_after=1
[20:55:20.240] PLAN_OUTPUT finish queue_size_after=1  (11ms later)
... 7 total in 87ms
[20:55:20.312] FINALIZE audit_pass=1 warn_count=0 fail_count=0 missions_completed=0
```
Note: audit_pass=1 but missions_completed=0 — this is an audit false-positive (audit passes even with 0 completed missions)

## Pattern 3: SPECIALIST_SELECT Without Subsequent TOOL_EXECUTE (queue displacement)

**Files**: 30 instances across many runs
**Symptom**: SPECIALIST_SELECT fires, then a new PLAN_OUTPUT arrives with different action before TOOL_EXECUTE — the queue drains the next action and the first specialist selection is wasted
**Evidence** (`5012d64d` lines 9-12):
```
[20:55:14.472] PLAN_OUTPUT sort_array [3,1] asc  queue_after=1
[20:55:14.481] SPECIALIST_SELECT executor sort_array
[20:55:14.498] PLAN_OUTPUT memoize ...  queue_after=1  (REPLACES sort_array)
[20:55:14.513] SPECIALIST_SELECT executor memoize
[20:55:14.525] TOOL_EXECUTE memoize  (sort_array was silently dropped)
```
**Root Cause**: The graph routes to plan node even when there's a pending action in the queue; the new PLAN_OUTPUT result replaces the old pending_action. sort_array was never executed in this run.

## Pattern 4: Content Validation Fail + Audit Permanent Failure

**Files**: `834af9a5`, `fb08b68e`, `c6235b9e`, `fa8ed852` (4 files, 2 paired groups)
**Symptom**: First write_file call fails with content_validation_failed (bad fib sequence "0,1,1,2,3,5,110"); mission → failed; agent retries with correct content; mission → completed; but FINALIZE shows fail_count=1
**Root Cause**: Auditor's `write_file_success` check fires on the first (failed) write_file result in tool_results, even though a subsequent retry succeeded. The check doesn't skip retried actions.
**Evidence** (`834af9a5`):
```
[20:54:07.552] MISSION_STATUS in_progress->failed  (after content_validation_failed)
[20:54:07.585] TOOL_EXECUTE write_file 1249 chars  (correct retry)
[20:54:07.585] MISSION_STATUS failed->completed
FINALIZE audit_pass=0 fail_count=1
```

## Pattern 5: Run Without FINALIZE (hard crash / recursion limit)

**Files**: `56d8e6f7`, `7a9a9b9f` (2 paired files)
**Symptom**: File ends at SPECIALIST_SELECT sort_array without TOOL_EXECUTE and no FINALIZE
**Root Cause**: ScriptedProvider keeps returning new sort_array actions, each one gets queued, but they are identical items causing dedup; the graph hits max_steps or recursion limit and the Eventer is closed without a FINALIZE log being written
**Evidence** (`56d8e6f7`):
```
[20:54:11.931] PLAN_OUTPUT sort_array [2,1]  queue_after=1
[20:54:11.944] SPECIALIST_SELECT executor sort_array
[20:54:11.974] PLAN_OUTPUT sort_array [9,8]  queue_after=1  (immediately replaces!)
[20:54:11.984] SPECIALIST_SELECT executor sort_array
[end of file — no FINALIZE]
```

## Pattern 6: Audit False-Positive (audit_pass>0 but missions_completed=0)

**Files**: 13 of the 25 files with missions_completed=0 have audit_pass=1
**Root Cause**: Auditor counts missions that PASS its checks, not total mission count. If missions list is empty or all missions happen to pass (vacuously), audit_pass can be non-zero while no real work was done.
**Impact**: The VERIFY GATE check `audit_no_failures` would pass on these runs, masking the actual failure.

## Pattern 7: retrieve_memo False-Start

**Files**: `cae83753`, `d4df2c34`
**Symptom**: ScriptedProvider calls retrieve_memo for "write_file:fib.txt" and "write_file:fibonacci" — both return found=False; mission marked completed anyway; audit warns
**Root Cause**: Mission completion criteria not requiring the memo key to be found; retrieve_memo→found=False still counts as a tool being "used"

## Pattern 8: Fib.txt Written as Sequential Integers

**Files**: `5012d64d`, `87fe3815`, `56d8e6f7`, `7a9a9b9f`
**Symptom**: write_file called with content "0,1,2,3,...,126" — sequential integers, NOT Fibonacci
**Root Cause**: ScriptedProvider scripted to write wrong content; no content validation fires on `fib.txt` (only `fib50.txt` has fibonacci count validation)

## Stable Clean Patterns

### Clean Multi-Mission Runs
`acc99f41`, `faf3af57` (4-mission, step1/sort/string/repeat), `11af605c`, `9590fda7` (5-mission full demo) all produce perfect event sequences with no anomalies.

### Multi-Action Queue Works
`1a12ca51`: queue_size_after=3 at first PLAN_OUTPUT; all 3 tools execute in order without gaps

### Fib50 Self-Correction Works
`fb08b68e` / `834af9a5`: wrong fib → failed → correct fib → completed. Recovery logic works; auditor is the problem.
