# CLAUDE.md

Quick-start context for Claude Code sessions in this repo. For full details see `AGENTS.md`, `P1_WALKTHROUGH.md`, and `directives/phase1_langgraph.md`.

## Commands

```bash
# Run Phase 1 demo
.venv/bin/python -m execution.langgraph.run

# Run all tests
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q

# Run specific test files
.venv/bin/python -m unittest tests/test_langgraph_flow.py tests/test_memo_store.py tests/test_memo_policy.py

# Run audit (all historical runs)
.venv/bin/python -m execution.langgraph.run_audit
```

## Context Load Order

1. `deep-research-report.md` — mission, roadmap, risk model
2. `P1_WALKTHROUGH.md` — Phase 1 architecture, known bugs, run guidance
3. `directives/phase1_langgraph.md` — Phase 1 SOP
4. `execution/langgraph/` code + `tests/test_langgraph_flow.py`

## Architecture

**3-layer model:**
- **Directive** (`directives/`) — SOPs defining goals, inputs, outputs, edge cases
- **Orchestration** (`execution/langgraph/`) — decision-making, retries, recovery, stop conditions; probabilistic reasoning lives here
- **Execution** (`execution/`) — deterministic Python code, tool execution, persistence, IO

**Phase 1 graph node flow:** `plan -> execute -> policy -> finalize`

**Key modules** (all under `execution/langgraph/`):
- `graph.py` — LangGraph nodes, planning, execution, arg normalization, Shared_plan.md writer
- `langgraph_orchestrator.py` — entrypoint, timeout handling, cache logic
- `state_schema.py` — typed state with `ensure_state_defaults` (includes `structured_plan`)
- `mission_parser.py` — structured mission parsing with sub-task support and regex fallback
- `provider.py` — multi-provider abstraction (Ollama, OpenAI, Groq)
- `tools_registry.py` — tool map via `build_tool_registry()` (12 tools)
- `memo_store.py` — schema-backed memoization store
- `checkpoint_store.py` — durable snapshots across node transitions
- `policy.py` — memo-required enforcement for heavy writes

**Tools** (under `tools/`):
- Core: `echo`, `sort_array`, `string_ops`, `math_stats`, `write_file`, `memoize` (in registry)
- Analysis/parsing: `task_list_parser`, `text_analysis`, `data_analysis`, `json_parser`, `regex_matcher`

## Conventions

- **Default targeting:** work on the highest implemented phase (currently Phase 1 under `execution/langgraph/`) unless user says otherwise.
- **Phase isolation:** Phase 0 stays in `p0/`, Phase 1 stays in `execution/langgraph/`, `tests/`, and docs.
- **Notebook vs production:** notebooks (`execution/notebooks/`) are for walkthrough and verification; production logic stays in `execution/langgraph/*.py`.
- **Check before creating:** inspect existing tools/code in `execution/` before writing new code.
- **Doc updates:** operational learnings go in `P1_WALKTHROUGH.md`; do not create/overwrite directives without explicit user request.

## Provider / Env Config

Set `P1_PROVIDER` to one of: `ollama`, `groq`, `openai`. Additional env vars per provider:

| Provider | Required env vars | Default model |
|----------|------------------|---------------|
| Ollama | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | `llama3.1:8b` |
| OpenAI | `OPENAI_API_KEY`, `OPENAI_MODEL` | `gpt-4.1-mini` |
| Groq | `GROQ_API_KEY`, `GROQ_MODEL` | `llama-3.1-8b-instant` |

Tuning env vars (with defaults):
- `P1_PROVIDER_TIMEOUT_SECONDS` (30)
- `P1_PROVIDER_MAX_RETRIES` (2)
- `P1_PROVIDER_RETRY_BACKOFF_SECONDS` (1.0)
- `P1_PLAN_CALL_TIMEOUT_SECONDS` (45) — hard wall-time cap per planner call

## Known Constraints

- **JSON contract violations:** some providers emit XML-ish tool-call envelopes instead of JSON. Parser recovers first balanced JSON object; non-JSON payloads cause bounded retry then fail-closed.
- **Memoization policy:** heavy deterministic writes (e.g. `write_file`) require a `memoize` call. This is enforced even during timeout mode — `memoize` before `finish`.
- **Timeout mode:** after a planner timeout, `planner_timeout_mode=True` activates deterministic fallback actions (no further model calls). Supports `repeat_message`, `sort_array`, `string_ops`, Fibonacci `write_file`.
- **Duplicate protection:** exact duplicate tool calls are blocked via `seen_tool_signatures`.
- **Arg normalization:** `graph.py` normalizes common arg aliases (e.g. `array`/`values` -> `items`, `file_path` -> `path`, `op` -> `operation`, `regex` -> `pattern`).
- **Structured plan:** mission parser produces `StructuredPlan` with sub-task support; `Shared_plan.md` is written at run start/finalize with IMPLEMENTED/PENDING markers.

## File Layout

- `p0/` — Phase 0 legacy baseline
- `execution/langgraph/` — Phase 1 runtime
- `execution/notebooks/` — walkthrough notebooks
- `directives/` — SOPs
- `tests/` — automated tests
- `.tmp/` — intermediates and local stores (regenerable)
- `.env` — provider/config secrets (not committed)
