# Phase 7.8 Stabilization: Parser Timeout + Planner Model Routing + Context Overflow + Run Log

**Gathered:** 2026-03-10
**Status:** Ready for planning

<domain>
## Feature Boundary

Stabilize Phase 7.8's multi-model routing by fixing three runtime issues observed in live Qwen14B/Phi4 runs, plus improving run log visibility. Parser timeout is too aggressive (5s, always falls back to regex). Planner uses same model as executor (Qwen14B) instead of a reasoning model (Phi4). Context overflows mid-mission (16528 tokens vs 8192 ctx). Run log lacks structured prompt/response/routing detail.

Evidence: `.tmp/api.log` from 2026-03-10 run with Qwen3-14B-Q4_0 shows:
- `PARSER REGEX FALLBACK` on every request (5s timeout, LLM parser never fires)
- `INTENT CLASSIFIER timeout after 0.50s` every time
- `exceed_context_size_error` (16528 > 8192) after ~4 tool steps
- Same model (`Qwen3-14B-Q4_0.gguf`) used for all plan steps — no strong/fast split

</domain>

<decisions>
## Implementation Decisions

### Parser Timeout Tuning
- Adaptive timeout by provider type: local models (LlamaCpp/Ollama) get longer timeout, cloud (Groq/OpenAI) stays at 5s
- Claude's discretion on exact local timeout values (Phi4 and Qwen14B are the target models)
- `P1_PARSER_TIMEOUT_SECONDS` env var overrides auto-detected timeout if set
- Intent classifier timeout: Claude's discretion whether to extend or keep fast
- On LLM parser timeout: fall back to regex (current behavior) + log WARNING with timing info
- Track `parser_timeout_count` in structural_health alongside existing parse metrics

### Planner Model Selection
- Reuse LLAMA_CPP_STRONG_ALIAS system from 7.8: set strong=phi4, fast=qwen14b
- Same llama-server with `--alias` (decided in 7.8, carry forward)
- All model assignments configurable via env vars for flexibility
- Planning uses the strong model (Phi4) — Claude's discretion on whether to always route planning to strong or keep signal-based routing
- Qwen14B `<think>` mode is too long/expensive for planning — Phi4 is the better planner

### Context Overflow Prevention
- Trigger ContextManager compaction proactively before each planner call when prompt approaches ctx limit
- ContextManager already has compact/eviction logic — trigger mid-mission, not just at mission boundaries
- If compaction is done correctly (batch tool results, summarize, write intermediates), context should never overflow — the 400 error should become impossible
- Prepare a fallback path if context still exceeds max after compaction (deterministic fallback, not crash)
- Ctx limit: auto-detect from provider + env var override

### Run Log Improvements
- Append structured debug info to `.tmp/api.log` (same file as current API logs)
- Per planner step: user's original input, model's full JSON response, which model was used, which provider, routing decision, parse result
- Make it as informative and structured as possible for debugging
- Full system prompt: Claude's discretion on logging strategy (first-step-only vs hash+length)

### Claude's Discretion
- Exact local parser timeout values for Phi4/Qwen14B
- Whether intent classifier needs longer timeout or stays fast
- Parser model: same as planner or always use fast model for parsing
- Whether planning always uses strong model or keeps signal-based routing
- Log format structure and verbosity level
- System prompt logging strategy

</decisions>

<specifics>
## Specific Ideas

- "Overall better response especially with qwen14 no_think but still lacks better usage of parser which defaults right away due to 5 seconds"
- "Planner should be led by a better and reasoning model (which is not qwen because qwen <think> is way too long)"
- "If done correctly the batching should prevent this from ever happening — just adds more steps and requires deterministic phase planning and query or mid phase writing then reverting to read batching"
- User runs Phi4 and Qwen3-14B-Q4_0 on llama-server locally
- The `.tmp/api.log` from 2026-03-10 run is the reference evidence for all issues

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ContextManager` in context_manager.py: has `compact()`, `on_mission_complete()`, eviction logic — needs mid-mission trigger
- `ModelRouter` in model_router.py: `route_by_signals()` with `RoutingSignals` TypedDict — already routes strong/fast
- `LlamaCppChatProvider.with_alias()`: creates provider instance for different model alias — wired in 7.8
- `_strip_thinking()` in action_parser.py: strips `<think>` blocks from model output
- `structural_health` dict in RunState: existing counters for json_parse_fallback, schema_mismatch, format_correction_hints, format_retries, cloud_fallback_count

### Established Patterns
- `P1_*` env var pattern for all configuration overrides
- `structural_health` counters incremented with `.get(key, 0) + 1` pattern
- `ensure_state_defaults()` uses `.setdefault()` for new state keys
- Provider `context_size()` method returns hardcoded values per provider type (Phase 7.6)
- Cloud fallback per-step (not sticky) from Phase 7.8

### Integration Points
- `mission_parser.py:258`: `timeout_seconds: float = 5.0` — parser timeout to make adaptive
- `mission_parser.py:452`: intent classifier 0.5s timeout
- `graph.py:1067`: `_generate_with_hard_timeout()` — pre-call context check goes here
- `graph.py:1062`: `route_by_signals()` call — planner routing happens here
- `run.py` + `user_run.py`: run log output (append structured debug to api.log)
- `context_manager.py`: `compact()` and eviction logic — needs mid-mission trigger path

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within stabilization scope

</deferred>

---

*Feature: stabilize-parser-planner-context*
*Context gathered: 2026-03-10*
