---
status: fixing
trigger: "Too many concurrent requests on large-directory tasks + Langfuse Cloud setup"
created: 2026-03-03T00:00:00Z
updated: 2026-03-03T00:10:00Z
---

## Current Focus

hypothesis: CONFIRMED — rapid sequential queue drain with zero inter-tool delay causes rate limit saturation.
test: Applied fix and ran 329 unit tests — all pass. Ruff check clean.
expecting: With P1_INTER_TOOL_DELAY_SECONDS=0.5 set in .env, queue pops will pause 0.5s between each batch item.
next_action: Human verification — set env var and run large-directory mission to confirm no rate limit errors.

## Symptoms

expected: When given "read all files in dir X and summarize each", agent should process files sequentially with controlled pace (≤3 at once or with delay) to avoid rate limits.
actual: Agent fires all read_file calls in rapid succession — all N actions land in pending_action_queue at once, drained as fast as the graph loop runs.
errors: "rate limit exceeded" identified in graph.py line 1784 as an unrecoverable error marker.
reproduction: Give agent "Read all Python files in src/agentic_workflows/tools/ and summarize each file, write summary to tools_summary.md"
started: Present since Phase 1 — no concurrency controls ever added to the tool execution path.

## Eliminated

- hypothesis: True async parallelism (asyncio, ThreadPoolExecutor) launching simultaneous HTTP calls
  evidence: Entire graph is synchronous (no asyncio.gather, no ThreadPoolExecutor). pending_action_queue is drained sequentially one item per graph step. The problem is rapid-fire sequential calls, not true parallelism.
  timestamp: 2026-03-03T00:00:00Z

## Evidence

- timestamp: 2026-03-03T00:00:00Z
  checked: graph.py lines 713-755 (_plan_next_action — multi-action parse path)
  found: When LLM produces N JSON action objects in one response, tagged_actions[1:] are stored in state["pending_action_queue"] (line 755). First action is dispatched immediately. Queue is drained on subsequent steps (line 590).
  implication: All N read_file calls (one per file) get queued in a single LLM call and are dispatched back-to-back with zero delay. For a directory with 12 files that means 12 sequential provider-adjacent tool calls with no pacing.

- timestamp: 2026-03-03T00:00:00Z
  checked: graph.py lines 588-640 (queue drain path)
  found: Queue pop at line 590 does queue.pop(0), sets pending_action, returns immediately. No sleep, no semaphore, no delay.
  implication: Between each queue pop (each graph step), the only latency is graph bookkeeping (checkpoint save, logging). No rate-limiting protection.

- timestamp: 2026-03-03T00:00:00Z
  checked: graph.py line 1774-1788 (_is_unrecoverable_plan_error)
  found: "rate limit exceeded" is classified as an UNRECOVERABLE error — causes immediate fail-closed. This means hitting a rate limit is fatal to the run.
  implication: When the rapid-fire queue hits a provider rate limit, the run dies. It does NOT retry with backoff.

- timestamp: 2026-03-03T00:00:00Z
  checked: provider.py lines 117-121
  found: Provider has retry backoff (sleep between LLM call retries) but only for planning calls, not tool dispatch. Tool calls (read_file etc.) are local/deterministic and do not hit the provider — so provider backoff is irrelevant here.
  implication: The rate-limit pressure is entirely on the PLANNING calls (each queue-popped action still triggers a provider call on the NEXT step). The fix needs to add delay between queue pops to space out planning calls.

- timestamp: 2026-03-03T00:00:00Z
  checked: pyproject.toml
  found: langfuse in optional extras [observability] = ["langfuse>=3.0"]. NOT in core dependencies or [dev] extras.
  implication: Developer must install with: pip install -e ".[observability]" to get Langfuse. The package will be absent in a default dev install.

- timestamp: 2026-03-03T00:00:00Z
  checked: graph.py lines 161-181 (_build_langfuse_handler) and lines 414-422 (run() Langfuse wiring)
  found: Langfuse handler is built via lazy import from agentic_workflows.observability. Handler is passed as a LangChain callback in base_config["callbacks"]. Wiring is correct — if LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set, tracing will activate automatically.
  implication: The code is complete. Only credentials are needed to activate.

- timestamp: 2026-03-03T00:00:00Z
  checked: .env.example lines 22-26
  found: LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are commented out. LANGFUSE_HOST comment says "omit for cloud" but the variable itself has no default value in code — cloud.langfuse.com is the SDK default when HOST is omitted.
  implication: Setting public/secret keys is sufficient for cloud. HOST only needed for self-hosted instances.

## Resolution

root_cause: |
  BUG (concurrent requests): The LLM planner can emit N tool calls in one JSON response. These N actions are placed into pending_action_queue all at once (graph.py:755). The queue is drained one item per graph step with zero inter-step delay. For large-directory read missions (e.g. "read all 12 files in tools/"), this produces 12 back-to-back planning cycles in rapid succession, each triggering a provider API call immediately after the last completes. This saturates rate limits. The mechanism is rapid sequential dispatch, not true parallelism.

  LANGFUSE: Code is fully wired. The langfuse package is in [observability] extras (not [dev]). Only missing: cloud credentials + install with observability extra.

fix: |
  1. Added `import time` to graph.py imports.
  2. Added P1_INTER_TOOL_DELAY_SECONDS env var (default 0.0).
     Applied time.sleep(delay) inside the queue-pop branch of _plan_next_action,
     after popping and before returning. Logged as INTER_TOOL_DELAY when active.
  3. Updated .env.example: added P1_INTER_TOOL_DELAY_SECONDS block + clarified
     LANGFUSE_HOST default (https://cloud.langfuse.com) + install instruction.

verification: |
  329 unit tests pass (python3 -m pytest tests/unit/ -q).
  ruff check clean on graph.py.
  Awaiting human verification of large-directory mission behavior.

files_changed:
  - src/agentic_workflows/orchestration/langgraph/graph.py
    (added import time; added inter-tool delay block in queue-pop path, lines ~588-648)
  - .env.example
    (added P1_INTER_TOOL_DELAY_SECONDS section; clarified LANGFUSE_HOST and install steps)
