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

## Run Steps
1. Install dependencies:
   - `python3 -m venv .venv`
   - `.venv/bin/pip install -r requirements.txt`
2. Run LangGraph orchestrator:
   - `.venv/bin/python -m execution.langgraph.run`
3. Inspect memo entries:
   - Use `SQLiteMemoStore.get(run_id=..., key=..., namespace="run")`

## Policy Rules
- Memoization is required for heavy deterministic `write_file` outputs.
- If the model skips memoization, orchestrator emits corrective system feedback.
- After max policy retries, run fails closed with `MemoizationPolicyViolation`.

## Debugging
- If model returns invalid JSON repeatedly:
  - check provider model supports JSON mode
  - verify system prompt is first message
- If memo policy loops:
  - verify model can call `memoize`
  - lower task scope or increase `max_policy_retries` for diagnostics
- If provider fails:
  - set `OPENAI_API_KEY`; fallback is Groq in `build_provider`

## Extension Path (Phase 1 -> 2)
- Replace SQLite backend with Postgres implementation behind same store interface.
- Add retrieval-first planner behavior (`retrieve_memo` before recomputation).
- Add `StateGraph` checkpointer and HITL interrupts for high-risk tools.
