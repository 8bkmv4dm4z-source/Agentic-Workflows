# Phase 1 SOP: LangGraph Stateful Orchestrator

## Goal
Build a LangGraph-based orchestrator with:
- State graph execution
- Durable checkpointing via SQLite
- Schema-first memoization store
- Policy-based memoization enforcement for heavy deterministic work

This SOP is intentionally notebook-friendly while keeping production code in `execution/langgraph/`.

## Inputs
- User task prompt
- `.env` with `OPENAI_API_KEY` or `GROQ_API_KEY`
- Existing tool modules under `tools/`

## Outputs
- Run result object:
  - `answer`
  - `tools_used`
  - `run_id`
  - `memo_events`
- SQLite memo store at `.tmp/memo_store.db`
- Run audit row fields include provider/cache reliability counters:
  - `provider_timeout_retries`
  - `cache_reuse_hits`
  - `cache_reuse_misses`

## Run Steps
1. Install dependencies:
   - `python3 -m venv .venv`
   - `.venv/bin/pip install -r requirements.txt`
2. Optional timeout control:
   - set `P1_PLAN_CALL_TIMEOUT_SECONDS` (for example `20`) to bound planner wall time.
3. Run LangGraph orchestrator:
   - `.venv/bin/python -m execution.langgraph.run`
4. Inspect memo entries:
   - Use `SQLiteMemoStore.get(run_id=..., key=..., namespace="run")`
5. Inspect run audit:
   - `.venv/bin/python -m execution.langgraph.run_audit`

## Policy Rules
- Memoization is required for heavy deterministic `write_file` outputs.
- If the model skips memoization, orchestrator emits corrective system feedback.
- After max policy retries, run fails closed with `MemoizationPolicyViolation`.
- If planner times out, orchestrator may switch to deterministic timeout fallback actions.
- After first planner timeout, timeout mode may continue deterministic actions without further planner calls.

## Debugging
- If model returns invalid JSON repeatedly:
  - check provider model supports JSON mode
  - verify system prompt is first message
- If memo policy loops:
  - verify model can call `memoize`
  - lower task scope or increase `max_policy_retries` for diagnostics
- If provider fails:
  - set `OPENAI_API_KEY`; fallback is Groq in `build_provider`
- If planner is slow/stuck:
  - verify `PLAN PROVIDER CALL` / `PLAN PROVIDER TIMEOUT` logs
  - lower `P1_PLAN_CALL_TIMEOUT_SECONDS`
  - confirm `PLAN TIMEOUT FALLBACK` or `PLAN TIMEOUT MODE` appears
  - confirm mission still enforces memo policy (`memoize` before finish)
- If cache reuse is enabled:
  - confirm cache-hit `write_file` is attributed to the correct mission (no Task N -> Task N+1 shift)
  - confirm run does not finalize early when later missions are still incomplete

## Tool Inventory (12 tools)

Core tools: `repeat_message`, `sort_array`, `string_ops`, `math_stats`, `write_file`, `memoize`, `retrieve_memo`

Analysis/parsing tools (added 2026-02-28): `task_list_parser`, `text_analysis`, `data_analysis`, `json_parser`, `regex_matcher`

## Structured Mission Parser

- Entry point: `execution/langgraph/mission_parser.py::parse_missions()`
- Produces `StructuredPlan` with `MissionStep` objects (id, description, parent_id, suggested_tools, dependencies, status)
- Supports numbered tasks (`Task N:`), dot/paren format (`1.`, `2)`), bullet lists (`- `, `* `), and nested sub-tasks (`1a.`, `1.1`)
- Falls back to original regex extraction for unrecognized formats
- `Shared_plan.md` is written at run start and finalize with IMPLEMENTED/PENDING markers

## Extension Path (Phase 1 -> 2)
- Replace SQLite backend with Postgres implementation behind same store interface.
- Add semantic memo keying (beyond file-path exact/basename).
- Add `StateGraph` checkpointer and HITL interrupts for high-risk tools.
