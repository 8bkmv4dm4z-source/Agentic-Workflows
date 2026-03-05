# Codebase Concerns

**Analysis Date:** 2026-03-05

## Tech Debt

**LangGraph orchestrator monolith:**
- Files: `src/agentic_workflows/orchestration/langgraph/graph.py`
- Issue: `LangGraphOrchestrator` is a 2682-line module that still mixes prompt construction, planner retries, mission attribution, specialist routing, memo policy, checkpointing, and API-facing artifact writes.
- Why: Phase work was added in place to keep graph behavior co-located while features were landing quickly.
- Impact: Small changes have a wide regression surface, reasoning about failures is slow, and framework upgrades become riskier because business logic and LangGraph glue are tightly coupled.
- Fix approach: Split the module into smaller units by responsibility and keep `graph.py` as thin graph-node wiring plus orchestration composition.

**Shared plan artifact still writes globally in service mode:**
- Files: `src/agentic_workflows/orchestration/langgraph/graph.py`, `Shared_plan.md`
- Issue: `_write_shared_plan()` writes a single repo-root `Shared_plan.md` on run start and finalize, outside the tool/policy pipeline and without per-run isolation.
- Why: The artifact started as a useful local debug/demo output and was kept during the API transition.
- Impact: Concurrent API runs overwrite each other, user task structure leaks across runs, and service requests still mutate a shared local file as a side effect.
- Fix approach: Disable shared-plan writes for API runs by default, or write run-scoped artifacts under a configured artifact directory keyed by `run_id`.

## Known Bugs

**CLI client fails against authenticated API deployments:**
- Files: `src/agentic_workflows/cli/user_run.py`, `src/agentic_workflows/api/middleware/api_key.py`
- Symptoms: `python -m agentic_workflows.cli.user_run` can pass the `/health` check but `POST /run` fails with `401 Unauthorized` when `API_KEY` is configured.
- Trigger: Set `API_KEY`, start the FastAPI app, and use the bundled CLI client.
- Workaround: Unset `API_KEY` for local use, or use another client that sends `X-API-Key`.
- Root cause: The CLI never sends `X-API-Key`, and only `/health` is exempt from auth.
- Blocked by: Not applicable.

**SSE reconnect path is not durable and appears single-consumer only:**
- Files: `src/agentic_workflows/api/routes/run.py`, `src/agentic_workflows/api/app.py`
- Symptoms: Reconnects can miss events, fail after process restart, and are not safe for multi-worker deployments.
- Trigger: Disconnect during a long `POST /run`, then reconnect via `GET /run/{run_id}/stream`, or run behind more than one API worker.
- Workaround: Keep the original SSE connection alive, or fall back to `GET /run/{run_id}` for completed results.
- Root cause: The API stores one in-memory AnyIO `receive_stream` per run in `app.state.active_streams` instead of a durable event log or replay buffer.
- Blocked by: Durable per-run event storage or broker-backed fan-out is not implemented.

## Security Considerations

**API and tool guardrails fail open when env vars are missing:**
- Files: `src/agentic_workflows/api/middleware/api_key.py`, `src/agentic_workflows/tools/_security.py`, `src/agentic_workflows/tools/read_file.py`, `src/agentic_workflows/tools/write_file.py`, `src/agentic_workflows/tools/http_request.py`
- Risk: If `API_KEY`, `P1_TOOL_SANDBOX_ROOT`, `P1_BASH_DENIED_PATTERNS`, or `P1_HTTP_ALLOWED_DOMAINS` are unset, the service becomes public and tool access is far broader than a production deployment should allow.
- Current mitigation: Guardrails exist, and `HttpRequestTool` blocks private IPv4 ranges in `src/agentic_workflows/tools/http_request.py`.
- Recommendations: Fail closed outside explicit dev mode, validate required hardening env vars at startup, and document separate dev vs. production defaults.

**`run_bash` remains a host-command execution hazard:**
- Files: `src/agentic_workflows/tools/run_bash.py`, `src/agentic_workflows/tools/_security.py`
- Risk: `RunBashTool` executes `subprocess.run(..., shell=True)` and relies on optional substring filters rather than a strict allowlist.
- Current mitigation: Optional denylist/allowlist checks and optional sandbox validation on the `cwd` argument.
- Recommendations: Disable `run_bash` in API deployments unless strictly required, prefer argv-based subprocess execution, and move from denylist matching to explicit command allowlists.

## Performance Bottlenecks

**Checkpoint persistence on every graph transition:**
- Files: `src/agentic_workflows/orchestration/langgraph/graph.py`, `src/agentic_workflows/orchestration/langgraph/checkpoint_store.py`
- Problem: The graph saves full-state checkpoints repeatedly across planner, execute, policy, retry, and finalize paths.
- Measurement: Not benchmarked in repo; current code serializes the full `RunState` JSON and inserts it into SQLite on each checkpoint save.
- Cause: `SQLiteCheckpointStore.save()` opens a fresh SQLite connection and stores whole-state snapshots rather than deltas.
- Improvement path: Reuse connections, enable WAL/busy timeout, reduce checkpoint frequency for API runs, or move to incremental/durable backend storage.

**Queued planner actions can create bursty provider traffic:**
- Files: `src/agentic_workflows/orchestration/langgraph/graph.py`
- Problem: Multi-action planner outputs are drained from `pending_action_queue` with no backpressure or pacing.
- Measurement: Not benchmarked in code; queue depth is unbounded by policy beyond what the model emits, and each drained action returns immediately to more planning/execution work.
- Cause: The plan loop treats queued actions as a fast path and re-enters provider/tool flow without service-level rate control.
- Improvement path: Cap queue depth, add per-run/provider backpressure, and short-circuit deterministic local steps when enough future actions are already known.

## Fragile Areas

**Annotated-list reducer workaround in sequential graph nodes:**
- Files: `src/agentic_workflows/orchestration/langgraph/graph.py`, `src/agentic_workflows/orchestration/langgraph/state_schema.py`
- Why fragile: `_sequential_node()` depends on `_ANNOTATED_LIST_FIELDS` staying perfectly aligned with reducer-backed list fields in `RunState`.
- Common failures: Newly added reducer fields can duplicate `tool_history`, `memo_events`, `seen_tool_signatures`, or `mission_reports` if they are not zeroed in the returned delta.
- Safe modification: Treat `RunState` and `_ANNOTATED_LIST_FIELDS` as a coupled change; update both together and add regression coverage for any new reducer-backed fields.
- Test coverage: `tests/unit/test_state_schema.py`, `tests/unit/test_state_isolation.py`, and `tests/integration/test_langgraph_flow.py` cover reducer behavior indirectly, but no test asserts `_ANNOTATED_LIST_FIELDS` stays synchronized with the schema.

**Run streaming and reconnect lifecycle:**
- Files: `src/agentic_workflows/api/routes/run.py`, `src/agentic_workflows/api/app.py`
- Why fragile: One route owns run creation, background execution, SSE emission, token issuance, reconnect lookup, and cleanup of `active_streams`.
- Common failures: Dropped reconnects, inconsistent behavior across worker restarts, and hard-to-debug races around in-memory stream state.
- Safe modification: Separate run execution, event buffering, and reconnect authorization into distinct components with stable contracts.
- Test coverage: `tests/integration/test_api_service.py` covers happy-path `POST /run` and `GET /run/{id}`, but not valid reconnects, expired tokens, restart scenarios, or multi-worker behavior.

## Scaling Limits

**In-process API state prevents horizontal scaling:**
- Files: `src/agentic_workflows/api/app.py`, `src/agentic_workflows/api/routes/run.py`, `src/agentic_workflows/orchestration/langgraph/graph.py`
- Current capacity: Not benchmarked; current design is effectively single-node because live stream state and shared plan output are held locally in process.
- Limit: `app.state.active_streams` and repo-root `Shared_plan.md` do not survive restarts and cannot be coordinated across workers.
- Symptoms at limit: Lost reconnects, inconsistent run visibility, overwritten shared artifacts, and behavior differences between workers.
- Scaling path: Move stream/event state and run artifacts to shared infrastructure such as Redis, Postgres, or object storage, and keep API nodes stateless.

**SQLite persistence is a local-mode ceiling, especially for checkpoints:**
- Files: `src/agentic_workflows/storage/sqlite.py`, `src/agentic_workflows/orchestration/langgraph/checkpoint_store.py`, `src/agentic_workflows/orchestration/langgraph/memo_store.py`
- Current capacity: Not benchmarked; suitable for local development and light single-instance traffic.
- Limit: Concurrent checkpoint-heavy workloads will hit SQLite locking and filesystem contention before service-scale throughput.
- Symptoms at limit: Slower requests, intermittent `database is locked` errors, and degraded streaming responsiveness under concurrent runs.
- Scaling path: Promote run, checkpoint, and memo persistence to a server database with connection management and keep SQLite as the local/dev backend only.

## Dependencies at Risk

**`langgraph` / `langgraph-prebuilt`:**
- Files: `pyproject.toml`, `src/agentic_workflows/orchestration/langgraph/graph.py`
- Risk: The project depends on framework-specific behavior around `ToolNode`, reducer semantics, and graph state updates while allowing broad `1.0.x` upgrade ranges.
- Impact: Patch upgrades can change error handling or state-merge behavior and break orchestration in subtle, hard-to-debug ways.
- Migration plan: Pin known-good versions exactly, expand upgrade tests around ToolNode error handling and reducer-backed state, and isolate LangGraph-specific behavior behind smaller adapters.

**Langfuse instrumentation coverage is provider-specific today:**
- Files: `src/agentic_workflows/observability.py`, `src/agentic_workflows/orchestration/langgraph/provider.py`
- Risk: Only `OllamaChatProvider.generate()` is decorated with `@observe`; `OpenAIChatProvider` and `GroqChatProvider` do not emit the same provider-level spans.
- Impact: Traces differ by provider, which weakens debugging and makes production observability inconsistent.
- Migration plan: Apply the same tracing wrapper to all supported providers and add structural tests so observability parity does not regress.

## Missing Critical Features

**Durable SSE replay / reconnect support:**
- Files: `src/agentic_workflows/api/routes/run.py`, `src/agentic_workflows/api/stream_token.py`
- Problem: Stream reconnect depends on ephemeral in-memory state instead of persisted events.
- Current workaround: Keep the original connection open or poll `GET /run/{id}` after the run finishes.
- Blocks: Restart-safe streaming, multi-worker API deployment, and reliable reconnects for long runs.
- Implementation complexity: Medium to High.

**Rate limiting for the public run API:**
- Files: `src/agentic_workflows/api/app.py`, `src/agentic_workflows/api/routes/run.py`
- Problem: No request-rate or concurrency throttling is enforced by the application.
- Current workaround: Rely on external proxy controls or keep the service private.
- Blocks: Safely exposing `/run` beyond trusted single-tenant usage.
- Implementation complexity: Medium.

## Test Coverage Gaps

**API auth, request metadata, reconnect, and pagination paths:**
- Files: `src/agentic_workflows/api/middleware/api_key.py`, `src/agentic_workflows/api/middleware/request_id.py`, `src/agentic_workflows/api/routes/runs.py`, `src/agentic_workflows/api/routes/run.py`
- What's not tested: No tests under `tests/` currently target API key enforcement, request ID propagation, `GET /runs` pagination, or successful/expired-token SSE reconnect flows.
- Risk: Security and operability regressions can ship even while the existing API happy-path tests remain green.
- Priority: High.
- Difficulty to test: Moderate; requires env-controlled app setup plus streaming assertions.

**First-party CLI and live-provider end-to-end behavior:**
- Files: `src/agentic_workflows/cli/user_run.py`, `.planning/STATE.md`
- What's not tested: The bundled API client has no automated tests, and the current state file still lists live-provider validation of `run.py` / `user_run.py` as pending.
- Risk: Auto-start, auth, context resume, SSE parsing, and real provider integration can break without being caught by `ScriptedProvider` tests.
- Priority: High.
- Difficulty to test: Medium to High; needs subprocess control and optional live-provider smoke coverage.

---

*Concerns audit: 2026-03-05*
*Update as issues are fixed or new ones discovered*
