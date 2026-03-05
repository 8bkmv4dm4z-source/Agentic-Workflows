# Codebase Concerns

**Analysis Date:** 2026-03-05

## Tech Debt

**Monolithic LangGraph orchestrator:**
- Issue: `src/agentic_workflows/orchestration/langgraph/graph.py` is a 2,682-line integration module that mixes prompt construction, graph wiring, retry policy, checkpointing, mission tracking, audit, and report/file side effects.
- Why: Phase-by-phase delivery kept new behavior in the central orchestrator to preserve momentum and compatibility.
- Impact: Small edits can regress unrelated runtime paths, and ownership boundaries inside the orchestrator are hard to reason about or test in isolation.
- Fix approach: Split node handlers, persistence/reporting helpers, prompt builders, and recovery logic into smaller modules with narrower contracts and targeted tests.

**Global run artifact written outside the tool pipeline:**
- Issue: `_write_shared_plan()` writes a root-level `Shared_plan.md` directly instead of going through the deterministic tool layer or a run-scoped artifact location.
- Why: It provides a human-readable shared plan artifact with backward compatibility for existing workflows.
- Impact: Concurrent runs overwrite the same file, and the side effect bypasses the memo-before-write discipline used elsewhere.
- Fix approach: Write per-run artifacts under `.tmp/` or `user_runs/`, or route the write through an explicit artifact interface with run-scoped names.

**Configuration side effects at import time:**
- Issue: `src/agentic_workflows/orchestration/langgraph/provider.py` loads the repo `.env` during module import.
- Why: It simplifies local CLI startup and provider bootstrapping.
- Impact: Importing the module has global process effects, which makes embedding the package in larger services and testing multiple config profiles in one process harder.
- Fix approach: Move environment loading to entrypoints like `src/agentic_workflows/api/app.py` and `src/agentic_workflows/cli/user_run.py`, then pass validated settings objects into providers.

## Known Bugs

**`GET /tools` omits real tool descriptions:**
- Symptoms: `/tools` can return empty or generic descriptions even though tools define a `description` attribute.
- Trigger: Calling `GET /tools`.
- Workaround: Inspect `src/agentic_workflows/orchestration/langgraph/tools_registry.py` or the individual tool modules directly.
- Root cause: `src/agentic_workflows/api/routes/tools.py` reads `tool.__doc__` instead of `tool.description`, while `src/agentic_workflows/tools/base.py` defines the real metadata field.
- Blocked by: Not applicable.

**`GET /health` can misreport the active provider:**
- Symptoms: The health response can report `"unknown"` or a stale env value even when the running orchestrator has already selected a concrete provider or fallback chain.
- Trigger: Running the API with auto-detected providers or `P1_PROVIDER_CHAIN`.
- Workaround: Inspect `request.app.state.orchestrator.provider` directly.
- Root cause: `src/agentic_workflows/api/routes/health.py` reports `os.environ.get("P1_PROVIDER")` instead of the instantiated provider object from application state.
- Blocked by: Not applicable.

**Concurrent runs clobber `Shared_plan.md`:**
- Symptoms: `Shared_plan.md` can switch between unrelated runs and stop representing any single run accurately.
- Trigger: Starting overlapping runs in the same working directory.
- Workaround: Use checkpoint data from `src/agentic_workflows/orchestration/langgraph/checkpoint_store.py` instead of the shared file.
- Root cause: `src/agentic_workflows/orchestration/langgraph/graph.py` always writes the same global filename.
- Blocked by: Not applicable.

## Security Considerations

**Service is exposed without application-layer auth or throttling:**
- Risk: Any reachable client can trigger LLM/tool execution, spend provider budget, and access run metadata endpoints.
- Current mitigation: `src/agentic_workflows/api/routes/run.py` only applies a same-IP check for `GET /run/{run_id}/stream`; no auth, rate limiting, or CORS policy was detected in `src/agentic_workflows/api/app.py`.
- Recommendations: Default bind to localhost, add API authentication and request throttling, and make public exposure an explicit opt-in deployment mode.

**Tool guardrails are fail-open unless env vars are set:**
- Risk: `src/agentic_workflows/tools/run_bash.py` executes shell commands with `shell=True`, and `src/agentic_workflows/tools/http_request.py` / `src/agentic_workflows/tools/_security.py` only enforce the stricter sandbox and domain rules when env vars are configured.
- Current mitigation: Optional denylist/allowlist controls, path sandbox checks, private-IP blocking for HTTP, and unit tests in `tests/unit/test_tool_security.py`.
- Recommendations: Enforce strict defaults in API mode, validate required security env vars at startup, and prefer argv-based subprocess execution over raw shell strings where possible.

## Performance Bottlenecks

**Checkpoint persistence writes the full state on every node transition:**
- Problem: Full `RunState` payloads are JSON-serialized and inserted repeatedly into SQLite during execution.
- Measurement: Not measured.
- Cause: `src/agentic_workflows/orchestration/langgraph/checkpoint_store.py` stores complete `state_json` snapshots, and `src/agentic_workflows/api/routes/run.py` reloads the latest full state at completion.
- Improvement path: Store smaller deltas or capped snapshots, compress large fields, and add retention/pruning for old checkpoints.

**SQLite-backed service persistence is a likely concurrency bottleneck:**
- Problem: Run metadata, memo data, and checkpoint data all go through local SQLite files.
- Measurement: Not measured.
- Cause: `src/agentic_workflows/storage/sqlite.py`, `src/agentic_workflows/orchestration/langgraph/memo_store.py`, and `src/agentic_workflows/orchestration/langgraph/checkpoint_store.py` optimize for simplicity over high-write service throughput.
- Improvement path: Move to shared service backends for multi-user workloads and add latency/error instrumentation around persistence operations.

## Fragile Areas

**Annotated reducer workaround in graph execution:**
- Why fragile: Correctness depends on every sequential node being wrapped by `_sequential_node()` and every reducer-backed list field being mirrored in `_ANNOTATED_LIST_FIELDS` inside `src/agentic_workflows/orchestration/langgraph/graph.py`.
- Common failures: Duplicated `tool_history` or `mission_reports`, dropped state updates, and subtle regressions when new reducer-backed fields are added.
- Safe modification: Change reducer annotations and wrapper behavior together, then add or update regression tests before refactoring node return values.
- Test coverage: Partial; `tests/integration/test_langgraph_flow.py` and `tests/unit/test_state_schema.py` cover state behavior, but there is no structural guard that every new reducer-backed field is registered in the workaround.

**SSE reconnect path and stream ownership:**
- Why fragile: `src/agentic_workflows/api/app.py` stores active streams in process memory, and `src/agentic_workflows/api/routes/run.py` ties reconnection to the same in-memory stream object plus client IP.
- Common failures: Reconnect breaks after process restart, reverse proxies/NAT can invalidate the same-session heuristic, and horizontal scaling has no shared stream state.
- Safe modification: Introduce durable event storage or pub/sub, use explicit session tokens, and remove assumptions that a single process owns the stream lifecycle.
- Test coverage: Thin; `tests/integration/test_api_service.py` covers the missing-stream 404 path, but no successful reconnect scenario or proxy-aware session test was detected.

**API metadata endpoints derive state indirectly:**
- Why fragile: `src/agentic_workflows/api/routes/health.py` and `src/agentic_workflows/api/routes/tools.py` infer metadata from environment variables and docstrings instead of the instantiated runtime objects.
- Common failures: Empty tool descriptions, stale provider reporting, and monitoring dashboards that disagree with runtime behavior.
- Safe modification: Read metadata from `request.app.state.orchestrator` and the tool instances directly, then add contract tests for exact values.
- Test coverage: Partial; `tests/integration/test_api_service.py` checks response shape, not semantic accuracy.

## Scaling Limits

**In-memory streaming registry:**
- Current capacity: Single-process only; exact concurrent stream capacity is Not measured.
- Limit: `src/agentic_workflows/api/app.py` keeps `active_streams` in process memory, so reconnect support does not survive restarts or horizontal scaling.
- Symptoms at limit: `GET /run/{run_id}/stream` returns 404 for live runs after failover, or clients lose the stream when the serving process changes.
- Scaling path: Replace the in-memory registry with durable event storage or a shared pub/sub layer that supports reconnect without sticky sessions.

**Local SQLite persistence:**
- Current capacity: Not measured.
- Limit: `src/agentic_workflows/storage/sqlite.py`, `src/agentic_workflows/orchestration/langgraph/memo_store.py`, and `src/agentic_workflows/orchestration/langgraph/checkpoint_store.py` remain file-local and host-local.
- Symptoms at limit: Higher write latency, potential lock contention, and operational friction when moving beyond a single-node deployment.
- Scaling path: Migrate the existing storage interfaces to shared database backends with retention policies and operational monitoring.

## Dependencies at Risk

**Fast-moving orchestration and provider packages:**
- Risk: `pyproject.toml` allows broad version ranges for `langgraph`, `langgraph-prebuilt`, `openai`, and `groq`, while `src/agentic_workflows/orchestration/langgraph/graph.py` and `src/agentic_workflows/orchestration/langgraph/provider.py` contain provider-specific compatibility branches and JSON-mode assumptions.
- Impact: Patch or minor upgrades can change import surfaces or runtime behavior without any local code changes.
- Migration plan: Pin known-good versions, run targeted compatibility CI for dependency upgrades, and keep vendor-specific behavior isolated behind smaller adapters.

## Missing Critical Features

**API authentication and deployment hardening:**
- Problem: No API key, JWT, request-throttling, or origin/CORS policy was detected in the FastAPI service layer.
- Current workaround: Rely on local-only deployments or external network controls.
- Blocks: Safe shared staging, multi-user environments, and public-facing deployment.
- Implementation complexity: Medium.

**Retention and cleanup for run artifacts:**
- Problem: Checkpoints, memo entries, run records, and the shared plan artifact accumulate without a retention or cleanup strategy.
- Current workaround: Manual cleanup of `.tmp/` and root artifacts such as `Shared_plan.md`.
- Blocks: Predictable long-lived service operation and disk usage control.
- Implementation complexity: Low to Medium.

## Test Coverage Gaps

**Successful SSE reconnect and resume behavior:**
- What's not tested: Happy-path `GET /run/{run_id}/stream`, reconnect during an active run, and same-session behavior behind proxies/NAT.
- Risk: Reconnect logic can break while current integration tests still pass.
- Priority: High.
- Difficulty to test: Requires concurrent async consumers and controlled stream lifecycle assertions.

**CLI-to-service live workflow:**
- What's not tested: `src/agentic_workflows/cli/user_run.py` auto-start behavior, persistence of `user_runs/context.json`, and real-provider end-to-end runs.
- Risk: The primary operator workflow can fail only in real environments; `.planning/STATE.md` still lists live-provider validation as pending.
- Priority: High.
- Difficulty to test: Requires subprocess orchestration and either live-provider fixtures or opt-in environment-backed tests.

**Production security posture defaults:**
- What's not tested: Startup enforcement that strict env vars such as `P1_TOOL_SANDBOX_ROOT`, `P1_BASH_DENIED_PATTERNS`, `P1_HTTP_ALLOWED_DOMAINS`, and `P1_TOOL_OUTPUT_SCHEMA_STRICT` are present for service deployments.
- Risk: Tests prove the guards work when enabled, but they do not prove production starts in a hardened configuration.
- Priority: High.
- Difficulty to test: Requires a deployment-mode config contract and startup validation tests.

---

*Concerns audit: 2026-03-05*
*Update as issues are fixed or new ones discovered*
