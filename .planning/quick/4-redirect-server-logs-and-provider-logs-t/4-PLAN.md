---
phase: quick-4
plan: 4
type: execute
wave: 1
depends_on: []
files_modified:
  - src/agentic_workflows/logger.py
  - src/agentic_workflows/cli/user_run.py
  - src/agentic_workflows/api/app.py
autonomous: true
requirements: [QUICK-4]

must_haves:
  truths:
    - "server_logs.txt receives uvicorn stdout/stderr from the auto-started subprocess"
    - "provider_logs.txt captures DEBUG-level events from provider/graph/tool loggers (not ERROR+ only)"
    - "Running user_run.py twice appends to log files instead of overwriting them"
    - "When uvicorn is already running, log file setup in the client process still completes without error"
    - "Distinct content: server_logs.txt has HTTP/uvicorn lines; provider_logs.txt has LLM provider lines"
  artifacts:
    - path: "src/agentic_workflows/logger.py"
      provides: "Fixed provider_logs.txt handler (DEBUG level, wider logger scope)"
    - path: "src/agentic_workflows/cli/user_run.py"
      provides: "Subprocess stdout/stderr redirected to .tmp/server_logs.txt file handle"
    - path: "src/agentic_workflows/api/app.py"
      provides: "lifespan calls setup_dual_logging() so stdlib logging is wired in server process"
  key_links:
    - from: "user_run.py _ensure_server_running()"
      to: ".tmp/server_logs.txt"
      via: "open() file handle passed as stdout= and stderr= to subprocess.Popen"
    - from: "app.py lifespan()"
      to: "setup_dual_logging()"
      via: "call with GSD_LOG_DIR env var or .tmp default"
    - from: "logger.py provider_handler"
      to: "langgraph.provider + agentic_workflows loggers"
      via: "addHandler on each named logger at DEBUG level"
---

<objective>
Redirect server-side output (uvicorn HTTP logs, structlog API events, stdlib LLM provider logs) to
separate .tmp/ files with full DEBUG visibility when running via user_run.py.

Purpose: Currently all server subprocess output is silently discarded (stdout=DEVNULL, stderr=DEVNULL)
and provider_logs.txt only captures ERROR-level events. Operators cannot see what the server or
provider layer is doing without attaching a debugger.

Output:
- .tmp/server_logs.txt — uvicorn stdout/stderr (HTTP request lines, startup banners, warnings)
- .tmp/provider_logs.txt — DEBUG+ from langgraph.provider, agentic_workflows, langgraph loggers
- .tmp/log.txt and admin_log.txt — unchanged behavior
</objective>

<execution_context>
@/home/nir/.claude/get-shit-done/workflows/execute-plan.md
@/home/nir/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@src/agentic_workflows/logger.py
@src/agentic_workflows/cli/user_run.py
@src/agentic_workflows/api/app.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix logger.py — widen provider_logs.txt scope and level</name>
  <files>src/agentic_workflows/logger.py</files>
  <action>
    In `setup_dual_logging()`, replace the single `provider_handler` block (lines 95-99) with:

    1. Change `provider_handler.setLevel(logging.ERROR)` to `provider_handler.setLevel(logging.DEBUG)`.
    2. Change the FileHandler mode from default 'w' to append mode: `logging.FileHandler(log_path / "provider_logs.txt", mode="a")`.
    3. Attach the handler to three loggers instead of one: `langgraph.provider`, `agentic_workflows`, and `langgraph`. For each:
       ```python
       for _name in ("langgraph.provider", "agentic_workflows", "langgraph"):
           _lg = logging.getLogger(_name)
           _lg.addHandler(provider_handler)
           _lg.propagate = True
       ```
    4. Also change the verbose_handler and admin_handler and server_handler FileHandler calls to use `mode="a"` so all log files accumulate across sessions.

    The `_setup_done` guard already ensures idempotency — no change needed there.

    Do NOT change _ADMIN_PREFIXES, AdminFilter, or get_logger().
  </action>
  <verify>
    <automated>python -c "
import logging, tempfile, os
from pathlib import Path
tmp = tempfile.mkdtemp()
import agentic_workflows.logger as L
L._setup_done = False
L.setup_dual_logging(log_dir=tmp)
logging.getLogger('agentic_workflows').info('TEST_PROVIDER_INFO')
logging.getLogger('langgraph.provider').warning('TEST_PROVIDER_WARN')
logging.getLogger('langgraph').debug('TEST_LG_DEBUG')
plog = Path(tmp) / 'provider_logs.txt'
content = plog.read_text()
assert 'TEST_PROVIDER_INFO' in content, f'missing INFO: {content}'
assert 'TEST_PROVIDER_WARN' in content, f'missing WARN: {content}'
assert 'TEST_LG_DEBUG' in content, f'missing DEBUG: {content}'
print('PASS: provider_logs captures DEBUG+ from all three loggers')
L._setup_done = False
"
</automated>
  </verify>
  <done>
    provider_logs.txt receives DEBUG+ log records from langgraph.provider, agentic_workflows, and
    langgraph loggers. All four file handlers open in append mode.
  </done>
</task>

<task type="auto">
  <name>Task 2: Fix user_run.py — redirect subprocess output to server_logs.txt</name>
  <files>src/agentic_workflows/cli/user_run.py</files>
  <action>
    In `_ensure_server_running()`, replace the `subprocess.Popen(...)` call block to:

    1. Before the `subprocess.Popen` call (inside the `if attempt == 0:` block), open the server log
       file in append mode and save the handle:
       ```python
       _TMP_DIR.mkdir(parents=True, exist_ok=True)
       _server_log_fh = open(_TMP_DIR / "server_logs.txt", "a")  # noqa: SIM115
       ```
    2. Replace `stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL` with
       `stdout=_server_log_fh, stderr=_server_log_fh`.
    3. Pass the `GSD_LOG_DIR` env var so the server subprocess knows where to write its own handlers:
       ```python
       env = {**os.environ, "GSD_LOG_DIR": str(_TMP_DIR)}
       ```
       Add `env=env` to the Popen call.
    4. The file handle intentionally stays open (Popen inherits it and owns stdout/stderr for the
       lifetime of the child process). This is the correct pattern for a long-running subprocess.

    All other Popen arguments (start_new_session, --log-level, etc.) remain unchanged.

    Note: `--log-level warning` is passed to uvicorn. Change it to `--log-level info` so uvicorn
    emits HTTP access lines (200 GET /health etc.) that will appear in server_logs.txt.
  </action>
  <verify>
    <automated>python -c "
import ast, pathlib
src = pathlib.Path('src/agentic_workflows/cli/user_run.py').read_text()
assert 'server_logs.txt' in src, 'server_logs.txt file handle missing'
assert 'GSD_LOG_DIR' in src, 'GSD_LOG_DIR env var not passed'
assert 'DEVNULL' not in src or src.count('DEVNULL') == 0, 'DEVNULL still present'
assert 'log-level\",\n                    \"info' in src or '\"--log-level\", \"info\"' in src or \"'info'\" in src, 'log-level not changed to info'
print('PASS: user_run.py correctly redirects subprocess output')
"
</automated>
  </verify>
  <done>
    Auto-started uvicorn subprocess writes stdout and stderr to .tmp/server_logs.txt in append mode.
    GSD_LOG_DIR env var is passed to the subprocess. uvicorn log-level is info.
  </done>
</task>

<task type="auto">
  <name>Task 3: Fix app.py lifespan — call setup_dual_logging in server process</name>
  <files>src/agentic_workflows/api/app.py</files>
  <action>
    In the `lifespan()` function, add a `setup_dual_logging()` call at the very top of the function
    body (before the `log.info("api.startup", ...)` call), so the server subprocess installs stdlib
    file handlers for its own logger tree:

    ```python
    from agentic_workflows.logger import setup_dual_logging as _setup_logging
    _log_dir = os.environ.get("GSD_LOG_DIR", ".tmp")
    _setup_logging(log_dir=_log_dir)
    ```

    This is safe:
    - `_setup_done` guard in setup_dual_logging() makes it idempotent.
    - When tests bypass lifespan (httpx ASGITransport), this code never runs — no test impact.
    - When uvicorn is started manually (not via user_run.py), GSD_LOG_DIR defaults to ".tmp".

    Do NOT change anything else in app.py (middleware, routes, error handlers, structlog config).
    Do NOT add a structlog file sink — stdlib handlers attached to "agentic_workflows" and "langgraph"
    loggers already capture the provider/graph/tool output via Task 1.
  </action>
  <verify>
    <automated>python -m pytest tests/ -q --tb=short -x 2>&1 | tail -20</automated>
  </verify>
  <done>
    lifespan() calls setup_dual_logging() using GSD_LOG_DIR env var. Full test suite still passes.
    server_logs.txt and provider_logs.txt are written by the server process when auto-started.
  </done>
</task>

</tasks>

<verification>
Manual smoke test (optional — requires live provider):
1. Start fresh: `rm -f .tmp/server_logs.txt .tmp/provider_logs.txt`
2. Run: `python -m agentic_workflows.cli.user_run`
3. Submit a simple mission (e.g. "What is 2+2?")
4. Check `.tmp/server_logs.txt` — should contain uvicorn HTTP lines (GET /health 200, POST /run 200)
5. Check `.tmp/provider_logs.txt` — should contain DEBUG/INFO lines from agentic_workflows logger
   (model selected, token budget, planner step events)
6. Run again — files should grow (append mode), not be truncated

Automated: `pytest tests/ -q --tb=short -x` must pass (Task 3 verify command).
</verification>

<success_criteria>
- .tmp/server_logs.txt receives uvicorn stdout/stderr from auto-started subprocess
- .tmp/provider_logs.txt captures DEBUG+ from langgraph.provider, agentic_workflows, langgraph
- All log files open in append mode (multiple CLI sessions accumulate)
- setup_dual_logging() called in server process via lifespan() using GSD_LOG_DIR
- Existing test suite passes without modification
</success_criteria>

<output>
After completion, create `.planning/quick/4-redirect-server-logs-and-provider-logs-t/4-SUMMARY.md`
</output>
