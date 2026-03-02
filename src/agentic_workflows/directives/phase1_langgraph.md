# Phase 1 SOP: LangGraph Stateful Orchestrator

## Goal

Build and operate a LangGraph-based orchestrator with:

- state graph execution (`plan -> execute -> policy -> finalize`)
- durable checkpointing via SQLite
- schema-first memoization store
- policy enforcement for heavy deterministic work
- deterministic post-run auditing

Implementation path in this repo:
`src/agentic_workflows/orchestration/langgraph/`

## Inputs

- user task prompt
- `.env` provider configuration (`P1_PROVIDER` plus provider-specific credentials)
- deterministic tools in `src/agentic_workflows/tools/`

## Outputs

- run result object containing:
  - `answer`
  - `tools_used`
  - `run_id`
  - `memo_events`
  - `mission_report`
  - `audit_report`
- SQLite memo store at `.tmp/memo_store.db`
- SQLite checkpoint snapshots at `.tmp/langgraph_checkpoints.db`
- optional run summary CSV from `run_audit.py`

## Run Steps

1. Install dependencies:
   - `pip install -e ".[dev]"`
2. Optional timeout control:
   - set `P1_PLAN_CALL_TIMEOUT_SECONDS` (for example `20`) to bound planner wall time.
3. Run orchestrator demo:
   - `python -m agentic_workflows.orchestration.langgraph.run`
4. Inspect run audit summary:
   - `python -m agentic_workflows.orchestration.langgraph.run_audit`
5. Inspect memo entries programmatically:
   - use `SQLiteMemoStore.get(run_id=..., key=..., namespace="run")`

## Policy Rules

- Memoization is required for heavy deterministic write-like outputs.
- If memoization is skipped, orchestrator emits corrective system feedback and retries.
- After max policy retries, run fails closed with `MemoizationPolicyViolation`.
- Planner timeout can trigger deterministic fallback actions.
- After first planner timeout, timeout mode can continue with deterministic actions.
- Duplicate tool calls are rejected and bounded by retry budgets.

## Runtime Contracts

- Plan node:
  - emits exactly one pending action at a time
  - gates premature `finish` when missions remain
- Execute node:
  - normalizes arg aliases before tool invocation
  - records tool history and mission report updates for success/error paths
- Policy node:
  - sets `memo_required` flags and suggested memo keys
- Finalize node:
  - creates final answer, runs deterministic audit, persists final checkpoint

## Tool Inventory (12 tools)

- Core:
  - `repeat_message`, `sort_array`, `string_ops`, `math_stats`, `write_file`,
    `memoize`, `retrieve_memo`
- Analysis/parsing:
  - `task_list_parser`, `text_analysis`, `data_analysis`, `json_parser`, `regex_matcher`

## Structured Mission Parser

- Entry point:
  - `src/agentic_workflows/orchestration/langgraph/mission_parser.py::parse_missions()`
- Produces `StructuredPlan` and `MissionStep` structures with dependencies/tool hints.
- Supports numbered tasks (`Task N:`), list formats (`1.`, `2)`), bullets, and nested sub-tasks
  (`1a.`, `1.1`).
- Falls back to regex extraction if structured parsing fails or times out.
- `Shared_plan.md` is written at run start and finalize with `IMPLEMENTED` / `PENDING` markers.

## Directive Usage

This file is the Phase 1 SOP. Role-specific directives refine behavior:

- `supervisor.md`
- `executor.md`
- `evaluator.md`

Current runtime builds a strict system prompt in code; directives serve as behavioral
specifications and implementation checklists.

## Debugging

- Repeated invalid JSON:
  - verify provider/model supports JSON-object outputs
  - verify system prompt remains first message in state
- Memo policy loops:
  - verify planner can issue `memoize` call with `run_id`
  - inspect `retry_counts["memo_policy"]` in checkpoint state
- Planner timeout/stall:
  - inspect logs for `PLAN PROVIDER TIMEOUT`, `PLAN TIMEOUT FALLBACK`, `PLAN TIMEOUT MODE`
  - lower `P1_PLAN_CALL_TIMEOUT_SECONDS`
- Provider failures:
  - ensure `P1_PROVIDER` and required keys/env vars are set
- Unexpected cache behavior:
  - inspect `policy_flags["cache_reuse_hits"]`/`cache_reuse_misses`
  - validate mission attribution in `mission_report`

## Extension Path (Phase 1 -> Phase 2)

- Introduce role-specific prompt loading directly from directive files.
- Expand specialist routing beyond current executor pass-through.
- Support richer memo keying and cross-run semantic reuse policies.
- Add high-risk tool interrupt/HITL checkpoints where needed.
