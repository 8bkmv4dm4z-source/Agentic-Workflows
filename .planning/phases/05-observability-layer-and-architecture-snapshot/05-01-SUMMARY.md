---
plan: 05-01
status: completed
requirement: OBSV-01
requirements_completed: [OBSV-01]
---

## Summary

Wired Langfuse 3.x CallbackHandler into the LangGraph orchestrator (additive-only).

## Changes Made

### src/agentic_workflows/observability.py
- Fixed dual-path import: tries `langfuse.decorators.observe` (2.x) then falls back to `langfuse.observe` (3.x)
- `_langfuse_available` is now `True` with langfuse 3.x installed
- Added `get_langfuse_callback_handler()` — returns `LangchainCallbackHandler` when configured, `None` otherwise

### src/agentic_workflows/orchestration/langgraph/graph.py
- Added `from agentic_workflows.observability import get_langfuse_callback_handler`
- Initialized `self._active_callbacks: list[Any] = []` in `__init__()` (prevents AttributeError on direct method calls)
- At `run()` start: builds `_active_callbacks` from `get_langfuse_callback_handler()`
- `self._compiled.invoke()` receives `config={"recursion_limit": N, "callbacks": self._active_callbacks}`
- `self._executor_subgraph.invoke()` receives `config={"callbacks": self._active_callbacks}`

### src/agentic_workflows/orchestration/langgraph/provider.py
- Added `from agentic_workflows.observability import observe`
- `@observe(name="provider.generate")` applied to `OllamaChatProvider.generate`

### tests/unit/test_observability.py (new)
- 4 structural tests all pass:
  - `test_langfuse_available_with_3x` — `_langfuse_available is True`
  - `test_get_langfuse_callback_handler_returns_none_without_creds` — returns `None` without env vars
  - `test_callback_handler_wired_in_graph_invoke` — source inspection confirms `_active_callbacks` in `run()`
  - `test_ollama_generate_has_observe_decorator` — `OllamaChatProvider.generate` has `__wrapped__`

## Self-Check: PASSED

- `_langfuse_available` prints `True` ✓
- `OllamaChatProvider.generate.__wrapped__` exists ✓
- All 427 tests pass (394 existing + 7 new from this phase + others already added) ✓
- No regressions ✓
