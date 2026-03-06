# Skill: ReviewTmpHealth
<!-- invoke: /review-tmp-health -->

Analyze the `.tmp/` directory artifacts to identify current weak links in system design and runtime behavior. Read-only — no code changes.

## What this reviews

| File | Purpose |
|------|---------|
| `.tmp/admin_log.txt` | Operational events: run lifecycle, tool calls, mission status, audit |
| `.tmp/log.txt` | Verbose log: all DEBUG+ entries including provider HTTP and internal |
| `.tmp/run_summary.csv` | Per-run metrics: step count, retry counts, issue flags, finalized_at |
| `.tmp/p2_latest_run.log` | Last user_run report: missions, audit, answer |

## Steps

### 1. Read all artifacts

Read each file that exists. Note which are missing (indicates that entrypoint was never run).

### 2. Parse run_summary.csv

For each row extract:
- `run_id`, `status` (FAILED/PASSED), `step_count`, `tools_used_count`
- `invalid_json_retries`, `duplicate_tool_retries`, `memo_policy_retries`, `content_validation_retries`
- `memo_retrieve_hits`, `memo_retrieve_misses`
- `issue_flags` (comma-separated)
- `finalized_at`

Compute aggregates:
- Average step count, total retries by type, failure rate, most common issue flags

### 3. Parse admin_log.txt

Scan for these signal patterns and count/timestamp each:

| Pattern | Weak link indicator |
|---------|-------------------|
| `PLAN TIMEOUT MODE` | Planner timed out — provider too slow or context too large |
| `PLANNER STEP START ... timeout_mode=True` | Every step in timeout mode = degraded run |
| `TOOL RESULT step=N tool=... result={'stderr': ...returncode!=0}` | Tool execution failure |
| `SPECIALIST REDIRECT` repeats for same step | Mission stuck in specialist loop |
| `MISSION STATUS ... status=pending->failed` | Mission failure (tool error or bad result) |
| `AUDIT WARN` / `AUDIT FAIL` | Auditor detected integrity gaps |
| `RUN START` → `RUN FINALIZE` wall time | Total run duration (time between these lines) |

### 4. Parse log.txt for deep signals

Scan for:

| Pattern | Weak link indicator |
|---------|-------------------|
| `sqlite3.OperationalError` / `database is locked` | SQLite contention — concurrent writes or WAL checkpoint lag |
| `MAX_RESULT_JSON_BYTES` truncation messages | Tool result too large for context — SQLite row bloat |
| `context_evict` / `_evict_tool_result_messages` | Context pressure — tool history overflowing LLM context window |
| `token_budget_remaining=0` | Token budget exhausted — agent hit ceiling mid-run |
| `HTTP 500` / `RetryError` from provider | Provider instability |
| `CACHE REUSE HIT` vs `CACHE REUSE MISS` ratio | Memo effectiveness |
| Long gaps between `Sending HTTP Request` and `receive_response_headers.complete` | Provider latency (extract elapsed ms) |

### 5. Estimate SQLite lag

In log.txt, look for evidence of:
- Large `write_file` results being stored (tool result JSON > 10KB is a sign)
- Sequential DB writes to `run_store.db` after large tool outputs
- WAL file size: note if `.tmp/run_store.db-wal` exists (indicates uncommitted WAL growth)

Check if `.tmp/run_store.db-wal` exists and is non-empty — this is a direct indicator of WAL pressure.

### 6. Check context ceiling pressure

In admin_log.txt count:
- Total `TOOL EXEC` entries across all runs
- Runs where `PLANNER STEP` count > 15 (high step count = context inflation)
- Any `context_clear_requested` in p2_latest_run.log answer

In log.txt look for `_evict_tool_result_messages` or `context_evict` calls — these indicate the system hit the ceiling and had to drop history.

Note: there is no way for the **user** to `/clear` context mid-session in the CLI loop; the only reset is the `clear_context` tool call from the agent (scope=full) or restarting the session.

### 7. Derive weak link report

For each identified weak link, rate severity:
- **Critical**: causes data loss, wrong answers, or crashes
- **High**: causes retries, timeouts, or degraded accuracy
- **Medium**: causes lag, resource waste, or reduced observability
- **Low**: cosmetic or minor efficiency gap

## Output format

```
═══════════════════════════════════════════════════════════
 .TMP HEALTH REVIEW
═══════════════════════════════════════════════════════════

Artifacts found: [list files present / missing]

━━━━━━━━━━━━━━━━━━━━━━━
 RUN METRICS (run_summary.csv)
━━━━━━━━━━━━━━━━━━━━━━━
Total runs: N  |  Passed: N  |  Failed: N  (failure rate: X%)
Avg steps per run: N.N
Retry breakdown:
  invalid_json_retries:       total=N  avg=N.N per run
  duplicate_tool_retries:     total=N  avg=N.N per run
  memo_policy_retries:        total=N  avg=N.N per run
  content_validation_retries: total=N  avg=N.N per run
Memo cache hit rate: X% (hits=N misses=N)
Most common issue flags: [list with counts]

━━━━━━━━━━━━━━━━━━━━━━━
 OPERATIONAL SIGNALS (admin_log.txt)
━━━━━━━━━━━━━━━━━━━━━━━
PLAN TIMEOUT events:      N
Tool failures (returncode!=0): N  [tools: list]
Mission failures:         N
Audit warnings/fails:     N / N
Avg run wall time:        Xs (based on RUN START→RUN FINALIZE timestamps)

━━━━━━━━━━━━━━━━━━━━━━━
 DEEP SIGNALS (log.txt)
━━━━━━━━━━━━━━━━━━━━━━━
SQLite errors:            N  [type: ...]
Context evictions:        N
Token budget exhausted:   N runs
Provider HTTP errors:     N
Max provider latency:     Xms  |  Avg: Xms
WAL file present:         YES / NO  (size: Xkb)
Large tool results (>10KB): N occurrences

━━━━━━━━━━━━━━━━━━━━━━━
 LAST USER_RUN (p2_latest_run.log)
━━━━━━━━━━━━━━━━━━━━━━━
Run ID: ...
Missions: N  |  Audit: passed=N warned=N failed=N
[List any WARN/FAIL findings]

═══════════════════════════════════════════════════════════
 WEAK LINKS  (ranked by severity)
═══════════════════════════════════════════════════════════

[CRITICAL] Title
  Evidence: ...
  Root cause: ...
  Impact: ...
  Fix direction: ...

[HIGH] Title
  Evidence: ...
  Root cause: ...
  Impact: ...
  Fix direction: ...

[MEDIUM] ...

[LOW] ...

═══════════════════════════════════════════════════════════
 KNOWN STRUCTURAL CONSTRAINTS
═══════════════════════════════════════════════════════════

These are architecture-level limits (not bugs):

- SQLite as checkpoint store: single-writer, WAL flushes block on large rows.
  Replacement: AsyncPostgresSaver (Phase 7).

- No mid-session /clear for the user in cli/user_run.py:
  The agent can call clear_context tool, but the user has no direct context-reset
  without restarting the session. The rolling prior_context window (10 messages)
  is the only buffer.

- Token budget is a fixed ceiling per session (default 200k tokens), tracked by
  character-count estimation (len//4), not exact tokenization. Runs near the
  ceiling will trigger planner_timeout_mode silently.

- Tool results are stored in SQLite run_store.db per row. Large results (e.g.,
  read_file on a big file) bloat the DB and slow subsequent checkpoint saves.
  MAX_RESULT_JSON_BYTES truncation (added in stabilize feature) caps this but
  the row is still written.
```
