---
status: resolved
trigger: "tool-result-truncation-dead-code: on_tool_result string mismatch in context_manager.py causes large tool results (5000+ chars) to bypass the large_result_threshold check and flood the planner context"
created: 2026-03-11T00:00:00Z
updated: 2026-03-11T00:10:00Z
---

## Current Focus

hypothesis: All three hypotheses H1/H2/H3 confirmed. Applying fix: gate truncation BEFORE append in _execute_action, correct string format, set threshold=1500 at instantiation.
test: Verified all three by reading context_manager.py and graph.py source
expecting: After fix, large results never enter state["messages"] at full size
next_action: Apply fixes to context_manager.py and graph.py, add test

## Symptoms

expected: Tool results exceeding large_result_threshold (1500 chars) are truncated/replaced with a compact summary before reaching the planner at the next step.
actual: A search_files() call returning a 5000-char JSON blob was NOT truncated. The full blob entered state["messages"], the planner timed out after 300s with 3 retries.
errors: "PROVIDER RETRY attempt=2/3 error=Request timed out" x3, then "PLAN PROVIDER TIMEOUT step=2 timeout_count=1"
reproduction: Run any mission that uses search_files, list_directory, or parse_code_structure on a large directory.
started: Bug has existed since ContextManager was introduced (Phase 7.1)

## Eliminated

- hypothesis: The threshold check itself was broken (off-by-one, wrong comparison)
  evidence: Comparison code `if result_len > self.large_result_threshold` is correct; the problem is the string to match after append and the default threshold being too high
  timestamp: 2026-03-11T00:00:30Z

## Evidence

- timestamp: 2026-03-11T00:00:10Z
  checked: context_manager.py on_tool_result(), lines 624-641
  found: Search string is `f"TOOL RESULT ({tool_name})"` (space between TOOL and RESULT, no #N)
  implication: H1 CONFIRMED — this never matches actual message format

- timestamp: 2026-03-11T00:00:15Z
  checked: graph.py _execute_action(), lines 2453-2475
  found: Message is appended at line 2453 with format `f"TOOL_RESULT #{call_number} ({tool_name}):"` (underscore, with step number). on_tool_result() called AFTER at line 2473.
  implication: H2 CONFIRMED — append happens BEFORE truncation attempt; retroactive patch approach is fragile

- timestamp: 2026-03-11T00:00:20Z
  checked: graph.py ContextManager instantiation, line 277-281
  found: ContextManager() called with no large_result_threshold argument; class default is 4000 (line 247)
  implication: H3 CONFIRMED — effective threshold is 4000, not 1500 as MEMORY.md documents

## Resolution

root_cause: Three compounding bugs: (1) on_tool_result searches for "TOOL RESULT (name)" but messages use "TOOL_RESULT #N (name):" format — never matches; (2) message is appended BEFORE on_tool_result is called, so retroactive replacement is the only option (fragile); (3) ContextManager default threshold is 4000 but no explicit value is passed at instantiation site.
fix: (1) Added primary gate in graph.py _execute_action: compute _tool_result_for_msg BEFORE appending to messages — if len > threshold, use placeholder string instead of full JSON; (2) Fixed retroactive fallback in on_tool_result to use correct format "TOOL_RESULT" (underscore) with "({tool_name})" — covers retrieve_memo/write_file code paths; (3) Added explicit large_result_threshold=800 and sliding_window_cap=20 at ContextManager instantiation in graph.py; (4) Updated pre-existing tests that used wrong format to use correct format; added 10 new regression tests.
verification: 1566 tests pass (all unit + integration); 10 new tests in test_context_manager_truncation.py all pass
files_changed:
  - src/agentic_workflows/orchestration/langgraph/context_manager.py
  - src/agentic_workflows/orchestration/langgraph/graph.py
  - tests/unit/test_context_eviction.py
  - tests/unit/test_context_manager.py
  - tests/unit/test_context_manager_truncation.py (new)
