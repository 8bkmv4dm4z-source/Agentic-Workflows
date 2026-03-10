---
phase: quick-5
plan: 01
subsystem: orchestration/provider
tags: [schema-enforcement, tool-registry, compact-prompt, provider-protocol]
dependency_graph:
  requires: []
  provides: [Tool.required_args, _build_action_json_schema, response_schema param on all providers]
  affects: [graph.py, provider.py, tools/base.py, conftest.py, test provider stubs]
tech_stack:
  added: []
  patterns: [anyOf JSON schema from live tool registry, arg-signature hints in compact prompt]
key_files:
  created: []
  modified:
    - src/agentic_workflows/tools/base.py
    - src/agentic_workflows/orchestration/langgraph/graph.py
    - src/agentic_workflows/orchestration/langgraph/provider.py
    - tests/conftest.py
    - tests/integration/test_langgraph_flow.py
    - tests/integration/test_model_router_integration.py
    - tests/unit/test_mission_completion.py
    - tests/unit/test_prompt_tier.py
    - tests/unit/test_structural_health.py
    - tests/unit/test_directives.py
    - tests/unit/test_action_queue.py
decisions:
  - Tool.required_args() uses regex to parse "Required args: x (type), y (type)" from description
  - _tool_sig() inner function uses `object` annotation (always in scope, no import needed)
  - _action_json_schema cached at __init__ time after build_tool_registry()
  - OpenAI uses dynamic schema preferentially over static _OPENAI_ACTION_RESPONSE_FORMAT constant
  - LlamaCpp uses response_schema as response_format only when grammar is disabled
  - Groq and Ollama accept and silently ignore response_schema
  - All test provider stubs updated with response_schema=None to match new protocol
metrics:
  duration: ~7min
  completed: 2026-03-10
  tasks: 3
  files: 11
---

# Phase quick-5 Plan 01: Tool Schema Enforcement and Compact Prompt Signatures Summary

**One-liner:** Added arg-signature hints to compact prompt and built a dynamic anyOf JSON schema from the live tool registry for OpenAI/LlamaCpp response_format enforcement.

## Tasks Completed

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 1 | Add required_args() to Tool base + compact prompt arg signatures | 42c6aad | base.py, graph.py |
| 2 | Update ChatProvider Protocol and all concrete providers with response_schema param | 9116236 | provider.py, conftest.py |
| 3 | Add _build_action_json_schema() + wire to _generate_with_hard_timeout() call sites | 29bca94 | graph.py + 7 test files |

## What Was Built

**Tool.required_args()** — New method on Tool base class parses `Required args: x (str), y (str)` segments from tool description strings, returning ordered arg name list. Tools without a Required args section return `[]`.

**Compact prompt arg signatures** — The compact prompt's `Available tools:` line now shows `write_file(path, content)` instead of bare `write_file` for tools that declare required args in their description. An inner `_tool_sig()` function handles both cases.

**ChatProvider Protocol update** — All five provider implementations (OpenAI, Groq, Ollama, LlamaCpp, ScriptedProvider) now accept `response_schema: dict | None = None`. OpenAI uses the dynamic schema preferentially; LlamaCpp applies it when grammar is disabled; Groq and Ollama silently ignore it.

**_build_action_json_schema()** — New orchestrator method builds an anyOf JSON schema covering every registered tool (with required args as string properties) plus finish and clarify action variants. Cached as `self._action_json_schema` at `__init__` time immediately after `build_tool_registry()`. 37 tool variants produced from the live registry.

**generate() call sites wired** — Both paths in `_generate_with_hard_timeout()` (direct no-timeout path and threaded path) now pass `response_schema=self._action_json_schema`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Test provider stubs missing response_schema param**
- **Found during:** Task 3 test run
- **Issue:** Multiple test-local provider classes (`RawScriptedProvider`, `InvalidJSONProvider`, `ScriptedProvider` in test_langgraph_flow.py, `TrackedScriptedProvider`, `DummyProvider`, `BlockingProvider`, `TimeoutThenSuccessProvider`, `CountingRawProvider`) all had `generate(self, messages)` without the new param, causing `unexpected keyword argument 'response_schema'` errors at runtime
- **Fix:** Added `response_schema=None` to all test provider generate() signatures across 7 test files
- **Files modified:** tests/integration/test_langgraph_flow.py, tests/integration/test_model_router_integration.py, tests/unit/test_mission_completion.py, tests/unit/test_prompt_tier.py, tests/unit/test_structural_health.py, tests/unit/test_directives.py, tests/unit/test_action_queue.py
- **Commit:** 29bca94 (included in Task 3 commit)

## Verification

- `Tool.required_args()` correctly parses `path (str), content (str)` → `['path', 'content']`
- `Tool.required_args()` returns `[]` when no Required args section exists
- `LangGraphOrchestrator._action_json_schema` has `type='json_schema'` with 37 tool variants + finish + clarify
- 1304 tests pass (was 823+ at plan writing time; count grew due to prior work)
- ruff check clean on all modified files

## Self-Check: PASSED

- `src/agentic_workflows/tools/base.py` — exists with required_args() method
- `src/agentic_workflows/orchestration/langgraph/graph.py` — contains _build_action_json_schema, _tool_sig, _action_json_schema
- `src/agentic_workflows/orchestration/langgraph/provider.py` — contains response_schema in all generate() signatures
- Commits 42c6aad, 9116236, 29bca94 — all present in git log
