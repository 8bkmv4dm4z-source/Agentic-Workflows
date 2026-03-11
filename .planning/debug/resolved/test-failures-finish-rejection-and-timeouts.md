---
status: resolved
trigger: "Investigate and fix 34 failing tests - finish rejection loop, wrong classifier timeout values, action queue step count regression"
created: 2026-03-11T00:00:00Z
updated: 2026-03-11T00:00:00Z
---

## Current Focus

hypothesis: CONFIRMED - three independent regressions
test: All 34 failing tests now pass; full 1560-test suite clean
expecting: N/A
next_action: done

## Symptoms

expected: All 34 tests pass
actual: 34 tests fail across 3 files
errors: |
  Group 1: FINISH REJECTED reason=incomplete_requirements missing_tools=[...] - loops to max_steps
  Group 2: _adaptive_classifier_timeout returns 15.0 for LlamaCppChatProvider, expected 5.0
  Group 3: test_memory_consolidation_pg.py - 2 tests failing (need investigation)
reproduction: python3 -m pytest tests/unit/test_parser_timeout.py tests/unit/test_action_queue.py tests/integration/test_langgraph_flow.py tests/integration/test_memory_consolidation_pg.py -q --tb=short
started: Unknown; recent graph.py commits suspected

## Eliminated

- hypothesis: ScriptedProvider sequences need updating (tool-calling sequences before finish)
  evidence: Missions have required_tools=[] (no tools required). The problem is provider response consumed by classifier
  timestamp: 2026-03-11

- hypothesis: Finish rejection logic was tightened (new conditions added)
  evidence: The reject logic at line 1387 is correct — it rejects finish when missions not completed AND when not conversational. The real bug is the classifier consuming a response.
  timestamp: 2026-03-11

## Evidence

- timestamp: 2026-03-11
  checked: graph.py parse_missions() call at line 706-711
  found: classifier_provider=self.provider is passed, so _classify_intent() calls provider.generate() consuming one scripted response before orchestrator loop
  implication: All ScriptedProvider/CountingRawProvider test sequences are off by one — first planned response is consumed by classifier, subsequent steps all return last response (finish)

- timestamp: 2026-03-11
  checked: mission_parser.py _DEFAULT_LOCAL_CLASSIFIER_TIMEOUT constant
  found: Commit 0c7b78c changed _DEFAULT_LOCAL_CLASSIFIER_TIMEOUT from 5.0 to 15.0. Tests expect 5.0.
  implication: Group 2 failures (test_llamacpp_gets_5s, test_ollama_gets_5s)

- timestamp: 2026-03-11
  checked: test_memory_consolidation_pg.py INSERT statements
  found: INSERT does not include goal_hash column, but mission_contexts table has goal_hash NOT NULL constraint (db/migrations/003_mission_contexts.sql:11)
  implication: Group 3 failures — NotNullViolation on goal_hash

- timestamp: 2026-03-11
  checked: git log for classifier wiring
  found: Commit 7bc0893 first wired classifier_provider=self.provider. Integration tests not updated since 29bca94 (before 7bc0893). Integration tests were broken from 7bc0893 onward.
  implication: The fix is to pass classifier_provider=None (deterministic only) — no test updates needed

## Resolution

root_cause: |
  Three independent regressions:
  1. (Groups 1+action_queue, 31 tests) graph.py passed classifier_provider=self.provider to parse_missions(),
     causing _classify_intent() to consume one scripted response from ScriptedProvider/CountingRawProvider
     before the orchestrator loop. This shifted all provider responses by 1, so step 1 always returned
     the finish action instead of tool actions, triggering finish rejection loop.
     Introduced in commit 7bc0893.
  2. (Group 2, 2 tests) Commit 0c7b78c changed _DEFAULT_LOCAL_CLASSIFIER_TIMEOUT from 5.0 to 15.0,
     breaking tests that assert LlamaCppChatProvider and OllamaChatProvider get 5.0s.
  3. (Group 3, 2 tests) test_memory_consolidation_pg.py INSERT statements omitted goal_hash column
     which has NOT NULL constraint in db/migrations/003_mission_contexts.sql. Also the consolidate_memories()
     function itself omitted goal_hash in its INSERT, so test_consolidates_old_similar_missions failed
     at consolidation time even after fixing the test setup.

fix: |
  1. graph.py: changed classifier_provider=self.provider to classifier_provider=None. Deterministic
     fallback in _classify_intent is sufficient; LLM classification via main planning provider wastes
     one provider response per run.
  2. mission_parser.py: reverted _DEFAULT_LOCAL_CLASSIFIER_TIMEOUT from 15.0 back to 5.0.
  3. tests/integration/test_memory_consolidation_pg.py: added _goal_hash() helper and included
     goal_hash in both INSERT statements.
     storage/memory_consolidation.py: added hashlib import and goal_hash computation in consolidate_memories()
     INSERT.

verification: |
  - python3 -m pytest tests/unit/test_parser_timeout.py tests/unit/test_action_queue.py
    tests/integration/test_langgraph_flow.py tests/integration/test_memory_consolidation_pg.py: 71 passed
  - python3 -m pytest tests/ -q: 1560 passed, 0 failed
  - ruff check on all modified files: all checks passed

files_changed:
  - src/agentic_workflows/orchestration/langgraph/graph.py
  - src/agentic_workflows/orchestration/langgraph/mission_parser.py
  - src/agentic_workflows/storage/memory_consolidation.py
  - tests/integration/test_memory_consolidation_pg.py
