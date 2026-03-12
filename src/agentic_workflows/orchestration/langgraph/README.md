# LangGraph Orchestration Directory

This directory contains the full Phase 1 orchestration runtime:
planning, deterministic tool execution, policy enforcement, checkpointing,
memoization, mission parsing, and post-run auditing.

## Scope

Runtime graph:
`plan -> execute -> policy -> finalize`

Primary entrypoint:
`agentic_workflows.orchestration.langgraph.run` (CLI demo)

Primary orchestrator class:
`LangGraphOrchestrator` in `graph.py` (re-exported via `langgraph_orchestrator.py`)

## Directory Inventory (Complete)

| File | Purpose | Key Symbols |
|---|---|---|
| `__init__.py` | Public package surface for consumers/tests | `LangGraphOrchestrator`, `MemoizationPolicy`, `SQLiteCheckpointStore`, `SQLiteMemoStore` |
| `graph.py` | Core orchestrator implementation and node logic | `LangGraphOrchestrator`, `MemoizationPolicyViolation` |
| `langgraph_orchestrator.py` | Discoverable compatibility wrapper export | `LangGraphOrchestrator`, `MemoizationPolicyViolation` |
| `state_schema.py` | Typed run-state contract and default repair | `RunState`, `new_run_state`, `ensure_state_defaults` |
| `provider.py` | LLM provider adapters and retry/timeout behavior | `ChatProvider`, `build_provider`, `ProviderTimeoutError` |
| `model_router.py` | Cost-aware strong/fast provider router scaffold | `ModelRouter`, `TaskComplexity` |
| `policy.py` | Memoization policy rules and key generation | `MemoizationPolicy` |
| `tools_registry.py` | Tool registry + memoize/retrieve wrappers | `build_tool_registry`, `MemoizeStoreTool`, `RetrieveMemoTool` |
| `memo_store.py` | SQLite memo persistence and cache lookup APIs | `SQLiteMemoStore`, `PutResult`, `MemoLookupResult` |
| `checkpoint_store.py` | SQLite checkpoint persistence for node transitions | `SQLiteCheckpointStore` |
| `mission_parser.py` | Structured mission parsing + dependency/tool hints | `parse_missions`, `StructuredPlan`, `MissionStep` |
| `mission_auditor.py` | Deterministic post-run audit checks | `audit_run`, `AuditReport`, `AuditFinding` |
| `handoff.py` | Typed contracts for future specialist delegation | `TaskHandoff`, `HandoffResult`, helpers |
| `run.py` | Demo CLI + audit panel + interactive correction loop | `main()` |
| `run_audit.py` | Historical run summarizer and CSV exporter | `summarize_runs`, `main()` |

## End-to-End Runtime Flow

1. `run.py` creates `LangGraphOrchestrator` and submits a multi-task prompt.
2. `LangGraphOrchestrator.run()` initializes `RunState`, parses missions, and
   writes initial checkpoint.
3. LangGraph executes node loop:
   - `plan`: planner emits next JSON action or finish.
   - `execute`: one deterministic tool call is performed and recorded.
   - `policy`: memo policy may require `memoize` before progress.
   - `finalize`: final answer and deterministic audit report are generated.
4. Checkpoints and memo entries are persisted in SQLite.
5. `run_audit.py` can summarize all recorded runs from checkpoint/memo DBs.

## File-by-File Details

### `graph.py`

Role:
- Implements the state machine and all runtime guardrails.

Important methods:
- Graph wiring: `_compile_graph()`
- Planning: `_plan_next_action()`, `_validate_action()`
- Execution: `_execute_action()`, `_normalize_tool_args()`
- Policy: `_enforce_memo_policy()`
- Finalization/audit: `_finalize()`, `_build_derived_snapshot()`
- Mission/reporting: `_build_mission_contracts_from_plan()`,
  `_initialize_mission_reports()`, `_record_mission_tool_event()`
- Timeout/cache helpers: `_generate_with_hard_timeout()`,
  `_maybe_complete_next_write_from_cache()`, `_cache_write_file_inputs()`

Guardrails implemented:
- strict action-schema validation (tool/finish only)
- invalid JSON retry budget
- duplicate tool-call detection
- content validation for mission-specific outputs
- finish rejection while missions remain incomplete
- planner timeout degradation to deterministic fallback actions
- memo-before-continue policy for heavy deterministic outputs

### `langgraph_orchestrator.py`

Role:
- Lightweight import surface so callers can use
  `agentic_workflows.orchestration.langgraph.langgraph_orchestrator`
  without importing `graph.py` directly.

### `state_schema.py`

Role:
- Defines typed state payloads used across all nodes.

Core contracts:
- `RunState`: canonical run dictionary schema.
- `new_run_state(...)`: initial shape for new runs.
- `ensure_state_defaults(...)`: repairs partial snapshots on node entry.

State includes:
- conversation transcript (`messages`)
- tool history and mission reports
- retry counters and policy flags
- mission contracts/structured plan
- handoff queues and token budget tracking

### `provider.py`

Role:
- Unifies provider contracts for planner calls.

Providers:
- `OpenAIChatProvider`
- `GroqChatProvider`
- `OllamaChatProvider`

Selection:
- `build_provider(preferred=None)` uses explicit argument or `P1_PROVIDER`.
- Fallback order without explicit provider: `ollama -> openai -> groq`
  (first configured provider wins).

Reliability behavior:
- timeout/retry handling in `_RetryingProviderBase`
- retryable timeout detection via string markers
- configurable env vars:
  - `P1_PROVIDER_TIMEOUT_SECONDS`
  - `P1_PROVIDER_MAX_RETRIES`
  - `P1_PROVIDER_RETRY_BACKOFF_SECONDS`
  - provider credentials/model env vars

### `model_router.py`

Role:
- Optional complexity-based strong-vs-fast provider routing.

Status:
- Scaffolded utility; current graph execution can run with a single provider.
- `has_dual_providers` indicates whether strong/fast providers are distinct.

### `policy.py`

Role:
- Decides when memoization is mandatory.

Rules (current):
- only `write_file` results are candidates
- mandatory for Fibonacci paths, large content, or high comma density
- keying via `suggested_memo_key()`

### `tools_registry.py`

Role:
- Builds the complete tool map used by execution node.

Includes:
- deterministic core tools
- analysis/parsing tools
- memo wrappers backed by `SQLiteMemoStore`

Contracts:
- `MemoizeStoreTool`: requires `key`, `value`, `run_id`
- `RetrieveMemoTool`: requires `key`, `run_id`

### `memo_store.py`

Role:
- Persists memo entries and cache entries in SQLite.

Primary methods:
- `put(...)`: upsert memo value + deterministic hash metadata
- `get(...)`: run-scoped lookup
- `get_latest(...)`: latest by key across runs (used for cache reuse)
- `list_entries(...)`: list run memo entries
- `delete(...)`: targeted cleanup by key/hash
- `get_cache_value(...)`: helper for shared cache values

Database:
- `.tmp/memo_store.db`
- table: `memo_entries`
- uniqueness: `(run_id, namespace, key)`

### `checkpoint_store.py`

Role:
- Persists per-node state snapshots for each run.

Primary methods:
- `save(...)`
- `load_latest(run_id)`
- `list_checkpoints(run_id)`

Database:
- `.tmp/langgraph_checkpoints.db`
- table: `graph_checkpoints`

### `mission_parser.py`

Role:
- Converts user prompt into structured mission plan.

Parsing capabilities:
- `Task N: ...`
- numbered lists (`1.`, `2)`, `3:`)
- bullets (`-`, `*`, `+`)
- nested sub-tasks (`1a`, `1.1`)
- multiline continuation handling
- fallback regex extraction if parsing fails or times out

Outputs:
- `StructuredPlan` with ordered `MissionStep`s
- `flat_missions` compatibility list for existing execution logic

### `mission_auditor.py`

Role:
- Deterministic post-run quality checks over mission reports and tool history.

Entry point:
- `audit_run(...) -> AuditReport`

Check families include:
- tool presence and mission attribution consistency
- requested count matching
- chain integrity for multi-tool transformations
- Fibonacci output heuristics
- write success and required output presence
- numeric consistency checks for summary files

No model calls occur in this file.

### `handoff.py`

Role:
- Typed schema contracts for future specialist handoffs.

Types:
- `TaskHandoff`
- `HandoffResult`

Helpers:
- `create_handoff(...)`
- `create_handoff_result(...)`

### `run.py`

Role:
- CLI demonstration runner.

Behavior:
- runs a representative multi-task prompt
- prints tool history, mission report, memo entries, derived snapshot
- renders audit panel
- optionally re-runs failed missions interactively
- appends compact audit summary to `lastRun.txt` when `P1_APPEND_LASTRUN` is enabled

Run command:
`python -m agentic_workflows.orchestration.langgraph.run`

### `run_audit.py`

Role:
- Summarizes stored runs from SQLite into terminal table + CSV.

CLI options:
- `--checkpoint-db`
- `--memo-db`
- `--csv-path`
- `--run-id` (prints detailed tool-step status for one run)

Run command:
`python -m agentic_workflows.orchestration.langgraph.run_audit`

## Persistence Artifacts

Generated files:
- `.tmp/langgraph_checkpoints.db`
- `.tmp/memo_store.db`
- `.tmp/run_summary.csv` (from `run_audit.py`)

Optional/ephemeral text outputs from demo missions:
- `analysis_results.txt`
- `users_sorted.txt`
- `pattern_report.txt`
- `fib*.txt`
- `lastRun.txt`
- `Shared_plan.md`

## Current vs Planned Multi-Agent Routing

Current:
- single planner + deterministic executor flow
- specialist routing helper exists but currently passes all actions to executor

Planned/extension path:
- role-specific prompt decomposition
- supervisor/executor/evaluator subgraph routing
- richer handoff queue processing using `handoff.py` contracts

## Practical Extension Points

- Add or adjust tool behavior:
  - update `tools_registry.py` and corresponding tool module under `tools/`
- Change memo policy:
  - update `policy.py` and related tests
- Adjust mission parsing:
  - update `mission_parser.py` heuristics and fallback behavior
- Expand audit checks:
  - add checks in `mission_auditor.py`
- Introduce role-specific routing:
  - expand `_route_to_specialist` and handoff queue handling in `graph.py`
