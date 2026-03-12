---
phase: 07.8-multi-model-provider-routing-+-smart-cloud-fallback
feature: stabilize-parser-planner-context
completed: "2026-03-10T18:12:00Z"
duration: 12min
tasks_completed: 3
tasks_total: 3
key-files:
  created:
    - tests/unit/test_parser_timeout.py
    - tests/unit/test_context_overflow.py
  modified:
    - src/agentic_workflows/orchestration/langgraph/mission_parser.py
    - src/agentic_workflows/orchestration/langgraph/graph.py
    - src/agentic_workflows/orchestration/langgraph/context_manager.py
    - src/agentic_workflows/orchestration/langgraph/state_schema.py
    - src/agentic_workflows/logger.py
decisions:
  - "Local models get 30s parser timeout (vs 5s for cloud) -- sufficient for Phi4/Qwen14B regex parsing"
  - "Intent classifier gets 5s for local models (vs 0.5s for cloud) -- prevents constant fallback"
  - "Planning always routes to strong model via mission_type=multi_step override in routing signals"
  - "Proactive compaction at 80% ctx_limit with aggressive fallback to system+5 messages"
  - "Context overflow caught in except block with one retry after compaction, then deterministic fallback"
  - "api_debug logger writes to .tmp/api.log via setup_dual_logging() file handler"
---

# Phase 7.8 Feature: Parser/Planner/Context Stabilization Summary

Adaptive parser timeout, proactive context compaction, structured debug logging, and strong-model planning routing for reliable multi-model local inference.

## Completed Tasks

| Task | Name | Commit | Key Changes |
|------|------|--------|-------------|
| 1 | Adaptive parser timeout + classifier timeout + structural_health | 0513ef2 | _adaptive_parser_timeout(), _adaptive_classifier_timeout(), parser_timeout_count |
| 2 | Proactive context compaction + overflow fallback | b4f9d85 | proactive_compact(), context overflow catch+retry, aggressive 5-msg fallback |
| 3 | Structured debug logging + strong model routing | 5805b7c | api_debug logger, PLANNER_STEP/PLANNER_PARSE/RUN_START logs, mission_type=multi_step |

## What Changed

### Parser Timeout (Task 1)
- `_adaptive_parser_timeout()`: 30s for LlamaCpp/Ollama, 5s for Groq/OpenAI
- `_adaptive_classifier_timeout()`: 5s for local, 0.5s for cloud
- `P1_PARSER_TIMEOUT_SECONDS` env var overrides auto-detection
- `parser_timeout_count` counter in structural_health
- Parser timeout fallback log upgraded from INFO to WARNING
- 12 tests in test_parser_timeout.py

### Context Compaction (Task 2)
- `proactive_compact(state, ctx_limit)` on ContextManager: triggers when estimated tokens > 80% of ctx_limit
- Standard sliding window compaction first, then aggressive (system + 5 messages) if still over
- Called in _plan_next_action() after existing compact() call, wrapped in try/except
- Context overflow errors (exceed_context_size, context length) caught in except block
- One retry after aggressive compaction, falls through to deterministic fallback on second failure
- 4 tests in test_context_overflow.py

### Debug Logging (Task 3)
- `api_debug` logger registered in graph.py, routed to .tmp/api.log via setup_dual_logging()
- `PLANNER_STEP`: model, provider, tier, routing_signals, tokens_est, output_preview
- `PLANNER_PARSE`: action, tool, fallback status
- `RUN_START`: run_id, missions, system_prompt_len, parser/classifier timeouts

### Strong Model Routing (Task 3)
- `mission_type` in RoutingSignals forced to `"multi_step"` in _plan_next_action()
- Ensures planning always routes to the strong model (Phi4) via route_by_signals()

## Deviations from Plan

None -- plan executed exactly as written.

## Test Results

- 1396 unit tests passing (12 new in test_parser_timeout.py, 4 new in test_context_overflow.py)
- Pre-existing failures: test_action_queue.py (1 unit), test_langgraph_flow.py (28 integration) -- not caused by these changes
- ruff check clean on all modified files (pre-existing I001/F401/UP037 in graph.py noted)

## Self-Check: PASSED

- [x] tests/unit/test_parser_timeout.py exists and passes
- [x] tests/unit/test_context_overflow.py exists and passes
- [x] Commit 0513ef2 exists (Task 1)
- [x] Commit b4f9d85 exists (Task 2)
- [x] Commit 5805b7c exists (Task 3)
- [x] _adaptive_parser_timeout importable from mission_parser
- [x] _adaptive_classifier_timeout importable from mission_parser
- [x] proactive_compact method on ContextManager
- [x] api_debug logger accessible via get_logger("api_debug")
