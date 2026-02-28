# Phase 1 Walkthrough (LangGraph)

This is the practical guide to move from your Phase 0 loop to Phase 1 graph orchestration.

## 1) What Phase 1 means

Phase 0 (`p0/main.py`, `p0/orchestrator.py`) proved:
- tool-calling loop
- schema validation
- retries and finish action

Phase 1 adds:
- explicit graph/state orchestration (`StateGraph`)
- durable checkpoints
- schema-backed memoization store
- policy enforcement (memo required for heavy deterministic writes)

## 2) P0 -> P1 file mapping

- P0 loop: `p0/orchestrator.py`
- P1 orchestrator entrypoint (Phase 0-style naming): `execution/langgraph/langgraph_orchestrator.py`
- P1 graph implementation (actual LangGraph nodes + tool/provider execution): `execution/langgraph/graph.py`

- P0 state assumptions: `p0/agent_state.py`
- P1 typed/defaulted state: `execution/langgraph/state_schema.py`

- P0 provider: `p0/llm_provider.py`
- P1 provider boundary: `execution/langgraph/provider.py`

- P0 memoize tool wrote direct files: `tools/memoize.py`
- P1 memo store + retrieval:
  - `execution/langgraph/memo_store.py`
  - `execution/langgraph/tools_registry.py`

- P0 logging only
- P1 durable snapshots: `execution/langgraph/checkpoint_store.py`

## 3) Setup (venv + kernel)

1. Create/activate venv:
   - `python3 -m venv .venv`
   - `source .venv/bin/activate`
2. Install deps:
   - `pip install -r requirements.txt`
3. Jupyter kernel must use `.venv/bin/python`.
4. Each notebook has a bootstrap cell that:
   - resolves repo root
   - injects repo root into `sys.path`
   - prints kernel path and warns if not `.venv`

## 4) Notebook order (one notebook per Phase 1 core file)

Start here:
- `execution/notebooks/phase1_langgraph_walkthrough.ipynb`

Then run in order:
1. `execution/notebooks/p1_state_schema.ipynb`
2. `execution/notebooks/p1_provider.ipynb`
3. `execution/notebooks/p1_policy.ipynb`
4. `execution/notebooks/p1_memo_store.ipynb`
5. `execution/notebooks/p1_checkpoint_store.ipynb`
6. `execution/notebooks/p1_tools_registry.ipynb`
7. `execution/notebooks/p1_graph_orchestrator.ipynb`

Directory index:
- `execution/langgraph/langgraph_code_walkthrough.ipynb`

## 5) LangGraph basics in this repo

- Node flow:
  - `plan -> execute -> policy -> finalize`
- Runtime wiring:
  - `LangGraphOrchestrator` uses `build_provider()` from `execution/langgraph/provider.py`
  - tool map comes from `build_tool_registry()` in `execution/langgraph/tools_registry.py`
- State is repaired on each node entry using `ensure_state_defaults`.
- Duplicate tool calls are blocked via `seen_tool_signatures`.
- Memoization policy:
  - heavy deterministic writes require `memoize`
  - skipped memoization triggers bounded retry feedback
- Checkpoints are written across node transitions for replay/debug.

## 6) What still needs to be made (to fully close Phase 1)

- install and run live `langgraph` runtime in your environment
- validate full live run with real provider (not only scripted provider)
- mark Phase 1 checklist in `deep-research-report.md` only after live validation
- optional: add LangGraph checkpointer integration directly (beyond custom checkpoint store)
- optional: add second framework prototype (LlamaIndex or Haystack) per original Phase 1 roadmap

## 7) Quick run commands

- Unit tests:
  - `.venv/bin/python -m unittest tests/test_memo_store.py tests/test_memo_policy.py tests/test_langgraph_flow.py`
- LangGraph entrypoint:
  - `.venv/bin/python -c "from execution.langgraph.langgraph_orchestrator import LangGraphOrchestrator; print(LangGraphOrchestrator.__name__)"`
  - `.venv/bin/python -m execution.langgraph.run`
- Run audit summary (all runs):
  - `.venv/bin/python -m execution.langgraph.run_audit`
  - includes `provider_timeout`, `cache_hit`, and `cache_miss` columns

## 8) Common pitfalls

- `ModuleNotFoundError: execution`
  - run notebook bootstrap cell first and confirm kernel is `.venv`.
- key errors like `messages` / `retry_counts`
  - restart kernel and re-run all cells top-to-bottom to load latest `ensure_state_defaults` logic.
- repeated wrong tool loops
  - inspect `retry_counts` and `tool_call_counts` in notebook debug cells.

## 9) Diff summary (current P1 fixes)

The latest diff touched these files:
- `execution/langgraph/langgraph_orchestrator.py` (new)
- `execution/langgraph/graph.py`
- `execution/langgraph/run.py`
- `execution/langgraph/__init__.py`
- `tests/test_langgraph_flow.py`

What changed in `graph.py`:
- Added stricter planning guardrails and structured logging:
  - unrecoverable provider error detection (fail fast)
  - bounded invalid-plan retries via `max_invalid_plan_retries`
- Added mission-aware execution tracking:
  - task extraction from numbered/task-style prompts
  - `mission_report` and `completed_tasks` updates tied to tool execution
- Added duplicate-loop escape behavior:
  - if all missions are complete and the model repeats a duplicate call, force `finish`
  - preserve pending `finish` in plan node (prevents plan from overwriting terminal state)
- Added planner output resilience:
  - parse first balanced JSON object if model emits extra JSON objects in one response
- Added arg normalization:
  - `sort_array`: `array`/`values` -> `items`
  - `repeat_message`: `text` -> `message`
  - `string_ops`: `op` -> `operation`
  - `write_file`: `file_path`/`filename` -> `path`, `text`/`data` -> `content`
  - `memoize`: `data` -> `value`

What changed in runtime exports:
- `execution/langgraph/run.py` imports via `execution.langgraph.langgraph_orchestrator`.
- `execution/langgraph/__init__.py` exports `LangGraphOrchestrator` from the same entrypoint.

What changed in tests (`tests/test_langgraph_flow.py`):
- Added failure-mode tests for:
  - unrecoverable model-not-found handling
  - invalid JSON fail-closed behavior
  - multi-JSON response recovery
  - arg alias normalization (`array` -> `items`)
  - duplicate-after-completion auto-finish

## 10) Known bug from live run (2026-02-28)

Observed behavior:
- Planner initially completed tasks 1-3 correctly.
- At task 4 the provider emitted XML-ish tool-call text:
  - `<minimax:tool_call> ... <invoke name="write_file"> ...`
- This is not valid JSON, so plan node treated it as invalid output.
- After retry feedback, model drifted into repeated `repeat_message` calls.

Root cause:
- Some models/providers do not honor `response_format={"type":"json_object"}` consistently and can emit vendor-specific function-call text.
- Current recovery only handles malformed JSON that still contains a JSON object; it does not convert XML-ish tool-call payloads.

Current mitigation:
- Invalid-plan retries are bounded and fail closed instead of infinite recursion.
- Duplicate exact calls are blocked.
- But duplicate retries are not yet fail-closed when the model keeps choosing the same already-completed tool while remaining tasks are incomplete.
- Deterministic content validation now checks active Fibonacci file tasks and rejects malformed sequence payloads before mission completion.

Next improvement (recommended):
- Add a second-stage parser that translates known XML-ish tool-call envelopes into canonical action JSON, or hard fail earlier when provider/model repeatedly violates JSON contract.
- Add `max_duplicate_tool_retries` fail-closed behavior so persistent duplicate drift cannot consume the whole recursion budget.

## 12) Planner Timeout Bottleneck Fix (2026-02-28)

Observed issue:
- Runs completed tasks 1-3 quickly, then stalled on task 4 (`write_file fib.txt`) because planner calls timed out repeatedly.
- This produced long waits (`PLAN PROVIDER CALL ...`, then repeated timeout warnings) and delayed finalization.

Implemented behavior (now standard):
- Hard planner wall-time timeout:
  - `P1_PLAN_CALL_TIMEOUT_SECONDS` controls maximum wall-clock time for each planner call.
  - Planner call is wrapped with a hard timeout guard in orchestrator, independent of provider SDK timeout behavior.
- Deterministic timeout fallback:
  - On planner timeout, orchestrator synthesizes the next safe action from local state/mission text (no model call).
  - Supports `repeat_message`, `sort_array`, `string_ops`, and Fibonacci `write_file`.
- Timeout mode:
  - After first timeout, `planner_timeout_mode=True` is set in state.
  - While active, planner calls are skipped and deterministic actions continue until run completes or no safe fallback exists.
- Memo policy still enforced:
  - If `write_file` triggers memo-required policy, fallback prioritizes `memoize` before `finish`.
- Cross-run write cache:
  - Orchestrator stores reusable `write_file` inputs in `namespace="cache"` and can reuse them on future runs before planner call.

What logs should look like now:
- First timeout event:
  - `PLAN PROVIDER TIMEOUT ...`
  - `PLAN TIMEOUT FALLBACK ...`
- Follow-up steps during degraded mode:
  - `PLAN TIMEOUT MODE ...`
  - no additional long planner waits for memoize/finish path
- Cache behavior remains explicit:
  - `MEMO GET LATEST HIT/MISS ...`
  - `CACHE REUSE HIT/MISS ...`

Why this fix worked:
- The bottleneck was planner latency, not tool execution.
- By moving post-timeout decisions to deterministic orchestration:
  - we removed repeated slow planner round-trips,
  - preserved policy correctness (`memoize` before completion),
  - and finished runs using local state transitions.
- Result: timeout paths are now bounded, auditable, and fast.

Regression tests that lock this behavior:
- `tests/test_langgraph_flow.py::test_hard_timeout_handles_blocking_provider`
- `tests/test_langgraph_flow.py::test_provider_timeout_uses_deterministic_fallback_for_fibonacci_write`
- `tests/test_langgraph_flow.py::test_cross_run_write_cache_reuse_skips_planner_generation`

## 13) Cache-Hit Mission Attribution Fix (2026-02-28)

Observed issue:
- On a run with 5 tasks, Task 4 (`write_file fib.txt`) was auto-completed from cache.
- The `write_file` tool result was incorrectly attached to Task 5 in mission report.
- Orchestrator then finalized early with "All tasks completed", skipping Task 5 intent.

Root cause:
- In cache-hit flow, Task 4 was appended to `completed_tasks` before mission event recording.
- Mission index selection in `_record_mission_tool_event` used `len(completed_tasks)`, which shifted attribution to the next mission (Task 5).

Implemented behavior:
- Cache-hit path now pins the target mission index before recording the tool event.
- `_record_mission_tool_event` accepts optional `mission_index` and uses it when provided.
- Cache-hit write result is attached to Task 4 deterministically.
- Task 5 remains pending and planner continues instead of finishing early.

Regression test:
- `tests/test_langgraph_flow.py::test_cache_hit_keeps_followup_mission_index_alignment`

## 14) Enhanced Mission Parser, New Tools, and Shared Plan (2026-02-28)

### What was implemented

**7 new files created:**

| File | Purpose |
|------|---------|
| `execution/langgraph/mission_parser.py` | Structured mission parser with `MissionStep`/`StructuredPlan` dataclasses, sub-task detection (1a/1b, 1.1/1.2), tool suggestion heuristics, dependency inference, and regex fallback |
| `tools/task_list_parser.py` | Tool wrapper around `parse_missions()` |
| `tools/text_analysis.py` | Text analytics: word/sentence/char count, key terms, complexity, paragraphs, unique words, full report |
| `tools/data_analysis.py` | Numeric analytics: summary stats, IQR outliers, percentiles, distribution, correlation, normalize, z-scores |
| `tools/json_parser.py` | JSON parse/validate/extract_keys/flatten/get_path/pretty_print/count_elements |
| `tools/regex_matcher.py` | Regex find_all/find_first/split/replace/match/count_matches/extract_groups (100KB safety limit) |
| `tests/test_mission_parser.py` | 13 unit tests for the mission parser |
| `tests/test_new_tools.py` | 40 unit tests across all 5 new tools |

**5 existing files modified:**

| File | Changes |
|------|---------|
| `execution/langgraph/state_schema.py` | Added `structured_plan` field to `RunState`, `new_run_state()`, and `ensure_state_defaults()` |
| `execution/langgraph/tools_registry.py` | Registered 5 new tools in `build_tool_registry()` |
| `execution/langgraph/graph.py` | Integrated mission parser in `run()`, added `_write_shared_plan()` method (called at init + finalize), added 5 new tools to system prompt, added arg normalization for `text_analysis`/`data_analysis`/`regex_matcher` |
| `execution/langgraph/run.py` | Replaced demo prompt with richer 5-task prompt exercising sub-tasks and cross-tool pipelines |
| `tests/test_langgraph_flow.py` | Added 9 integration tests (structured plan in state, backward compat, text_analysis/data_analysis in flow, Shared_plan.md written, all 12 tools in prompt, 3 arg normalization tests) |

### Why it worked

1. **Backward compatibility preserved.** The mission parser produces `flat_missions` that match the exact format the orchestrator already uses for `state["missions"]`. The old `_extract_missions()` regex logic is preserved verbatim as `_extract_missions_regex_fallback()` inside the parser module, so any input that worked before still works identically.

2. **Layered parsing with fallback.** The parser tries structured numbered tasks first, then bullet lists, then falls back to the original regex. This means richer inputs get sub-task support while simple inputs degrade gracefully. A 5-second timeout wrapper prevents runaway parsing on huge inputs.

3. **State schema is additive-only.** The `structured_plan` field defaults to `None` and `ensure_state_defaults()` backfills it, so existing serialized states and checkpoint stores remain compatible.

4. **New tools follow the existing `Tool` base class pattern.** Each tool has `name`, `description`, and `execute(args) -> dict`. They plug directly into `build_tool_registry()` and the system prompt tool reference without changing any execution pipeline code.

5. **Shared_plan.md is written via direct file I/O**, not through the tool pipeline. This avoids triggering memo policy enforcement, audit noise, and duplicate-call detection. It's called at run start (after parsing) and in `_finalize()` (with completion status). Each step is marked `IMPLEMENTED` or `PENDING` so other agents can pick up the plan.

6. **Arg normalization extends cleanly.** The `_normalize_tool_args()` method already had per-tool alias mappings. Adding `text_analysis` (`op`→`operation`), `data_analysis` (`data`/`values`→`numbers`), and `regex_matcher` (`regex`→`pattern`) follows the same pattern with no structural changes.

7. **No changes to graph topology or routing.** The plan→execute→policy→finalize flow is untouched. The parser integration is purely at the `run()` entry point, and Shared_plan.md writing is in `_finalize()`. All existing guardrails (duplicate detection, memo policy, timeout fallback, content validation) work unchanged.

### Test results

94 tests, all passing (0 failures, 0 errors). This includes:
- 13 mission parser unit tests
- 40 new tool unit tests (across 5 tools)
- 9 new integration tests in `test_langgraph_flow.py`
- All 32 original tests passing unchanged

### Tool inventory (now 12 tools)

| Tool | Category |
|------|----------|
| `repeat_message` | Echo/debug |
| `sort_array` | Array manipulation |
| `string_ops` | String transforms |
| `math_stats` | Single math operations |
| `write_file` | File output |
| `memoize` | Memo store write |
| `retrieve_memo` | Memo store read |
| `task_list_parser` | Mission parsing |
| `text_analysis` | Text analytics |
| `data_analysis` | Numeric analytics |
| `json_parser` | JSON operations |
| `regex_matcher` | Regex operations |

## 15) Prompt plan for next iteration

Use this exact user prompt template when running `execution.langgraph.run`:

1. Put a strict output contract first:
   - "Return exactly one JSON object, no markdown, no XML, no tool-call tags."
2. Re-state valid schemas:
   - `{"action":"tool","tool_name":"...","args":{...}}`
   - `{"action":"finish","answer":"..."}`
3. Pin task order and completion policy:
   - "Execute tasks in order. Do not repeat completed tool calls. Finish only after all tasks."
4. Pin task-4 write behavior:
   - "Use `write_file` with `path` and full `content`."
5. Pin memo policy:
   - "If instructed by system policy, call `memoize` immediately before any other tool."
6. Add violation fallback:
   - "If unsure, output `finish` with an error summary in valid JSON rather than non-JSON text."
