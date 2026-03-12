---
phase: 07.8-multi-model-provider-routing-+-smart-cloud-fallback
feature: stabilize-parser-planner-context
type: execute
autonomous: true
files_modified:
  - src/agentic_workflows/orchestration/langgraph/mission_parser.py
  - src/agentic_workflows/orchestration/langgraph/graph.py
  - src/agentic_workflows/orchestration/langgraph/context_manager.py
  - src/agentic_workflows/orchestration/langgraph/state_schema.py
  - src/agentic_workflows/logger.py
  - tests/unit/test_parser_timeout.py
  - tests/unit/test_context_overflow.py

must_haves:
  truths:
    - "Local models (LlamaCpp/Ollama) get a longer parser timeout than cloud providers"
    - "P1_PARSER_TIMEOUT_SECONDS env var overrides auto-detected timeout"
    - "Parser timeout fallbacks are tracked in structural_health as parser_timeout_count"
    - "Context is proactively compacted before each planner LLM call when approaching ctx limit"
    - "Context overflow (exceed_context_size_error) never crashes the run -- fallback path handles it"
    - "Planning step always routes to the strong model via route_by_signals"
    - "Per-step structured debug info is logged to .tmp/api.log with model, provider, routing decision, parse result"
  artifacts:
    - path: "src/agentic_workflows/orchestration/langgraph/mission_parser.py"
      provides: "Adaptive parser timeout by provider type"
      contains: "P1_PARSER_TIMEOUT_SECONDS"
    - path: "src/agentic_workflows/orchestration/langgraph/graph.py"
      provides: "Pre-call context compaction, overflow fallback, debug logging"
      contains: "proactive_compact"
    - path: "tests/unit/test_parser_timeout.py"
      provides: "Tests for adaptive timeout selection"
      min_lines: 30
    - path: "tests/unit/test_context_overflow.py"
      provides: "Tests for proactive compaction trigger"
      min_lines: 20
  key_links:
    - from: "graph.py _plan_next_action"
      to: "context_manager.proactive_compact()"
      via: "pre-call check against provider.context_size()"
      pattern: "proactive_compact"
    - from: "graph.py run()"
      to: "parse_missions(timeout_seconds=...)"
      via: "adaptive timeout from provider type"
      pattern: "parser_timeout"

rollback_notes: |
  All changes are additive -- no existing behavior is removed.
  - mission_parser.py: revert timeout_seconds default back to 5.0, remove P1_PARSER_TIMEOUT_SECONDS read
  - graph.py: remove proactive_compact call before planner, remove debug logging lines
  - context_manager.py: remove proactive_compact() method
  - state_schema.py: remove parser_timeout_count from structural_health defaults
  - Delete tests/unit/test_parser_timeout.py and tests/unit/test_context_overflow.py
  Git: `git diff HEAD~1 --name-only` shows all touched files; `git revert HEAD` cleanly reverts.
---

<objective>
Stabilize Phase 7.8 runtime by fixing three observed issues from live Qwen14B/Phi4 runs: (1) parser timeout too aggressive at 5s for local models causing constant regex fallback, (2) context overflow mid-mission crashing the run, and (3) lack of structured debug logging. Also ensure planning always routes to the strong model.

Purpose: Make multi-model local inference reliable -- parser gets enough time, context never overflows, and debug visibility enables rapid issue diagnosis.
Output: Adaptive parser timeout, proactive context compaction, structured debug logging, supporting tests.
</objective>

<context>
@.planning/STATE.md
@.planning/phases/07.8-multi-model-provider-routing-+-smart-cloud-fallback/features/stabilize-parser-planner-context/FEATURE-CONTEXT.md

<interfaces>
<!-- Key interfaces the executor needs -->

From mission_parser.py (current signature to modify):
```python
def parse_missions(
    user_input: str,
    timeout_seconds: float = 5.0,       # <- make adaptive
    max_plan_steps: int = 7,
    classifier_provider: ChatProvider | None = None,
    classifier_timeout: float = 0.5,     # <- consider extending for local
) -> StructuredPlan:
```
Note: `_parse_missions_inner()` is pure regex/text parsing (no LLM). The 5s timeout wraps this regex parser. The intent classifier (`_classify_intent()`) is the LLM call with its own 0.5s timeout.

From graph.py (call site at line 688):
```python
structured_plan = parse_missions(
    user_input,
    classifier_provider=self.provider,
)
# Uses default timeout_seconds=5.0 and classifier_timeout=0.5
```

From graph.py _plan_next_action (line 871-874):
```python
def _plan_next_action(self, state: RunState) -> RunState:
    state = ensure_state_defaults(state, system_prompt=self.system_prompt)
    self.context_manager.compact(state)  # existing compaction (sliding window)
    # ... then builds messages and calls _generate_with_hard_timeout
```

From context_manager.py compact() (line 567):
```python
def compact(self, state: dict[str, Any]) -> None:
    """Unified compaction: enforce sliding window hard cap."""
    messages = state.get("messages", [])
    if len(messages) <= self.sliding_window_cap:
        return
    # Keeps system + newest (cap-1) messages
```

From provider.py context_size() methods:
```python
# OpenAIChatProvider.context_size() -> 128000
# GroqChatProvider.context_size() -> 32768
# OllamaChatProvider.context_size() -> num_ctx or env or 32768
# LlamaCppChatProvider.context_size() -> int(os.getenv("LLAMA_CPP_N_CTX", "8192"))
```

From state_schema.py structural_health defaults:
```python
"structural_health": {
    "json_parse_fallback": 0, "schema_mismatch": 0,
    "format_correction_hints": 0, "format_retries": 0,
    "cloud_fallback_count": 0,
    "local_model_failures": {"timeout": 0, "parse": 0},
    "routing_decisions": {"strong": 0, "fast": 0},
}
```

From logger.py setup_dual_logging():
```python
def setup_dual_logging(log_dir: str = ".tmp") -> None:
    # Creates: log.txt (verbose), admin_log.txt, server_logs.txt, provider_logs.txt
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Adaptive parser timeout + intent classifier timeout + structural_health tracking</name>
  <files>src/agentic_workflows/orchestration/langgraph/mission_parser.py, src/agentic_workflows/orchestration/langgraph/graph.py, src/agentic_workflows/orchestration/langgraph/state_schema.py, tests/unit/test_parser_timeout.py</files>
  <behavior>
    - Test 1: _adaptive_parser_timeout(LlamaCppChatProvider) returns 30.0 (local model, needs more time for regex on large inputs)
    - Test 2: _adaptive_parser_timeout(OllamaChatProvider) returns 30.0
    - Test 3: _adaptive_parser_timeout(GroqChatProvider) returns 5.0 (cloud, fast)
    - Test 4: _adaptive_parser_timeout(OpenAIChatProvider) returns 5.0
    - Test 5: _adaptive_parser_timeout(None) returns 5.0 (no provider = default)
    - Test 6: P1_PARSER_TIMEOUT_SECONDS="15" env var overrides all auto-detection to 15.0
    - Test 7: _adaptive_classifier_timeout(LlamaCppChatProvider) returns 5.0 (local LLM classifier needs more time)
    - Test 8: _adaptive_classifier_timeout(GroqChatProvider) returns 0.5 (cloud stays fast)
  </behavior>
  <action>
1. Create `tests/unit/test_parser_timeout.py` with above tests. Mock provider classes using simple objects with `__class__.__name__` matching the provider names. Use `unittest.mock.patch.dict(os.environ, ...)` for env var tests.

2. In `mission_parser.py`, add a module-level helper (before `parse_missions`):
   ```python
   _LOCAL_PROVIDERS = {"LlamaCppChatProvider", "OllamaChatProvider"}
   _DEFAULT_LOCAL_TIMEOUT = 30.0
   _DEFAULT_CLOUD_TIMEOUT = 5.0
   _DEFAULT_LOCAL_CLASSIFIER_TIMEOUT = 5.0
   _DEFAULT_CLOUD_CLASSIFIER_TIMEOUT = 0.5

   def _adaptive_parser_timeout(provider: ChatProvider | None) -> float:
       env_override = os.getenv("P1_PARSER_TIMEOUT_SECONDS")
       if env_override:
           try:
               val = float(env_override)
               if val > 0:
                   return val
           except ValueError:
               pass
       if provider is not None and type(provider).__name__ in _LOCAL_PROVIDERS:
           return _DEFAULT_LOCAL_TIMEOUT
       return _DEFAULT_CLOUD_TIMEOUT

   def _adaptive_classifier_timeout(provider: ChatProvider | None) -> float:
       if provider is not None and type(provider).__name__ in _LOCAL_PROVIDERS:
           return _DEFAULT_LOCAL_CLASSIFIER_TIMEOUT
       return _DEFAULT_CLOUD_CLASSIFIER_TIMEOUT
   ```
   Add `import os` at the top of mission_parser.py if not already present.

3. In `graph.py` at the `parse_missions` call site (line 688), pass adaptive timeouts:
   ```python
   from agentic_workflows.orchestration.langgraph.mission_parser import (
       _adaptive_parser_timeout,
       _adaptive_classifier_timeout,
   )
   # ... in run() method:
   structured_plan = parse_missions(
       user_input,
       timeout_seconds=_adaptive_parser_timeout(self.provider),
       classifier_provider=self.provider,
       classifier_timeout=_adaptive_classifier_timeout(self.provider),
   )
   ```
   Import the helpers alongside the existing `parse_missions` import at line 43.

4. In `state_schema.py`, add `"parser_timeout_count": 0` to structural_health in both `new_run_state()` and `ensure_state_defaults()`.

5. In `mission_parser.py` `parse_missions()`, in the timeout fallback path (line 305), accept an optional `structural_health: dict | None = None` parameter and increment the counter:
   Actually, simpler approach -- `parse_missions` returns a `StructuredPlan` whose `parsing_method` is `"regex_fallback"` on timeout. Track this in graph.py after the call:
   ```python
   if structured_plan.parsing_method == "regex_fallback":
       state["structural_health"]["parser_timeout_count"] = (
           state["structural_health"].get("parser_timeout_count", 0) + 1
       )
   ```
   This avoids changing `parse_missions` signature for state tracking and keeps concerns separated.

6. Log a WARNING when parser falls back due to timeout in `parse_missions` -- already done (line 305 logs `PARSER FALLBACK reason=timeout`). Change log level from INFO to WARNING for the timeout case to make it more visible.
  </action>
  <verify>
    <automated>cd /home/nir/dev/agent_phase0 && python -m pytest tests/unit/test_parser_timeout.py -x -q && python -m pytest tests/unit/ -x -q --timeout=60</automated>
  </verify>
  <done>Adaptive parser timeout returns 30s for local providers, 5s for cloud; P1_PARSER_TIMEOUT_SECONDS env var overrides; intent classifier gets 5s for local, 0.5s for cloud; parser_timeout_count tracked in structural_health; all unit tests pass</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Proactive context compaction before planner calls + overflow fallback</name>
  <files>src/agentic_workflows/orchestration/langgraph/context_manager.py, src/agentic_workflows/orchestration/langgraph/graph.py, tests/unit/test_context_overflow.py</files>
  <behavior>
    - Test 1: proactive_compact() triggers compaction when estimated tokens > 80% of ctx_limit
    - Test 2: proactive_compact() does nothing when estimated tokens < 80% of ctx_limit
    - Test 3: proactive_compact() with very large messages compacts to fit under ctx_limit
    - Test 4: After proactive_compact(), if messages still exceed ctx_limit, logs WARNING but does not crash
  </behavior>
  <action>
1. Create `tests/unit/test_context_overflow.py` with above behavior tests. Create a ContextManager with small `sliding_window_cap` and test `proactive_compact()` with messages of varying sizes.

2. In `context_manager.py`, add `proactive_compact()` method:
   ```python
   def proactive_compact(self, state: dict[str, Any], ctx_limit: int) -> None:
       """Compact messages when estimated token count approaches ctx_limit.

       Called before each planner LLM call to prevent exceed_context_size_error.
       Uses len//4 token estimation (same as token_budget tracking in graph.py).
       Triggers at 80% of ctx_limit to leave headroom for the response.
       """
       messages = state.get("messages", [])
       estimated_tokens = sum(len(str(m.get("content", ""))) // 4 for m in messages)
       threshold = int(ctx_limit * 0.8)

       if estimated_tokens <= threshold:
           return

       _logger.warning(
           "PROACTIVE COMPACT triggered: estimated_tokens=%d threshold=%d ctx_limit=%d messages=%d",
           estimated_tokens, threshold, ctx_limit, len(messages),
       )

       # First try standard sliding window compaction
       self.compact(state)

       # Re-estimate after compaction
       messages = state.get("messages", [])
       estimated_tokens_after = sum(len(str(m.get("content", ""))) // 4 for m in messages)

       if estimated_tokens_after > threshold:
           # Aggressive compaction: keep system + last 5 messages
           system_msgs = [m for m in messages if m.get("role") == "system"]
           non_system = [m for m in messages if m.get("role") != "system"]
           aggressive_keep = min(5, len(non_system))
           state["messages"] = system_msgs + non_system[-aggressive_keep:]
           _logger.warning(
               "AGGRESSIVE COMPACT: reduced from %d to %d messages (estimated_tokens was %d, ctx_limit=%d)",
               len(messages), len(state["messages"]), estimated_tokens_after, ctx_limit,
           )

       # Final check -- if still over, log but do not crash
       final_tokens = sum(len(str(m.get("content", ""))) // 4 for m in state.get("messages", []))
       if final_tokens > ctx_limit:
           _logger.warning(
               "CONTEXT STILL EXCEEDS LIMIT after compaction: estimated=%d limit=%d — provider may reject",
               final_tokens, ctx_limit,
           )
   ```

3. In `graph.py` `_plan_next_action()`, after the existing `self.context_manager.compact(state)` call (line 874), add:
   ```python
   # Proactive compaction against provider context limit
   try:
       _routed_provider = self._router.route_by_signals(...)  # this happens later, so use the provider directly
       ctx_limit = self.provider.context_size()
       self.context_manager.proactive_compact(state, ctx_limit)
   except Exception:
       pass  # graceful degradation -- don't crash if proactive compact fails
   ```
   Actually, place this right after the existing compact() call at line 874, before the step counter increment. Use `self.provider.context_size()` since we want the primary provider's limit (that's what will reject the request). Wrap in try/except for graceful degradation (matching the Phase 7.1 pattern for ContextManager lifecycle calls).

4. In graph.py, in the `except` block for the planner call (where ProviderTimeoutError and other exceptions are caught), add handling for context overflow errors:
   ```python
   except Exception as exc:
       if "exceed_context_size" in str(exc).lower() or "context length" in str(exc).lower():
           self.logger.warning(
               "CONTEXT OVERFLOW step=%s — triggering aggressive compaction and retry",
               state["step"],
           )
           self.context_manager.proactive_compact(state, self.provider.context_size())
           # One retry after aggressive compaction
           try:
               model_output = self._generate_with_hard_timeout(
                   state["messages"], signals=_signals,
               ).strip()
           except Exception:
               # Fall through to deterministic fallback
               state["policy_flags"]["planner_timeout_mode"] = True
       else:
           raise
   ```
   Be careful about placement -- this should be an additional except clause, not replacing existing ones.
  </action>
  <verify>
    <automated>cd /home/nir/dev/agent_phase0 && python -m pytest tests/unit/test_context_overflow.py -x -q && python -m pytest tests/unit/ -x -q --timeout=60</automated>
  </verify>
  <done>proactive_compact() triggers at 80% ctx_limit with aggressive fallback to 5 messages; context overflow caught and retried after compaction; all unit tests pass; no crash on exceed_context_size_error</done>
</task>

<task type="auto">
  <name>Task 3: Structured per-step debug logging to .tmp/api.log + planning routes to strong model</name>
  <files>src/agentic_workflows/orchestration/langgraph/graph.py, src/agentic_workflows/logger.py</files>
  <action>
1. In `logger.py`, add a new file handler in `setup_dual_logging()` for api.log:
   ```python
   # API debug: per-step planner debug info
   api_handler = logging.FileHandler(log_path / "api.log", mode="a")
   api_handler.setLevel(logging.DEBUG)
   api_handler.setFormatter(fmt)
   api_handler.addFilter(_PrefixFilter(("api_debug",)))
   root.addHandler(api_handler)
   ```
   Add `"api_debug"` to the appropriate filter. If `_PrefixFilter` is the existing filter mechanism, add a new one specifically for `api_debug` logger prefix.

   Actually, simpler approach: create a dedicated logger `_api_logger = get_logger("api_debug")` in graph.py and add a FileHandler for it in `setup_dual_logging()`. The existing filter infrastructure already routes by logger name prefix.

2. In `graph.py`, add at module level:
   ```python
   _api_logger = get_logger("api_debug")
   ```

3. In `graph.py` `_plan_next_action()`, after the model_output is received (line 1071), log structured debug info:
   ```python
   _api_logger.info(
       "PLANNER_STEP step=%s model=%s provider=%s tier=%s "
       "routing_signals=%s tokens_est=%d parse_method=%s "
       "output_preview=%s",
       state["step"],
       getattr(_routed_provider, "model", "unknown"),
       type(_routed_provider).__name__,
       _tier,
       _signals,
       len(model_output) // 4,
       "pending",  # will be updated after parsing
       model_output[:200],
   )
   ```

4. After parsing completes (after `validate_action` or fallback), log the parse result:
   ```python
   _api_logger.info(
       "PLANNER_PARSE step=%s action=%s tool=%s fallback=%s",
       state["step"],
       action.get("action", "unknown") if isinstance(action, dict) else "unknown",
       action.get("tool_name", "none") if isinstance(action, dict) else "none",
       str(used_fallback),
   )
   ```
   Place this after the parse_action_json / parse_all_actions_json call and the fallback determination.

5. At run start (in `run()` method, after parse_missions), log the system prompt strategy:
   ```python
   _api_logger.info(
       "RUN_START run_id=%s missions=%d system_prompt_len=%d parser_timeout=%.1f classifier_timeout=%.1f",
       state["run_id"],
       len(missions),
       len(self.system_prompt),
       _adaptive_parser_timeout(self.provider),
       _adaptive_classifier_timeout(self.provider),
   )
   ```

6. For planner model routing: the current `route_by_signals` already routes planning to strong when `mission_type="multi_step"` or budget is low. To ensure planning ALWAYS uses the strong model, modify the `_signals` construction in `_plan_next_action()` to set `mission_type="multi_step"` when the current action is a planning step (which it always is in `_plan_next_action`). This guarantees the strong model is selected for every planning call per the user's decision that "Planning uses the strong model (Phi4)":
   ```python
   _signals: RoutingSignals = {
       "token_budget_remaining": int(state.get("token_budget_remaining", 100000)),
       "mission_type": "multi_step",  # Always route planning to strong model
       "retry_count": int(state["retry_counts"].get("provider_timeout", 0)),
       "step": state["step"],
       "intent_classification": _intent,
   }
   ```
   This is a one-line change from `(_intent or {}).get("mission_type", "unknown")` to `"multi_step"`.
  </action>
  <verify>
    <automated>cd /home/nir/dev/agent_phase0 && python -c "
from agentic_workflows.logger import get_logger
_api = get_logger('api_debug')
assert _api is not None, 'api_debug logger not created'
print('api_debug logger OK')
" && python -m pytest tests/unit/ -x -q --timeout=60</automated>
  </verify>
  <done>Per-step debug info logged to .tmp/api.log via api_debug logger (model, provider, tier, routing signals, parse result); planning always routes to strong model via mission_type="multi_step" override; system prompt length logged at run start; all unit tests pass</done>
</task>

</tasks>

<verification>
```bash
cd /home/nir/dev/agent_phase0 && python -m pytest tests/unit/test_parser_timeout.py tests/unit/test_context_overflow.py -x -q
cd /home/nir/dev/agent_phase0 && python -m pytest tests/ -q --timeout=120
cd /home/nir/dev/agent_phase0 && python -c "
from agentic_workflows.orchestration.langgraph.mission_parser import _adaptive_parser_timeout, _adaptive_classifier_timeout
print(f'Local parser timeout: {_adaptive_parser_timeout.__doc__}')
"
cd /home/nir/dev/agent_phase0 && make lint
```
</verification>

<success_criteria>
- Local models get 30s parser timeout, cloud stays at 5s
- P1_PARSER_TIMEOUT_SECONDS env var overrides auto-detection
- Intent classifier gets 5s for local, 0.5s for cloud
- parser_timeout_count tracked in structural_health
- Proactive compaction triggers at 80% ctx_limit before every planner call
- Context overflow errors caught and retried after aggressive compaction (never crash)
- Planning always routes to strong model (mission_type forced to "multi_step")
- Per-step debug info logged to .tmp/api.log with model, provider, tier, routing, parse result
- All existing 823+ tests pass unchanged
- ruff check clean
</success_criteria>

<output>
After completion, create `.planning/phases/07.8-multi-model-provider-routing-+-smart-cloud-fallback/features/stabilize-parser-planner-context/FEATURE-SUMMARY.md`
</output>
