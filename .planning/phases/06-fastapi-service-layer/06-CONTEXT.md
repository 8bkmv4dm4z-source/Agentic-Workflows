# Phase 6: FastAPI Service Layer — Context

**Gathered:** 2026-03-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Wrap `LangGraphOrchestrator.run()` in a FastAPI service exposing `POST /run` as the primary endpoint. Add `GET /health` and `GET /tools` informational endpoints. Introduce an eval harness under `tests/eval/` with at least 3 scenario-based evaluations that exercise the HTTP contract end-to-end. Harden `run_bash` and `http_request` tools with configurable scope restrictions (command allowlists/denylists, URL domain allowlists) enforced at the tool level before execution. Update directives to document tool security scopes. No Dockerfile or docker-compose (Phase 7). No Postgres migration (Phase 7). No new agent capabilities or graph topology changes.

</domain>

<decisions>
## Implementation Decisions

### FastAPI Application Structure
- **Single module:** `src/agentic_workflows/api/app.py` — creates the FastAPI app, defines routes, instantiates orchestrator
- **Entrypoint:** `python -m agentic_workflows.api.app` (uvicorn programmatic start) or `uvicorn agentic_workflows.api.app:app`
- **`__init__.py`:** `src/agentic_workflows/api/__init__.py` — re-exports `app` for import convenience
- **Pydantic request/response models:** Defined in `src/agentic_workflows/api/models.py` — `RunRequest`, `RunResponse`, `HealthResponse`, `ToolInfo`
- **No async orchestrator:** `LangGraphOrchestrator.run()` is synchronous; wrap in `asyncio.to_thread()` or use `def` endpoint (FastAPI handles sync endpoints in threadpool automatically)

### Endpoints
- **`POST /run`** — accepts `RunRequest(user_input: str, run_id: str | None = None)`, returns `RunResponse` with `answer`, `tools_used`, `mission_report`, `run_id`, `audit_report`
- **`GET /health`** — returns `{"status": "ok", "provider": <P1_PROVIDER>, "tool_count": <int>}`
- **`GET /tools`** — returns list of `ToolInfo(name, description)` for all registered tools
- **Error handling:** Return structured JSON errors; catch orchestrator exceptions and map to 500 with `{"error": str(exc), "run_id": ...}`

### Request/Response Schemas
- `RunRequest`: `user_input: str` (required), `run_id: str | None = None`, `prior_context: list[dict] | None = None`
- `RunResponse`: `answer: str`, `tools_used: list[str]`, `mission_report: list[dict]`, `run_id: str`, `audit_report: dict | None`
- All models use Pydantic v2 with `model_config = ConfigDict(...)` (consistent with project conventions)

### Tool-Scope Security Restrictions

#### `run_bash` Hardening
- Add `TOOL_BASH_ALLOWED_COMMANDS` env var — comma-separated allowlist of permitted command prefixes (e.g., `ls,cat,head,wc,grep,find,python`)
- Add `TOOL_BASH_DENIED_PATTERNS` env var — comma-separated denylist of blocked patterns (e.g., `rm -rf,sudo,curl,wget,chmod,chown,kill,mkfs,dd`)
- When allowlist is set, commands not matching any allowed prefix are rejected before execution
- When denylist is set, commands matching any denied pattern are rejected before execution
- Default behavior (no env vars set): unrestricted, preserving backward compatibility
- Validation runs before `subprocess.run()` — no shell execution of blocked commands

#### `http_request` Hardening
- Add `TOOL_HTTP_ALLOWED_DOMAINS` env var — comma-separated allowlist of permitted domains (e.g., `api.github.com,httpbin.org`)
- When allowlist is set, requests to domains not in the list are rejected before the HTTP call
- Existing SSRF protection (private IP blocking) remains unchanged
- Default behavior (no env var set): any public domain permitted, preserving backward compatibility

### Eval Harness
- **Location:** `tests/eval/` directory with `conftest.py` for eval-specific fixtures
- **Framework:** pytest-based; each eval scenario is a test function
- **Strategy:** Eval scenarios call the orchestrator's `run()` directly (not via HTTP) to test mission completion quality. HTTP contract tests go in `tests/integration/`
- **Minimum 3 scenarios:**
  1. Single-mission deterministic task (e.g., sort an array + write result) — asserts correct tool sequence and output
  2. Multi-mission task with data chaining — asserts intermediate results carry forward
  3. Error/edge case — malformed mission text or tool failure — asserts graceful degradation and audit report accuracy
- **Eval metrics:** Each scenario asserts `audit_report` pass rate, correct `tools_used`, and answer quality (substring/structure checks)
- **ScriptedProvider:** Evals use `ScriptedProvider` (same as integration tests) — no live API calls

### Directive Updates
- Update `src/agentic_workflows/directives/phase1_langgraph.md` (or create `phase6_api.md`) with:
  - Tool security scope documentation: which tools have restrictions, how scopes are configured
  - HTTP endpoint contract: request/response shapes
  - Eval expectations: what constitutes a passing eval scenario

### Claude's Discretion
- Exact Pydantic field names and JSON serialization details in response models
- Whether to use `def` (sync) or `async def` (with `to_thread`) for the `/run` endpoint
- Uvicorn configuration defaults (host, port, reload flag)
- Additional eval scenarios beyond the minimum 3
- Whether `tests/eval/` uses a separate pytest marker or just directory-based collection
- `.env.example` additions for tool scope vars (format and comments)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `LangGraphOrchestrator` in `graph.py` — fully functional `run(user_input, run_id, ...)` returning a dict with `answer`, `tools_used`, `mission_report`, `run_id`, `memo_events`, `audit_report`, `state`
- `build_tool_registry(store)` in `tools_registry.py` — returns all 24 tools; the `/tools` endpoint can enumerate this
- `ScriptedProvider` in `tests/conftest.py` — deterministic provider for eval scenarios without live API
- `RunBashTool` in `tools/run_bash.py` — `shell=True` subprocess; needs allowlist/denylist before `subprocess.run()`
- `HttpRequestTool` in `tools/http_request.py` — already has SSRF protection via `_PRIVATE_PREFIXES`; domain allowlist adds another layer
- `schemas.py` — `ToolAction`, `FinishAction` Pydantic models; response models should follow same conventions
- `.env.example` — already has provider vars; tool scope vars follow same pattern

### Established Patterns
- **Pydantic v2 everywhere** — `ConfigDict`, not `class Config`
- **Env-based configuration** — `os.environ.get()` with defaults; no hardcoded values
- **Graceful degradation** — tools return `{"error": ...}` dicts on failure, never raise
- **Tool base class** — all tools extend `Tool` with `name`, `description`, `execute(args)`
- **Integration tests with ScriptedProvider** — no live API calls in CI

### Integration Points
- `graph.py:384` — `LangGraphOrchestrator.run()` is the function the API wraps
- `tools_registry.py:108` — `build_tool_registry()` provides tool enumeration for `/tools`
- `run.py` — existing CLI entrypoint; API is the HTTP equivalent
- `.env.example` — add `TOOL_BASH_ALLOWED_COMMANDS`, `TOOL_BASH_DENIED_PATTERNS`, `TOOL_HTTP_ALLOWED_DOMAINS`

</code_context>

<specifics>
## Specific Ideas

- **FastAPI is already in ProjectCompass recommended stack** — `fastapi[standard]>=0.128` listed in the compatible libraries section. The `docs/phases/Phase4.md` document explicitly calls out "Build a minimal FastAPI wrapper around orchestrator run + health endpoint" as proceedings step 2.
- **Tool scope restrictions are OWASP-mandated** — ProjectCompass Section 6 (Security Essentials) lists "least-privilege tool scoping" and "sandboxed code execution" as mandatory controls. `run_bash` with unrestricted `shell=True` is the highest-risk tool in the registry. `http_request` already has SSRF protection but lacks domain-level restrictions.
- **Eval harness before release** — Phase4.md proceedings step 5: "Add baseline eval suite and make it a CI gate before release automation." The eval harness is prerequisite infrastructure for CI quality gates.
- **Keep API surface minimal** — three endpoints (`/run`, `/health`, `/tools`) is intentionally narrow. Streaming, WebSocket, or multi-turn conversation endpoints are deferred.
- **`run_bash` is the highest-risk tool** — unrestricted `shell=True` with arbitrary commands. The allowlist/denylist pattern is the minimum viable security boundary. Full sandboxing (seccomp, containers) is deferred to Phase 7 when Docker is introduced.

</specifics>

<deferred>
## Deferred Ideas

- **Containerization** (`Dockerfile`, `docker-compose.yml`) — Phase 7; API contract must stabilize first
- **Postgres migration** — Phase 7; SQLite is sufficient for dev/eval
- **Streaming responses** (SSE/WebSocket for real-time tool execution updates) — v2 feature
- **Authentication/authorization** on API endpoints — Phase 7 or beyond; dev-only service for now
- **Rate limiting and request validation middleware** — Phase 7 with production hardening
- **Full sandbox for `run_bash`** (seccomp profiles, container isolation) — Phase 7 when Docker is available
- **Multi-turn conversation API** (session management, conversation history) — v2 feature
- **OpenAPI schema publishing** and client SDK generation — post-Phase 6 polish
- **Async orchestrator rewrite** — significant refactor; current sync `run()` works fine behind FastAPI's threadpool

</deferred>

<risks>
## Risk Considerations

### Subgraph Tech Debt (inherited from Phase 4)
The executor subgraph invocation currently uses the parallel-invoke pattern where `_executor_subgraph.invoke()` result is discarded and `_execute_action()` does the real work. This does not affect the API layer directly, but means the orchestrator internals are not yet clean enough for independent subgraph scaling. The API should treat `run()` as a black box.

### graph.py Size (~1700 lines)
`graph.py` is large and handles orchestration, state management, tool dispatch, and specialist routing in one file. The API layer should NOT import internals from `graph.py` beyond `LangGraphOrchestrator`. If the API needs graph-internal state, expose it through `run()` return values, not by reaching into private methods.

### Synchronous Orchestrator Under Load
`LangGraphOrchestrator.run()` is synchronous and can take 30-60+ seconds per run (depending on mission complexity and provider timeouts). Under concurrent HTTP requests, this blocks threadpool workers. Mitigations: document single-user dev-mode expectation, set reasonable uvicorn worker count, add request timeout middleware. True async support is a future refactor.

### Tool Scope Bypass via Prompt Injection
The allowlist/denylist for `run_bash` operates on the command string. Sophisticated prompt injection could attempt to bypass string-level checks (e.g., encoding tricks, variable expansion). The string-match approach is a minimum viable boundary, not a security guarantee. Full sandboxing (Phase 7) is the proper mitigation.

### Eval Scenario Brittleness
ScriptedProvider-based evals test the orchestrator's deterministic behavior given fixed LLM responses. They do NOT test actual LLM quality. This is intentional (reproducible CI), but means eval pass/fail does not guarantee real-world quality. Live-provider eval scenarios (manual, not CI) should be added in a future phase.

</risks>

---

*Phase: 06-fastapi-service-layer*
*Context gathered: 2026-03-03*
