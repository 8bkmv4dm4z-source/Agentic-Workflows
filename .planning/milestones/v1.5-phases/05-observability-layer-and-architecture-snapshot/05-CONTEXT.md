# Phase 5: Observability Layer and Architecture Snapshot - Context

**Gathered:** 2026-03-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire Langfuse `CallbackHandler` into the graph invocation config for automatic node-level tracing. Add `@observe()` to `OllamaProvider.generate()` to close the OBSV-02 gap. Produce a `docs/architecture/` snapshot documenting the Phase 1-4 graph topology progression with Mermaid diagrams. No FastAPI, no Postgres, no CI (Phase 6-7). No execution path logic changes.

</domain>

<decisions>
## Implementation Decisions

### Langfuse Deployment Target
- **Langfuse Cloud free tier** — cloud.langfuse.com; credentials via `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY`
- CI behavior: **silent no-op** when credentials absent — graceful degradation already wired in `observability.py`; no Langfuse secrets needed in CI
- SC #1 verified manually: run with real credentials, check Langfuse UI for node spans

### CallbackHandler Wiring
- **Additive-only constraint**: no changes to execution path logic, node functions, or state management
- Wire `LangfuseCallbackHandler` into `self._compiled.invoke(state, config={...})` in `graph.py`
- **Also pass to subgraph invocations**: both `executor_subgraph.invoke(exec_state, config={...})` and `evaluator_subgraph.invoke(eval_state, config={...})` receive the same handler
- If tests fail after subgraph callback wiring: investigate the root cause — callback wiring is standard LangGraph convention; don't drop the feature without understanding why
- No test for Langfuse span emission (would require live connection); wiring is verified manually

### Subgraph Tracing
- `build_executor_subgraph()` and `build_evaluator_subgraph()` accept an optional `callbacks` parameter and pass it to the subgraph `.invoke()` config
- Specialist files (`specialist_executor.py`, `specialist_evaluator.py`) receive only the callback parameter addition — no other changes

### Provider @observe() Gap
- `OllamaProvider.generate()` gets `@observe(name="provider.generate")` (dev default provider only)
- `GroqProvider`, `OpenAIProvider` skipped for now; `ScriptedProvider` never decorated (test double)
- Add a focused unit test asserting `@observe()` is present on `OllamaProvider.generate()` — guards against accidental removal
- Existing tests cover the graceful-degradation no-op; new test is structural only

### Architecture Snapshot
- **Single markdown file**: `docs/architecture/PHASE_PROGRESSION.md`
- **Format**: Markdown with Mermaid diagrams showing graph topology per phase
- **Primary focus**: graph topology progression — show node/edge structure at each phase transition (Phase 1 baseline → Phase 2 with reducers → Phase 3 with subgraphs → Phase 4 with routing)
- **Secondary**: specialist boundary story — ExecutorState/EvaluatorState isolation, prefixed field convention, `isdisjoint` test pattern
- **Audience**: author — technically dense; no LangGraph introductions needed; shows real decisions and their rationale

### Claude's Discretion
- Exact Mermaid diagram syntax and layout
- Level of detail for RunState field listings in the snapshot (summary vs exhaustive)
- Whether to include ADR cross-references in the snapshot

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `observability.py::observe()` — graceful-degradation decorator; already wired on `LangGraphOrchestrator.run()` and `run.py::main()`; use same import pattern for provider wiring
- `observability.py::get_langfuse_client()` — lazy client init with env-var guard; can use same guard for `CallbackHandler` instantiation
- `graph.py` line 408: `self._compiled.invoke(state, config={"recursion_limit": self.max_steps * 9})` — the exact point where `"callbacks"` key is added

### Established Patterns
- Graceful degradation: check `_is_configured()` before instantiating anything Langfuse; return `None` / skip if not
- `@observe()` import: `from agentic_workflows.observability import observe`
- Prior WALKTHROUGH files (`docs/WALKTHROUGH_PHASE3.md`, `docs/WALKTHROUGH_PHASE4.md`) establish the documentation style for the snapshot

### Integration Points
- `graph.py::LangGraphOrchestrator.run()` → `self._compiled.invoke()` — callback injection point
- `graph.py::_route_to_specialist()` → `self._executor_subgraph.invoke()` and `self._evaluator_subgraph.invoke()` — subgraph callback injection points
- `orchestration/langgraph/provider.py::OllamaProvider.generate()` — @observe() addition point
- `docs/architecture/` — new directory to create

</code_context>

<specifics>
## Specific Ideas

- The previous Phase 5 implementation introduced regressions by touching too many systems — this implementation must be **additive-only**: CallbackHandler wiring through config only, no node logic changes
- SC #2 in the roadmap lists @observe() on run() and provider generate() — run() already has it; Phase 5 closes the provider gap

</specifics>

<deferred>
## Deferred Ideas

- @observe() on GroqProvider and OpenAIProvider — future phase or when those providers become active
- Mocked Langfuse test for span emission verification — deferred; would require live or mocked Langfuse infrastructure
- Parallel Send() fan-out tracing — v2 requirements (PRLL-01)

</deferred>

## Phase 5 Hardening (Code Review Fixes)

Applied after review of `graph.py` and `user_run.py`:

### RunResult TypedDict
- Added `RunResult` TypedDict in `state_schema.py` — typed return contract for `LangGraphOrchestrator.run()`
- Annotated `graph.py::run()` → `RunResult`, `user_run.py::_validate_result()` → `RunResult`, `run_once()` → `RunResult`

### Security Guardrails (`_security.py`)
All env-var gated, off by default. Active when Phase 6 HTTP service sets them.

| Function | Env Var | Tool(s) |
|----------|---------|---------|
| `validate_path_within_sandbox()` | `P1_TOOL_SANDBOX_ROOT` | write_file, read_file, run_bash (cwd) |
| `check_bash_command()` | `P1_BASH_DENIED_PATTERNS`, `P1_BASH_ALLOWED_COMMANDS` | run_bash |
| `check_http_domain()` | `P1_HTTP_ALLOWED_DOMAINS` | http_request |
| `check_content_size()` | Per-caller: `P1_WRITE_FILE_MAX_BYTES`, `P1_READ_FILE_MAX_BYTES` | write_file, read_file |

Additional: `P1_HTTP_MAX_RESPONSE_BYTES` (response cap), `P1_USER_INPUT_MAX_LENGTH` (user_run input cap).

### Quick Fixes (user_run.py)
- Added `log.exception()` before error message in `run_once()` except block
- Removed dead `_print_live_phase` static method
- Extracted `__CLARIFY__:` → `_CLARIFY_PREFIX` module constant

---

*Phase: 05-observability-layer-and-architecture-snapshot*
*Context gathered: 2026-03-04*
