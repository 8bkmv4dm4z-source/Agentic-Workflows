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

## 15) Bugfixes — 2026-03-01

### What was fixed

**1. Action Queue (pending_action_queue)**
- Multi-action batching: planner can emit multiple JSON actions in one response; all are parsed and enqueued (`_extract_all_json_objects`, `_parse_all_actions_json` in `graph.py`).
- Queue-pop: subsequent plan nodes pop the next action from the queue instead of calling the provider.
- Timeout clear: when timeout mode is entered, the queue is drained to prevent stale queued actions from executing out of order.
- State fields: `pending_action_queue: list[dict]` in `state_schema.py`; initialized to `[]` in `new_run_state` and `ensure_state_defaults`.

**2. Recursion limit ×3 scaling**
- `self._compiled.invoke(state, config={"recursion_limit": self.max_steps * 3})` in `graph.py` line ~168.
- Prevents premature recursion limit errors on longer runs without inflating `max_steps`.

**3. Mission completion write-guard**
- Non-`write_file` tools are blocked from claiming write-keyword missions (preventing early mission completion on a `memoize` call).
- Implemented in `graph.py:_record_mission_tool_event`.

**4. Post-run Mission Auditor (`mission_auditor.py`)**
- New file: `src/agentic_workflows/orchestration/langgraph/mission_auditor.py`
- Deterministic, keyword-driven post-run checks — no LLM calls.
- Six check types: `tool_presence`, `count_match`, `chain_integrity`, `fibonacci_count`, `mean_reuse`, `write_file_success`.
- `chain_integrity` check catches the Mission 2 bug: `data_analysis` returned 12 `non_outliers` but `sort_array` received 11 (150 dropped by planner).
- `fibonacci_count` check catches the Mission 5 bug: fib50.txt had 339 chars, expected ≥ 420 for 50 numbers.
- Called in `graph.py:_finalize()` after mission logging; result stored in `state["audit_report"]` and returned in `run()`.
- Unit tests: `tests/unit/test_mission_auditor.py`

**5. Dynamic Fibonacci validator**
- `graph.py:_validate_tool_result_for_active_mission` now extracts N from the mission text via `_extract_fibonacci_count()` instead of hardcoding 100.
- Validates fib-50, fib-30, etc. correctly at write time.

### Test count
151 tests passing (0 failures, 0 errors). New tests in `tests/unit/test_mission_auditor.py`.

---

## 18) Audit/Re-run System Bugfixes — 2026-03-01 (post-live-run)

Five bugs found from `lastRun.txt` analysis after the auditor was first exercised in a live run.

### Bug A — `[r]` re-ran WARN missions (user-confirmed)

**File:** `run.py:_get_failed_missions`

**Problem:** Filter was `f.get("level") in ("fail", "warn")` — pressing `[r]` re-ran any mission that had a warning, even if nothing actually failed.

**Fix:** Changed to `f.get("level") == "fail"`. Only hard failures trigger re-run.

---

### Bug B — Re-run lost sub-task context (user-confirmed)

**File:** `run.py:_build_rerun_input`

**Problem:** Used `r.get("mission", "")` which contains only the short mission title (e.g. `"Task 2: Data Analysis and Sorting"`). All sub-task data (inline lists, JSON samples, text blocks) from the original prompt was stripped.

**Fix:** Added `original_input: str = ""` parameter. For each failed mission, extracts the full task block using:
```python
pattern = rf"Task\s+{mid}\s*:.*?(?=Task\s+\d+\s*:|$)"
re.search(pattern, original_input, re.DOTALL | re.IGNORECASE)
```
The extracted block is used verbatim — all sub-tasks and inline data are preserved. Falls back to `r.get("mission")` if extraction fails.

`_correction_loop` updated to pass `original_input` through to `_build_rerun_input`.

---

### Bug C — Double `"Task N:"` prefix (log-confirmed)

**Evidence:** `lastRun.txt` line 68 showed `"Task 1: Task 1: Text Analysis Pipeline"`.

**Problem:** `_build_rerun_input` prepended `f"Task {mid}: {mission}"` but `mission` already started with `"Task 1:"`.

**Fix:** Bug B's extraction naturally avoids this (the extracted block already starts with `"Task N:"`). In the fallback path, a guard prevents double-prefix:
```python
if not re.match(r"Task\s+\d+", mission_text, re.IGNORECASE):
    mission_text = f"Task {mid}: {mission_text}"
```

---

### Bug D — `tool_presence` false positives (log-confirmed)

**File:** `mission_auditor.py:_check_tool_presence`

**Evidence:** Run had 0/5 clean missions. The `"analysis"` keyword maps to `["text_analysis", "data_analysis"]`. Any mission with "analysis" in its text got warned about both tools even when one of them ran.

**Problem:** Old logic: iterate each suggested tool and warn if absent. This warned about `data_analysis` for a mission that used `text_analysis` (and vice versa) — treating alternatives as requirements.

**Fix:** Group-based logic with `frozenset` deduplication. A finding is only emitted when **none** of the tools in a keyword group were used:
```python
if not any(t in used_tools for t in tool_group):
    # warn: none from this group ran
```
Multiple keywords mapping to the same tool group (e.g. `"analyze"` + `"analysis"`) produce at most one finding via `checked_groups: set[frozenset[str]]`.

---

### Bug E — Fibonacci validator fired on unrelated writes (log-confirmed)

**File:** `graph.py:_validate_tool_result_for_active_mission`

**Evidence:** Tool #6 was `write_file` for `analysis_results.txt` but was rejected with `content_validation_failed`. Tasks 1–4 each completed with one tool, so Task 5 (Fibonacci) became the active mission. When `analysis_results.txt` was written, the validator applied fibonacci integer-sequence validation to non-integer content.

**Problem:** No path guard — any `write_file` call while a fibonacci mission was active would be validated as fibonacci content.

**Fix:** Added path guard before the mission text check:
```python
path = str(tool_args.get("path", "")).lower()
if "fib" not in path:
    return None  # not a fibonacci file — skip content validation
```

---

### Test count
165 tests passing (0 failures, 0 errors). +14 new tests:
- `tests/unit/test_run_helpers.py` — 11 tests covering Bugs A, B, C
- `tests/unit/test_mission_auditor.py` — 3 new tests covering Bug D group logic

### Quick run commands (updated paths)

```bash
# All tests
.venv/bin/python -m pytest tests/ -q

# Unit tests only
.venv/bin/python -m pytest tests/unit/ -q

# Integration tests
.venv/bin/python -m pytest tests/integration/ -q

# Main run (with audit panel)
.venv/bin/python -m agentic_workflows.orchestration.langgraph.run

# Audit summary (all past runs)
.venv/bin/python -m agentic_workflows.orchestration.langgraph.run_audit
```

---

## 19) ReviewLastRun Skill Analysis — 2026-03-01

Skill located at `.claude/skills/review-last-run.md`. Run against `lastRun.txt` (two runs: initial + `[r]` re-run).

### Run 1 (4d82488c) — Initial run

**Mission attribution: BROKEN across all missions.**
- Mission 1 only gets `text_analysis`. Missions 2, 3, 4 each get one tool from Task 1/2 (sequential attribution).
- Mission 5 becomes a catch-all for all remaining tools (15 tools from Tasks 2–5).
- Root cause: `_record_mission_tool_event` completes a mission on the first tool that matches, in execution order. When the planner emits a large multi-task action batch, missions 1–4 each get the first tool that runs, leaving everything else to mission 5.

**fib50.txt (Run 1):** Written with 48 numbers and malformed content (`'0, 1, 1, 2 5, , 3,8, ...'` — space-before-comma, empty token). Cached as `hash=8ae0dd6e...`. POISONED.

**Finish claim:** Planner constructed a plausible-sounding answer from memory/context, not from actual mission tracking. "All 5 tasks completed" is false — Task 5 has 48 numbers and malformed CSV.

**Audit accuracy:** Passed=1, warned=4, failed=1 (chain_integrity M5). Correct that chain failed, but misses M2/M3/M4 attribution failures entirely.

### Run 2 (c86dcbf7) — Re-run (triggered before today's Bug B/C fix)

**fib50.txt written with Task 4 regex output:** At step 11, the planner's queued batch included `write_file fib50.txt` with `content='1, 2, 3, 5, 10, 45.99, 123, 229.95'` — the numbers extracted by `regex_matcher` from Task 4's text. Cached as `hash=748caf86...`. POISONED.

**Content validator silently dropped:** `content_validation_retries=0` despite `45.99` being non-integer. The validator fires and returns an error string, but when the action comes from the queue (not from a live planner call), the retry feedback path is suppressed. **Bug F2: content validation errors on queue-popped actions are silently dropped.**

**Premature finish via timeout:** Planner timed out at step 12. `PLAN TIMEOUT FALLBACK` memoized the (wrong) fib50.txt result. `PLAN TIMEOUT MODE` immediately synthesized `finish` citing `result='memoized'` as proof of completion. **Bug F3: finish criterion in timeout mode is "memoize returned success" regardless of content.**

**Audit false clean:** Mission 5 showed PASS. `_check_fibonacci_file_size` skipped because the mission title `"Task 5: Fibonacci with Analysis"` has no digit count — the "first 50" sub-task text was stripped from the re-run prompt. **Bug F5: fibonacci count check requires digit in mission title, not tool history.**

### Open Bugs Identified (not yet fixed)

| ID | Description | File |
|----|-------------|------|
| F1 | Mission attribution is sequential, not semantic — multi-task batches pollute all mission reports | `graph.py:_record_mission_tool_event` |
| F2 | Content validation errors on queue-popped actions silently dropped | `graph.py` execute node queue-pop path |
| F3 | Timeout-mode finish uses `memoize returned success` as completion proof | `graph.py` timeout fallback / finalize |
| F4 | Cache stores any content without correctness check — poisoning on wrong writes | `graph.py` cache write path |
| F5 | `_check_fibonacci_file_size` requires count digit in mission title — misses re-run scenario | `mission_auditor.py` |

---

## 16) Recommended Next Steps

1. **Chain integrity planner hint** — when a tool result's list is about to be passed to the next tool, inject a system message pinning the exact count: `"Use exactly these N items from the previous result: [...]"`. This prevents the 150-drop class of bugs at the source (planner transcription error) rather than detecting them post-hoc.

2. **Read_file tool registration** — `tools/read_file.py` exists but is not registered in `tools_registry.py`. Adding it lets the planner (and the auditor) verify file contents post-write, closing the loop on write correctness.

3. **Structured result propagation** — add a `use_result` argument to tools that accept a prior tool's output by reference (tool history index). This removes the transcription error vector entirely: the planner passes an index instead of re-typing a list.

4. **Mission auditor surfaced in run console** — the auditor is now integrated; the `AUDIT REVIEW` panel in `run.py` surfaces `PASS/WARN/FAIL` interactively. For CI/non-interactive runs, findings are appended to `lastRun.txt` automatically.

5. **Phase 2 target — multi-agent orchestration** — one planner agent + N specialized executor agents, each owning a domain (text, data, file I/O). Eliminates cross-domain planner confusion and allows parallel mission execution with domain-expert sub-agents.

---

## 17) Prompt plan for next iteration

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

---

## 20) LastRun Communication Analysis — 2026-03-02

Analysis of `lastRun.txt` covering two runs (initial d8c070e3 + re-run 48ede961).

### Run 1 (d8c070e3): 5 missions, 21 tool calls, 18 steps

| Mission | Status | Summary |
|---------|--------|---------|
| M1: Text Analysis | PASS | `text_analysis` → `string_ops` → `write_file` all succeeded. 15 chars to `analysis_results.txt`. |
| M2: Data Analysis | WARN | Pipeline ran (`data_analysis` ×2 → `sort_array` → `math_stats`). `math_stats` mean computed on 5 items instead of 12 non_outliers (planner passed subset). |
| M3: JSON Processing | PASS | `json_parser` → `regex_matcher` → `sort_array` → `write_file`. 17 chars to `users_sorted.txt`. |
| M4: Pattern Matching | FAIL | `regex_matcher` extracted 5 numbers correctly. `math_stats` sum=413.94, mean=82.788. But `write_file` failed 2× with `content_validation_failed` — planner formatted content with bracket prefix `'[123'`. Pattern report never written. |
| M5: Fibonacci | FAIL | `write_file` failed with `content_validation_failed` — planner sent non-CSV content. `fib50.txt` never written. 0 integers. |

**Communication patterns:**
1. **Content formatting bottleneck** — 3 `content_validation_retries`. Planner can extract correct numbers via tools but cannot format `write_file` content string correctly.
2. **No timeout mode** — Both runs completed without `PLAN TIMEOUT MODE`. Honest fail-closed: `"Run failed closed after repeated deterministic content validation failures."`
3. **Mean-reuse data loss** — M2 `math_stats` received 5 items instead of 12 non_outliers. Planner transcription error (same class as the old 150-drop bug).
4. **Retry distribution:** `content_validation=3`, `duplicate_tool=1`, all others 0.

### Run 2 (48ede961): Re-run of 3 failed missions (M3, M4, M5)

| Re-run Mission | Status | Summary |
|----------------|--------|---------|
| M3 re-run | PASS | Clean execution. |
| M4 re-run | PASS | Clean execution. |
| M5 re-run | FAIL | `write_file` failed 3× with `content_validation_failed`. Planner still cannot format fibonacci CSV. |

**False positives in audit:**
- `repeat_message` flagged as missing in M5 — the "echo" sub-keyword in mission text maps to `repeat_message` via `_TOOL_KEYWORD_MAP`, but fibonacci missions don't need `repeat_message`.
- Mission 3 audit found `pattern_report.txt` non-numeric token — this is cross-contamination from M4's `write_file` call being attributed to M3's audit scope during run 1.

### Open issues from this run

| Issue | Severity | Component |
|-------|----------|-----------|
| Planner cannot format `write_file` content as valid CSV/report | High | Planner prompt / content validation |
| `math_stats` mean computed on planner-transcribed subset | Medium | Planner data propagation |
| `repeat_message` false positive in fibonacci mission audit | Low | `mission_auditor.py` keyword filter |
| Cross-mission `pattern_report.txt` audit contamination | Low | Audit scope isolation |
