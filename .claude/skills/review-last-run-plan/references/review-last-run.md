# Skill: ReviewLastRun
<!-- invoke: /review-last-run -->

Review `lastRun.txt` to produce a structured success/failure analysis of every run in the file. No live execution — read and interpret only.

## Steps

1. **Read `lastRun.txt`** in full.

2. **Identify each run** by `RUN START run_id=...` lines. For each run:
   - Note the run_id (short 8-char prefix)
   - Note `missions=N`
   - Determine whether it was an initial run or a re-run (re-runs appear after the `AUDIT REVIEW` panel of the prior run)

3. **Per run, collect:**
   - Tool execution sequence: each `TOOL EXEC step=N tool=X` with args and result
   - Mission reports: `MISSION REPORT #N mission=... used_tools=[...] result=...`
   - Audit findings: `AUDIT WARN/FAIL mission=N check=... detail=...`
   - Audit summary: `AUDIT REPORT passed=N warned=N failed=N`
   - Cache/memo events: `CACHE WRITE INPUT STORED`, `CACHE REUSE HIT/MISS`, `MEMO PUT`, `MEMO GET MISS/HIT`
   - Timeout events: `PLAN PROVIDER TIMEOUT`, `PLAN TIMEOUT FALLBACK`, `PLAN TIMEOUT MODE`
   - The final answer from `PLANNED ACTION step=N action={'action':'finish','answer':'...'}`

4. **Per mission, evaluate success criteria:**

   | Mission | Expected tools | Expected output |
   |---------|---------------|-----------------|
   | Task 1: Text Analysis Pipeline | text_analysis + string_ops + write_file | analysis_results.txt with uppercase key terms |
   | Task 2: Data Analysis and Sorting | data_analysis + sort_array + math_stats | outlier detection, sorted non-outliers, mean |
   | Task 3: JSON Processing | json_parser + regex_matcher + sort_array + write_file | users_sorted.txt with Alice, Bob, Charlie |
   | Task 4: Pattern Matching and Transform | regex_matcher + math_stats + write_file | pattern_report.txt with extracted numbers and stats |
   | Task 5: Fibonacci with Analysis | memoize + write_file to fib50.txt | 50 fibonacci integers as CSV |

   For each mission flag:
   - `PASS` — correct tools used, correct output file written with correct content
   - `WARN` — partial success or missing tools
   - `FAIL` — wrong content, wrong file, dropped data, or wrong tools attributed

5. **Check mission attribution accuracy:**
   - Compare `MISSION REPORT #N used_tools=[...]` against which tools the planner actually called for that task
   - Flag any case where a mission report includes tools that logically belong to a different task (e.g., `string_ops` credited to "Data Analysis and Sorting")

6. **Check finish claim accuracy:**
   - Extract the `finish` answer text
   - Compare each claim in the answer against actual mission report results
   - Flag any claim that contradicts the actual tool results (e.g., claiming "all 5 tasks completed" when mission reports show wrong attributions or wrong file content)
   - Flag premature finish: finish triggered before all tasks actually ran (e.g., timeout mode finish with incomplete task data)

7. **Check cache/memo correctness:**
   - For each `CACHE WRITE INPUT STORED key=write_file_input:X`, verify the content being cached corresponds to the correct task for file X
   - Flag cache poisoning: a file being cached with content from a different task (e.g., `fib50.txt` cached with regex-extracted numbers instead of fibonacci numbers)
   - Report the stored hash and content so it can be invalidated

8. **Verify the two specific issues:**

   **Issue 1 — Wrong content cached/written for fib50.txt:**
   - Find the `TOOL EXEC ... tool=write_file ... path=fib50.txt` step
   - Check the `content` value: should be a comma-separated list of exactly 50 fibonacci integers starting with `0,1,1,2,3,...`
   - If content is extracted regex numbers, mean array, or malformed, mark as `CACHE POISONED`
   - Report the `CACHE WRITE INPUT STORED` hash so it can be identified and cleared

   **Issue 2 — Premature finish:**
   - Check if `PLAN TIMEOUT MODE` appears before `finish`
   - Check if the timeout finish answer falsely claims task completion for tasks that were either: not run, run with wrong inputs, or run for a different mission
   - Check if any incomplete or wrong mission result is cited as success in the finish answer

9. **Output format:**

```
═══════════════════════════════════════════════
 LAST RUN REVIEW
═══════════════════════════════════════════════

RUN 1: <run_id> (<N> steps)
  Missions: N/5 correctly executed

  Mission 1 [PASS/WARN/FAIL]: <summary>
  Mission 2 [PASS/WARN/FAIL]: <summary>
  Mission 3 [PASS/WARN/FAIL]: <summary>
  Mission 4 [PASS/WARN/FAIL]: <summary>
  Mission 5 [PASS/WARN/FAIL]: <summary>

  Attribution issues:   <list>
  Finish claim accuracy: CORRECT / INCORRECT — <reason>
  Cache writes: <list of file→hash, flag POISONED if wrong>

  Audit: passed=N warned=N failed=N
  Audit accuracy: CORRECT / INCORRECT — <reason if wrong>

---
RUN 2 (re-run): <run_id> (<N> steps)
  [same format]

═══════════════════════════════════════════════
 ISSUE VERIFICATION
═══════════════════════════════════════════════

Issue 1 — fib50.txt cached with wrong content:
  [CONFIRMED / NOT CONFIRMED]
  Step: <N>
  Content written: <value>
  Expected: first 50 fibonacci integers
  Cache key: write_file_input:fib50.txt
  Cache hash: <hash>
  Root cause: <explanation>

Issue 2 — Premature finish:
  [CONFIRMED / NOT CONFIRMED]
  Trigger: <timeout / planner error / other>
  Step: <N>
  Tasks not completed correctly at finish time: <list>
  Finish answer falsely claims: <quote>
  Root cause: <explanation>

═══════════════════════════════════════════════
 BUGS STILL OPEN (not yet fixed)
═══════════════════════════════════════════════
  <list any root causes that don't yet have a code fix>
```
