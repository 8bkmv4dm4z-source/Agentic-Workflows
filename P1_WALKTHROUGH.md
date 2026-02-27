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

## 11) Prompt plan for next iteration

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
