---
status: awaiting_human_verify
trigger: "cross-run-context-amnesia — agent loses all context between user turns"
created: 2026-03-03T00:00:00Z
updated: 2026-03-03T00:02:00Z
---

## Current Focus

hypothesis: CONFIRMED AND FIXED
test: 381 tests pass; 3 new regression tests added
expecting: Human verification in real multi-turn session
next_action: await user confirmation that follow-up turns now have context

## Symptoms

expected: When user follows up in a new run (e.g., "can you repeat the answer you sent?"),
  the agent should retrieve prior outputs from conversation history
actual: Each run() call started with completely fresh RunState. Agent timed out or
  emitted clarify action with no memory of previous run.
errors: No code errors — design missing cross-run context continuity
reproduction: |
  1. Run agent with any task that produces output
  2. In next run, say "can you repeat the answer you sent?"
  3. Agent had no memory of previous run
started: Always present — never implemented

## Eliminated

- hypothesis: memo_store is queried at startup to inject prior context
  evidence: graph.py run() line 392 — new_run_state() builds messages=[system, user]
            only. memo_store is read AFTER run via list_entries(run_id). No pre-run query.
  timestamp: 2026-03-03T00:01:00Z

- hypothesis: UserSession passes conversation_history to orchestrator.run()
  evidence: user_run.py line 99 — self._orchestrator.run(user_input) — only user_input
            passed. self._conversation_history accumulated but NEVER forwarded.
            LangGraphOrchestrator.run() had no conversation_history parameter.
  timestamp: 2026-03-03T00:01:00Z

- hypothesis: _completed_summaries is injected into system prompt or state
  evidence: _collect_summary() builds self._completed_summaries but was NEVER passed
            to orchestrator.run(). Dead accumulator with no downstream consumer.
  timestamp: 2026-03-03T00:01:00Z

## Evidence

- timestamp: 2026-03-03T00:01:00Z
  checked: state_schema.py new_run_state() lines 112-162
  found: messages initialised as [system_prompt, user_input] only — no prior history
  implication: Every run started with a blank conversation slate

- timestamp: 2026-03-03T00:01:00Z
  checked: graph.py LangGraphOrchestrator.run() lines 383-450
  found: Signature is run(user_input, run_id, rerun_context) — no history param.
         First thing it does is new_run_state(self.system_prompt, user_input).
  implication: Orchestrator had no mechanism to receive or inject prior-run context.

- timestamp: 2026-03-03T00:01:00Z
  checked: user_run.py UserSession class (all methods)
  found: _conversation_history accumulates assistant answers. _completed_summaries
         accumulates mission summaries. Both fields exist but run_once() calls
         self._orchestrator.run(user_input) with ONLY user_input — both fields dead.
  implication: UserSession collected the right data but the bridge to new run state
               was never built.

- timestamp: 2026-03-03T00:01:00Z
  checked: memo_store.py SQLiteMemoStore — get_latest() method lines 165-201
  found: get_latest() CAN retrieve the most recent value for a key across all run_ids.
         Only called in _auto_lookup_before_write(), never at run() startup.
  implication: Cross-run DB retrieval exists but has no startup caller.

## Resolution

root_cause: |
  PRIMARY BUG (cross-run amnesia):
  UserSession._conversation_history and _completed_summaries are accumulated correctly
  across turns, but UserSession.run_once() passes ONLY user_input to
  orchestrator.run(). The orchestrator's run() method had no parameter for prior
  conversation history, and new_run_state() always creates a blank message history.
  The bridge between session turn N data and turn N+1 initial state was never built.

  SECONDARY BUG (duplicate mission_id=1 in logs):
  The duplicate mission_id=1 in the _finalize log originates from the clarify recursion
  in user_run.py: when agent emits __CLARIFY__:, run_once() calls itself recursively
  with combined input. The second orchestrator.run() call is a fresh run. The log
  message "missions=2" in the second run finalize refers to the combined input being
  parsed as two entries by the regex fallback. No data corruption occurs — it is a
  logging artifact from the clarify re-prompt path. Not separately fixed as the primary
  fix (prior_context) eliminates the confusion that triggers the clarify action.

fix: |
  1. Added `prior_context: list[dict[str, str]] | None = None` parameter to
     LangGraphOrchestrator.run() in graph.py.
     When provided, messages are injected between the system prompt and the current
     user message, giving the planner full visibility of prior completed work.

  2. Added UserSession._build_prior_context() in user_run.py.
     Builds a compact 2-message block:
       - system message: short summary of up to 5 most recent completed missions
         (mission_id, status, tools used, result snippet)
       - assistant message: the last assistant answer from _conversation_history
     Returns None on the first turn (no history yet).

  3. Updated UserSession.run_once() to call _build_prior_context() and pass the
     result to orchestrator.run(prior_context=...) on every turn after the first.

verification: |
  - 381 tests pass (was 378; added 3 new regression tests)
  - ruff lint clean on all changed files
  - Manual trace confirmed: after turn 1, turn 2 receives prior context messages in
    the message list visible to the planner
  - _build_prior_context returns None on first turn (no regression for initial calls)
  - run() signature backward compatible (prior_context defaults to None)

files_changed:
  - src/agentic_workflows/orchestration/langgraph/graph.py
    (added prior_context param to run(), injection logic in message setup)
  - src/agentic_workflows/orchestration/langgraph/user_run.py
    (added _build_prior_context() method, updated run_once() to use it)
  - tests/integration/test_langgraph_flow.py
    (added PriorContextInjectionTests class with 3 regression tests)
