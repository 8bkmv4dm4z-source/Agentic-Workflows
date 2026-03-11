# Codebase Concerns

**Analysis Date:** 2026-03-12

## Tech Debt

**Pervasive `type: ignore` suppression (315 occurrences):**
- Issue: 315 `# type: ignore` comments throughout core orchestration modules, plus 18 full-module `ignore_errors = true` overrides in `pyproject.toml` for modules including `graph.py`, `provider.py`, `context_manager.py`, `run.py`, `user_run.py`, and `app.py`
- Files: `src/agentic_workflows/orchestration/langgraph/planner_helpers.py`, `planner_node.py`, `executor_node.py`, `context_manager.py`, `provider.py`, and most orchestration modules
- Impact: mypy gives no safety signal on the highest-risk code paths. Type errors in the orchestration core are invisible until runtime.
- Fix approach: Enable mypy on one module at a time, starting with `state_schema.py` (already clean), then `model_router.py`, then progressively re-enable the full-module overrides.

**Hardcoded `mission_type="multi_step"` routing always selects strong model:**
- Issue: In `planner_node.py:256`, the routing signal `mission_type` is hardcoded to `"multi_step"` with comment `# Always route planning to strong model`. This means `ModelRouter.route_by_signals()` signal #3 always fires, short-circuiting budget-aware or intent-aware routing for planner calls.
- Files: `src/agentic_workflows/orchestration/langgraph/planner_node.py:256`
- Impact: The multi-provider routing system is partially bypassed for the most frequent (planner) LLM calls; fast provider never used for planning even when intent is `"simple"`.
- Fix approach: Pass the actual `mission_type` from `structured_plan.intent_classification` instead of a hardcoded constant.

**Deprecated `route_by_intent()` not fully removed:**
- Issue: `ModelRouter.route_by_intent()` marked `DeprecationWarning` since "Plan 03" but still present. No callers found in `src/` at time of analysis (migration appears complete), but the deprecated path remains in the public API.
- Files: `src/agentic_workflows/orchestration/langgraph/model_router.py:104-129`
- Impact: Maintenance surface; future callers could accidentally use the deprecated path.
- Fix approach: Remove after confirming no external callers; one-liner deletion.

**Legacy P0 baseline (`core/`, `agents/`) never removed:**
- Issue: `src/agentic_workflows/core/orchestrator.py` (316 lines), `core/main.py`, and `agents/local_agent.py` are excluded from coverage and mypy (`pyproject.toml` omit list) but still exist in the package. They are not imported anywhere in the active codebase.
- Files: `src/agentic_workflows/core/orchestrator.py`, `src/agentic_workflows/core/main.py`, `src/agentic_workflows/agents/local_agent.py`
- Impact: Dead weight; anyone reading the codebase will be confused about which orchestrator is authoritative.
- Fix approach: Delete or move to `archive/` — they are not tested and not imported.

**Duplicate SQL migration directory:**
- Issue: `db/migrations/005_sub_task_cursors.sql` exists in both `db/migrations/` and `storage/migrations/`. No migration runner or version-tracking table found.
- Files: `db/migrations/`, `storage/migrations/005_sub_task_cursors.sql`
- Impact: Schema drift risk; unclear which directory is authoritative. Migrations must be applied manually.
- Fix approach: Remove the duplicate directory, add a `schema_version` table, and document the apply procedure.

**File handle leak in `user_run.py`:**
- Issue: `open(_TMP_DIR / "server_logs.txt", "a")` at line 154 is stored in module-level `_server_log_fh` but never explicitly closed. Suppressed with `# noqa: SIM115`.
- Files: `src/agentic_workflows/cli/user_run.py:154`
- Impact: File handle leaked for the process lifetime when the auto-server-start path is used.
- Fix approach: Use `contextlib.ExitStack` or register a `signal.atexit` to close the handle.

**`seen_tool_signatures` stored as `set[str]` in RunState:**
- Issue: `RunState` declares `seen_tool_signatures: set[str]` (state_schema.py:86). SQLite checkpoint serialization uses `json.dumps(value, default=str)` — `set` is not JSON-serializable; `default=str` will serialize a set as its string representation `"{'sig1', 'sig2'}"` rather than a list, breaking deserialization. `ensure_state_defaults` converts lists back to sets (line 221-222), but the round-trip through SQLite is lossy.
- Files: `src/agentic_workflows/orchestration/langgraph/state_schema.py:86`, `src/agentic_workflows/storage/sqlite.py:213`
- Impact: After a checkpoint restore the duplicate-tool guard may fail to detect previously seen calls, or the set may deserialize as a single garbled string entry.
- Fix approach: Store as `list[str]` in state; convert to `set` inside the executor for O(1) lookup, convert back to `list` before returning from the node.

## Known Bugs

**Daemon threads not cancellable on provider timeout:**
- Symptoms: When `_generate_with_hard_timeout()` or `parse_missions_with_timeout()` times out, the spawned daemon thread continues running in the background until the underlying HTTP call completes or the process exits. For Ollama/slow providers this can be minutes.
- Files: `src/agentic_workflows/orchestration/langgraph/planner_helpers.py:643`, `src/agentic_workflows/orchestration/langgraph/mission_parser.py:359`, `src/agentic_workflows/orchestration/langgraph/mission_parser.py:505`
- Trigger: Any planner call that exceeds `P1_PLAN_CALL_TIMEOUT_SECONDS`
- Workaround: Set socket-level timeouts on the provider (granular `httpx.Timeout` applied in provider.py for Ollama). Anthropic/OpenAI paths rely solely on the queue timeout, leaving the thread live.

**Ollama Intel Arc iGPU GPU acceleration broken:**
- Symptoms: Ollama uses CPU (no GPU offload) on Intel Arc graphics, causing very slow inference; SYCL/Vulkan backends both fail upstream.
- Files: `src/agentic_workflows/orchestration/langgraph/provider.py` (OllamaChatProvider), `.env` / `OLLAMA_NUM_GPU`
- Trigger: Running with Ollama on a system with Intel Arc GPU without `OLLAMA_NUM_GPU=0`
- Workaround: Set `OLLAMA_NUM_GPU=0` to force CPU, or migrate to IPEX-LLM/SYCL.

**Empty `{}` JSON output from grammar-constrained LlamaCpp:**
- Symptoms: LlamaCpp with GBNF grammar occasionally produces `{}` as model output, which is treated as "empty" after detection in `planner_node.py:289` and triggers the empty-output escalation path.
- Files: `src/agentic_workflows/orchestration/langgraph/planner_node.py:289-294`
- Trigger: Grammar-constrained sampling on certain quantized models; harder to reproduce with `json_schema` mode.
- Workaround: System detects and falls through to retry; non-fatal but wastes a planner step and a LLM call.

## Security Considerations

**`run_bash` uses `shell=True` with user-provided command string:**
- Risk: When `P1_BASH_ENABLED=true`, the LLM-generated `command` argument is passed directly to `subprocess.run(..., shell=True)`. The denylist in `check_bash_command()` relies on substring matching (`if pattern in command`), which can be bypassed with shell quoting, variable expansion, or multi-statement chaining (`;`, `&&`, `$(...)`).
- Files: `src/agentic_workflows/tools/run_bash.py:68-75`, `src/agentic_workflows/tools/_security.py:90-120`
- Current mitigation: Disabled by default (`P1_BASH_ENABLED` env gate); sandbox path check via `P1_TOOL_SANDBOX_ROOT`; python bare-call guard; denylist patterns via `P1_BASH_DENIED_PATTERNS`.
- Recommendations: Replace `shell=True` with `shlex.split()` + list-form `subprocess.run`; add an allowlist-only mode (`P1_BASH_ALLOWED_COMMANDS` already exists but is opt-in); never enable in production without container sandboxing.

**API key middleware disabled by default:**
- Risk: The `APIKeyMiddleware` has an explicit dev-passthrough: if `API_KEY` env var is not set, all requests pass without any authentication. This is a latent production misconfiguration risk.
- Files: `src/agentic_workflows/api/middleware/api_key.py:26-27`
- Current mitigation: Documented in middleware docstring. No test enforces that `API_KEY` is set in staging/production deployments.
- Recommendations: Add a startup check that warns (or optionally errors) when `API_KEY` is unset and `ENVIRONMENT != "development"`.

**No rate limiting on `/run` endpoint:**
- Risk: `POST /run` accepts arbitrary user input and starts a full LLM orchestration run per request. There is no per-client, per-IP, or global rate limit.
- Files: `src/agentic_workflows/api/routes/run.py:42`, `src/agentic_workflows/api/app.py`
- Current mitigation: SSE stream duration cap via `SSE_MAX_DURATION_SECONDS` (default 300s).
- Recommendations: Add a token-bucket rate limiter (e.g., `slowapi`) keyed on `client_ip` before the orchestrator is invoked.

**User input flows unsanitized into LLM message history:**
- Risk: `user_input` from the API body is placed directly into `state["messages"]` as a `user` role message with no sanitization. A malicious user could attempt prompt injection via crafted input.
- Files: `src/agentic_workflows/orchestration/langgraph/lifecycle_nodes.py:517`, `src/agentic_workflows/api/routes/run.py:44`
- Current mitigation: System prompt (from directives) establishes agent role before user messages. Tool calls are validated against a registry.
- Recommendations: Add a maximum `user_input` length cap at the API layer (e.g., 10k characters); log suspicious patterns (injected system tags, role-switching attempts).

**SSE stream reconnect uses HMAC token but active_streams dict is in-memory only:**
- Risk: `active_streams` is a plain `dict` on `app.state`. In multi-worker deployments (e.g., `uvicorn --workers N`), a reconnecting client will get a 404 if it hits a different worker. The stream is gone.
- Files: `src/agentic_workflows/api/routes/run.py:71`, `src/agentic_workflows/api/app.py:143`
- Current mitigation: Single-worker deployments are the assumed target.
- Recommendations: Document the single-worker requirement explicitly; or use Redis pub/sub for cross-worker stream state.

## Performance Bottlenecks

**Token budget uses len//4 character-count heuristic:**
- Problem: All token budget tracking uses `len(text) // 4` (defined in `planner_helpers.py:698-699` and applied in `planner_node.py:364-369` and `context_manager.py:757`). This is a rough approximation — off by 20-40% for code/JSON payloads and 2-3x for CJK text.
- Files: `src/agentic_workflows/orchestration/langgraph/planner_helpers.py:698`, `src/agentic_workflows/orchestration/langgraph/planner_node.py:364`, `src/agentic_workflows/orchestration/langgraph/context_manager.py:757`
- Cause: Avoiding tokenizer dependency for portability across providers.
- Improvement path: Add optional `tiktoken` integration for OpenAI paths; accept the approximation for Ollama/Groq where true token counts are unavailable without an extra API call.

**ContextManager `_cascade_cache` uses simple FIFO eviction:**
- Problem: `_cascade_cache` and `_embed_cache` are capped at 200 entries (`_CACHE_MAX_SIZE`) with "oldest half evicted" when full. For long-lived FastAPI workers with high request diversity this means frequent cache misses and Postgres round-trips (2-second timeout each) on every planner step.
- Files: `src/agentic_workflows/orchestration/langgraph/context_manager.py:42-44`
- Cause: No LRU eviction; FIFO eviction can discard frequently-accessed entries.
- Improvement path: Replace with `functools.lru_cache` or `cachetools.LRUCache`.

**`context_manager.py` is 1054 lines — single-class god object:**
- Problem: `MissionContextManager` handles context injection, sliding-window compaction, cascade retrieval, embedding, partial-mission persistence, and cross-run summaries in one 1054-line file.
- Files: `src/agentic_workflows/orchestration/langgraph/context_manager.py`
- Cause: Incremental phase-by-phase additions without refactoring.
- Improvement path: Extract into `context/injection.py`, `context/compaction.py`, `context/cascade.py`.

**`run.py` is 1112 lines and excluded from coverage and mypy:**
- Problem: The main CLI entrypoint `run.py` contains orchestration helpers, UI rendering, audit reporting, and run lifecycle management in a single file. It is both the largest source file and excluded from both mypy and coverage.
- Files: `src/agentic_workflows/orchestration/langgraph/run.py`
- Cause: Run logic accreted over phases without restructuring.
- Improvement path: Extract UI helpers into `run_ui.py` (already partially done), audit into `run_audit.py` (already exists), lifecycle into lifecycle module.

## Fragile Areas

**`_sequential_node` wrapper silently zeros Annotated list fields:**
- Files: `src/agentic_workflows/orchestration/langgraph/orchestrator.py:176-193`
- Why fragile: Every graph node must be wrapped with `_sequential_node()` to avoid `operator.add` doubling list fields. If a new node is added without this wrapper, lists silently double each step. The derived field set `_ANNOTATED_LIST_FIELDS` auto-updates, but the wrapping requirement is not enforced by any test or type system.
- Safe modification: Always register new graph nodes via `_sequential_node(fn)`. Add a test that runs a single step and asserts list field lengths stay constant.
- Test coverage: Integration tests catch regression indirectly via output correctness, not via explicit field-length assertion.

**`ensure_state_defaults` requires manual sync with RunState fields:**
- Files: `src/agentic_workflows/orchestration/langgraph/state_schema.py:200-290`
- Why fragile: Every new `RunState` field must be manually added to `ensure_state_defaults()` and `new_run_state()`. Missing an entry causes `KeyError` at runtime when the field is first accessed. There is no static check.
- Safe modification: After adding a field to `RunState`, search for `ensure_state_defaults` and `new_run_state` and add a corresponding default.
- Test coverage: Partial — `test_run_helpers.py` covers some defaults but not all fields.

**Mission parser fallback silently swallows parsing exceptions:**
- Files: `src/agentic_workflows/orchestration/langgraph/mission_parser.py:356-388`
- Why fragile: The threaded parser catches all exceptions and logs `PARSER FALLBACK reason=exception` at INFO level (not WARNING). The fallback plan is a single-step catch-all, which will always succeed but may miss multi-mission intent entirely.
- Safe modification: At minimum log the original exception at WARNING level; consider re-raising after a structured fallback for debugging.
- Test coverage: `test_mission_parser.py` tests the fallback path but uses scripted triggers, not real LLM exceptions.

**Broad `except Exception: pass` patterns mask failures silently:**
- Files: `src/agentic_workflows/orchestration/langgraph/provider.py:357,389,400`, `src/agentic_workflows/orchestration/langgraph/planner_node.py:228,497,622,729`, `src/agentic_workflows/orchestration/langgraph/lifecycle_nodes.py:177,197`
- Why fragile: At least 15 bare `except Exception: pass` (or `pass`-equivalent) clauses across core orchestration nodes. Silent swallowing means unexpected errors are invisible in logs, making debugging production failures very difficult.
- Safe modification: Replace `pass` with at minimum `self.logger.debug(..., exc_info=True)` to emit traceback at debug level without changing behavior.
- Test coverage: None — by definition these paths fail silently.

## Scaling Limits

**SQLite checkpoint store:**
- Current capacity: Single-file SQLite, one writer at a time.
- Limit: Concurrent runs from multiple threads/workers will serialize on SQLite write locks; at ~10 concurrent runs performance degrades significantly.
- Scaling path: `DATABASE_URL` env var enables Postgres via `checkpoint_postgres.py`; SQLite is development-only.

**`active_streams` in-memory dict on FastAPI app state:**
- Current capacity: All active SSE streams for a single process.
- Limit: Single process / single worker. Any restart or second worker loses all in-flight streams.
- Scaling path: Redis pub/sub or a persistent event store; documented as single-worker only.

**ContextManager cascade retrieval 2-second timeout per planner step:**
- Current capacity: Blocks planner for up to 2 seconds per step if Postgres is slow.
- Limit: Under high Postgres load or network latency, each multi-mission run adds `n_steps × 2s` worst-case latency.
- Scaling path: Make cascade retrieval fully async (currently runs in `ThreadPoolExecutor`); add read replica support.

## Dependencies at Risk

**`spacy` + `en_core_web_sm` model — optional but affects mission quality:**
- Risk: `spacy` is loaded lazily in `mission_parser.py`. If the model (`en_core_web_sm`) is not installed, clause-splitting falls back to regex. The fallback silently reduces mission-parsing quality for multi-clause inputs.
- Impact: Multi-mission runs may collapse to single-mission plans on environments without spacy.
- Migration plan: Add `spacy` and `en_core_web_sm` to `[project.optional-dependencies]` with a clear install note; add a startup warning when spacy is absent.

**`langfuse` — optional observability with version-split import:**
- Risk: The import in `observability.py:24-26` handles a `langfuse 2.x` vs `langfuse 3.x` API split with a try/except. If neither import path works (e.g., future langfuse 4.x changes), observability silently no-ops with no log warning.
- Impact: Traces and schema compliance scores are silently dropped without any indication.
- Migration plan: Add a logged warning when langfuse is installed but neither import path succeeds.

## Test Coverage Gaps

**`run.py` and `user_run.py` excluded from coverage:**
- What's not tested: The main CLI demo entry point (`run.py`, 1112 lines) and the interactive conversational CLI (`user_run.py`, 377 lines) are both excluded from coverage via `pyproject.toml` omit list with rationale "requires TTY".
- Files: `src/agentic_workflows/orchestration/langgraph/run.py`, `src/agentic_workflows/orchestration/langgraph/user_run.py`
- Risk: Orchestration helpers inside `run.py` (e.g., `_derive_run_result`, `_safe_serialize`, `_build_run_context`) are never unit-tested.
- Priority: High — these helpers are called on every run; a silent bug here affects all users.

**`provider.py` excluded from mypy, sparse unit tests for fallback paths:**
- What's not tested: The Ollama native-chat fallback path, the LlamaCpp grammar-vs-json_schema selection, and the retry backoff logic have no dedicated unit tests. Integration tests use `ScriptedProvider`.
- Files: `src/agentic_workflows/orchestration/langgraph/provider.py`
- Risk: Provider-level retry and fallback logic could break silently for specific model configurations.
- Priority: Medium — ScriptedProvider integration tests cover the happy path but not fallback combinations.

**Security guardrails in `_security.py` have minimal edge-case coverage:**
- What's not tested: Denylist bypass via shell metacharacters (`;`, `$(...)`), symlink attacks on `validate_path_within_sandbox`, and the `check_content_size` with non-UTF-8 content.
- Files: `src/agentic_workflows/tools/_security.py`, `tests/unit/test_run_bash.py`
- Risk: A crafted command could bypass the substring denylist check.
- Priority: High when `P1_BASH_ENABLED=true`; low in default configuration.

**No tests for `active_streams` cleanup on producer error:**
- What's not tested: The `finally: request.app.state.active_streams.pop(run_id, None)` cleanup path in the SSE producer is not covered by any test. If `send_stream.aclose()` raises, the stream dict entry leaks.
- Files: `src/agentic_workflows/api/routes/run.py:173-175`
- Risk: Long-lived FastAPI processes accumulate stale stream references, growing `active_streams` indefinitely.
- Priority: Medium.

---

*Concerns audit: 2026-03-12*
