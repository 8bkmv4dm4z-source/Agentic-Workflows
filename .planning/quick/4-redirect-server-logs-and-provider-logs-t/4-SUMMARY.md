---
phase: quick-4
plan: 4
subsystem: logging / cli / api
tags: [logging, observability, server-logs, provider-logs, user-run, lifespan]
dependency_graph:
  requires: []
  provides: [server_logs_visibility, provider_debug_logs, append_mode_logs]
  affects: [logger.py, user_run.py, app.py]
tech_stack:
  added: []
  patterns: [stdlib-logging-file-handlers, subprocess-output-capture, lifespan-init]
key_files:
  modified:
    - src/agentic_workflows/logger.py
    - src/agentic_workflows/cli/user_run.py
    - src/agentic_workflows/api/app.py
decisions:
  - "Use mode='a' for all four FileHandlers so log files accumulate across sessions"
  - "Attach provider_handler to langgraph.provider + agentic_workflows + langgraph (three loggers) for full coverage"
  - "Open server_logs.txt file handle before Popen and pass as stdout/stderr — handle intentionally stays open for lifetime of subprocess"
  - "Pass GSD_LOG_DIR env var to subprocess so server can self-wire its own stdlib handlers via setup_dual_logging"
  - "Call setup_dual_logging in lifespan() not at module level — avoids side effects at import time"
  - "uvicorn --log-level info (was warning) so HTTP access lines appear in server_logs.txt"
metrics:
  duration: "~2 minutes"
  completed_date: "2026-03-07"
  tasks_completed: 3
  files_modified: 3
---

# Phase quick-4: Redirect Server Logs and Provider Logs

**One-liner:** Full DEBUG-level logging to `.tmp/server_logs.txt` (uvicorn subprocess stdout) and `.tmp/provider_logs.txt` (stdlib handlers on three loggers), all in append mode.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Fix logger.py — widen provider_logs.txt scope and level | d7f81cc | src/agentic_workflows/logger.py |
| 2 | Fix user_run.py — redirect subprocess output to server_logs.txt | 49457cd | src/agentic_workflows/cli/user_run.py |
| 3 | Fix app.py lifespan — call setup_dual_logging in server process | 40e33f5 | src/agentic_workflows/api/app.py |

## What Was Built

### Task 1 — logger.py
- Changed `provider_handler.setLevel(logging.ERROR)` to `logging.DEBUG`
- Changed `FileHandler` constructor to use `mode="a"` on all four handlers (log.txt, admin_log.txt, server_logs.txt, provider_logs.txt)
- Extended provider_handler attachment from `langgraph.provider` only to all three loggers: `langgraph.provider`, `agentic_workflows`, `langgraph` — using a `for _name in (...)` loop with `propagate = True` on each

### Task 2 — user_run.py
- In `_ensure_server_running()`, before `Popen`, now opens `_TMP_DIR / "server_logs.txt"` in `"a"` mode and saves the file handle as `_server_log_fh`
- Replaces `stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL` with `stdout=_server_log_fh, stderr=_server_log_fh`
- Builds `env = {**os.environ, "GSD_LOG_DIR": str(_TMP_DIR)}` and passes `env=env` to Popen
- Changes `--log-level` argument from `"warning"` to `"info"` so uvicorn emits HTTP access lines

### Task 3 — app.py
- Adds three lines at top of `lifespan()` body: imports `setup_dual_logging`, reads `GSD_LOG_DIR` env var (defaults to `.tmp`), calls `_setup_logging(log_dir=_log_dir)`
- The `_setup_done` guard makes this idempotent; tests using httpx ASGITransport bypass lifespan entirely

## Verification

All 657 tests pass after changes:
```
657 passed in 22.77s
```

Task 1 automated verify (provider_logs content assertions): PASS
Task 2 automated verify (source text assertions): PASS
Task 3 automated verify (full pytest suite): PASS

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

- [x] `src/agentic_workflows/logger.py` modified (mode="a", DEBUG level, three loggers)
- [x] `src/agentic_workflows/cli/user_run.py` modified (server_logs.txt, GSD_LOG_DIR, log-level info)
- [x] `src/agentic_workflows/api/app.py` modified (setup_dual_logging in lifespan)
- [x] Commit d7f81cc exists (Task 1)
- [x] Commit 49457cd exists (Task 2)
- [x] Commit 40e33f5 exists (Task 3)

## Self-Check: PASSED
