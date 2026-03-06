# Agentic Workflows Package

This package implements a deterministic tool layer plus a LangGraph orchestration runtime.
It is split into clear layers so planning, policy, and execution stay testable and auditable.

## Directory Layout

- `core/`:
  - Phase 0 baseline orchestrator (`Orchestrator`) and simple loop runtime.
  - Useful for comparison and regression checks.
- `orchestration/langgraph/`:
  - Phase 1 orchestrator (`LangGraphOrchestrator`) and graph nodes.
  - Checkpointing, memo store integration, mission parser, provider routing, and audit.
  - Full module documentation: `orchestration/langgraph/README.md`
- `tools/`:
  - Deterministic tools only; no model calls.
  - Implementations are pure input/output logic with file I/O where required.
- `directives/`:
  - SOP/role contracts for supervisor, executor, evaluator, and Phase 1 scope.
  - See `directives/README.md` for how to use them in practice.

## Runtime Flow

The active production path is `LangGraphOrchestrator` in
`orchestration/langgraph/graph.py`.

Graph node sequence:
`plan -> execute -> policy -> finalize`

Node responsibilities:

- `plan` (`_plan_next_action`):
  - Calls planner model.
  - Validates strict JSON action.
  - Enforces retries, timeout fallback, and finish gating.
- `execute` (`_execute_action`):
  - Normalizes tool args.
  - Executes exactly one tool call.
  - Records mission/tool history and duplicate safeguards.
- `policy` (`_enforce_memo_policy`):
  - Detects heavy deterministic outputs.
  - Requires `memoize` before allowing further progress.
- `finalize` (`_finalize`):
  - Produces final answer.
  - Runs deterministic audit (`audit_run`).
  - Persists checkpoint and writes `Shared_plan.md`.

## Quick Start

```bash
pip install -e ".[dev]"
pytest tests/ -q
python -m agentic_workflows.orchestration.langgraph.run
python -m agentic_workflows.orchestration.langgraph.run_audit
```

## Environment Configuration

Provider selection:

- `P1_PROVIDER=openai|groq|ollama`
- `OPENAI_API_KEY` and optional `OPENAI_MODEL`
- `GROQ_API_KEY` and optional `GROQ_MODEL`
- `OLLAMA_BASE_URL` / `OLLAMA_HOST` and optional `OLLAMA_MODEL`

Runtime controls:

- `P1_PLAN_CALL_TIMEOUT_SECONDS`: hard planner wall-clock timeout.
- `P1_PROVIDER_TIMEOUT_SECONDS`: provider request timeout.
- `P1_PROVIDER_MAX_RETRIES`: retry count for timeout-like provider errors.
- `P1_PROVIDER_RETRY_BACKOFF_SECONDS`: linear retry backoff.
- `P1_APPEND_LASTRUN`: append audit summary to `lastRun.txt` when enabled.

## Directive Usage

Directive files are the authoritative behavioral contracts for role-based orchestration:

- `directives/supervisor.md`
- `directives/executor.md`
- `directives/evaluator.md`
- `directives/phase1_langgraph.md`

Current state:

- The single-planner runtime builds its system prompt in code (`_build_system_prompt`).
- Directive files are maintained as role/SOP docs and are the source of truth for future
  specialist routing and prompt decomposition.

If you add new behavior in orchestration code, update matching directive contracts in the same
change.
