# Phase 7.8 Walkthrough: Multi-Model Provider Routing + Smart Cloud Fallback

**Phase goal:** Extend the orchestration layer to support alias-based multi-model routing on a
single llama-server instance, replace intent-only routing with signal-based complexity inference,
and add automatic cloud fallback when the local model fails (timeout or repeated parse failures).

**Status:** Complete (4/4 plans, 2026-03-10)

---

## Overview

Phase 7.8 tackles a practical problem with local LLM deployments: a single model cannot optimally
handle both planning (complex reasoning) and execution (fast tool dispatch). Rather than running
multiple server processes, this phase uses llama-server's `--alias` flag to load multiple models
on one server and route requests to the appropriate model based on runtime signals.

When the local model fails entirely (timeout or repeated parse failures), the system falls back
to a cloud provider (Groq) for that single step, then returns to local for the next step. This
per-step fallback minimizes cloud usage while maintaining reliability.

Three components were modified:
1. **LlamaCppChatProvider** -- `with_alias()` factory for alias-based routing
2. **ModelRouter** -- `route_by_signals()` replaces `route_by_intent()`
3. **LangGraphOrchestrator** -- cloud fallback logic + `fallback_provider` parameter

---

## Alias-Based Multi-Model Routing

### The Problem

ModelRouter already supports strong/fast provider tiers, but when using llama-server locally,
both tiers pointed to the same model. You could run two separate llama-server instances, but
that doubles memory usage and operational complexity.

### The Solution: `with_alias()`

llama-server supports loading multiple models with the `--alias` flag:

```bash
llama-server \
  --model planner.gguf --alias planner \
  --model executor.gguf --alias executor
```

The OpenAI-compatible API routes requests based on the `model` field in the request body,
matching against configured aliases. Since `LlamaCppChatProvider` already passes `self.model`
to `self.client.chat.completions.create()`, the factory method just creates a new instance
with a different model name:

```python
def with_alias(self, alias: str) -> LlamaCppChatProvider:
    clone = LlamaCppChatProvider.__new__(LlamaCppChatProvider)
    clone.timeout_seconds = self.timeout_seconds
    clone.max_retries = self.max_retries
    clone.retry_backoff_seconds = self.retry_backoff_seconds
    clone.model = alias
    clone.client = self.client  # Share the same OpenAI client
    clone._grammar_enabled = self._grammar_enabled
    # ... copy remaining attributes
    return clone
```

The `__new__` pattern avoids calling `__init__`, which would trigger `_detect_llama_cpp_model()`
-- an HTTP call to the server that would fail or return the wrong model for the alias.

### Configuration

Two env vars control alias routing:

| Variable | Purpose | Default |
|----------|---------|---------|
| `LLAMA_CPP_STRONG_ALIAS` | Model alias for complex tasks (planning, multi-step) | Same as detected model |
| `LLAMA_CPP_FAST_ALIAS` | Model alias for simple tasks (tool dispatch) | Same as detected model |

In `graph.py __init__`, if either env var is set and the primary provider is LlamaCpp,
alias-based providers are created and wired into the ModelRouter:

```python
strong_alias = os.getenv("LLAMA_CPP_STRONG_ALIAS")
fast_alias = os.getenv("LLAMA_CPP_FAST_ALIAS")
if (strong_alias or fast_alias) and isinstance(self.provider, LlamaCppChatProvider):
    _strong = self.provider.with_alias(strong_alias) if strong_alias else self.provider
    _fast = self.provider.with_alias(fast_alias) if fast_alias else self.provider
    self._router = ModelRouter(strong_provider=_strong, fast_provider=_fast)
```

If neither env var is set, both tiers use the same provider (preserving current behavior).

---

## Signal-Based Routing

### Why Replace Intent-Only Routing

`route_by_intent()` only considered the intent classifier's output. But routing decisions
benefit from more context: How much token budget remains? Is this a retry? How many steps
have elapsed? These signals paint a fuller picture of when to use the stronger model.

### RoutingSignals TypedDict

```python
class RoutingSignals(TypedDict):
    token_budget_remaining: int
    mission_type: str        # from intent_classification or "unknown"
    retry_count: int
    step: int
    intent_classification: dict[str, Any] | None
```

### Decision Logic

`route_by_signals()` applies thresholds in priority order:

1. **retry_count >= 2** -> strong (reliability needed after repeated failures)
2. **token_budget_remaining < 5000** -> strong (conserve remaining budget with precise output)
3. **mission_type == "multi_step"** -> strong (complex reasoning)
4. **intent_classification complexity** -> strong if "complex", fast if "simple"
5. **Default** -> fast

Thresholds are module-level constants (`_BUDGET_STRONG_THRESHOLD = 5000`,
`_RETRY_STRONG_THRESHOLD = 2`), easy to tune without code changes.

### Tracking

Each routing decision is recorded in `structural_health["routing_decisions"]`:

```python
routing_decisions: {"strong": N, "fast": M}
```

This distribution appears in the audit panel, helping validate whether the router makes
sensible splits for a given workload.

---

## Cloud Fallback

### When It Triggers

Cloud fallback activates on two conditions:

1. **ProviderTimeoutError** -- local model exceeds the hard timeout
2. **2 consecutive parse failures** -- after the Phase 7.7 escalation chain
   (hint -> retry -> accept) exhausts without producing valid JSON

### Per-Step Behavior

Cloud fallback is **per-step, not sticky**. Each step independently:
1. Tries the local model first
2. On failure, tries the fallback provider
3. On fallback failure, falls through to deterministic action

The next step starts fresh with the local model. This minimizes cloud API usage --
a single timeout does not commit the rest of the run to cloud execution.

### Implementation

`LangGraphOrchestrator.__init__` accepts `fallback_provider: ChatProvider | None`:

```python
class LangGraphOrchestrator:
    def __init__(self, *, ..., fallback_provider: ChatProvider | None = None):
        self._fallback_provider = fallback_provider
        self._consecutive_parse_failures = 0
```

In `_plan_next_action()`, two insertion points:

**After ProviderTimeoutError:**
```python
except ProviderTimeoutError:
    if self._fallback_provider is not None:
        cloud_output = self._fallback_provider.generate(messages, ...)
        state["structural_health"]["cloud_fallback_count"] += 1
        state["structural_health"]["local_model_failures"]["timeout"] += 1
```

**After 2 consecutive parse failures:**
```python
if self._consecutive_parse_failures >= 2 and self._fallback_provider is not None:
    cloud_output = self._fallback_provider.generate(messages, ...)
    state["structural_health"]["cloud_fallback_count"] += 1
    state["structural_health"]["local_model_failures"]["parse"] += 1
```

`_consecutive_parse_failures` is an instance attribute (not state), so it resets
naturally per orchestrator lifecycle and does not pollute checkpointed state.

### Why Groq

Groq was chosen as the default fallback provider because:
- Free tier available (no cost for occasional fallback)
- Already integrated (`GroqChatProvider` exists with retry logic)
- Fast inference (low latency addition to the step)

In `run.py`, the fallback provider is constructed from environment:

```python
fallback_provider = None
if os.getenv("GROQ_API_KEY"):
    try:
        fallback_provider = GroqChatProvider()
    except Exception:
        pass  # No fallback -- graceful degradation
```

---

## Structural Health Expansion

Phase 7.8 adds three new counters to the existing `structural_health` dict in RunState:

| Counter | Type | Purpose |
|---------|------|---------|
| `cloud_fallback_count` | `int` | Total cloud fallback events during the run |
| `local_model_failures` | `dict` | Breakdown: `{"timeout": N, "parse": M}` |
| `routing_decisions` | `dict` | Distribution: `{"strong": N, "fast": M}` |

These join the existing counters (`json_parse_fallback`, `schema_mismatch`,
`format_correction_hints`, `format_retries`) in `ensure_state_defaults()`.

### Audit Panel Display

**run.py** -- The `_print_audit_panel()` function shows a "Routing & Fallback" section:

```
  Routing & Fallback:
    Routing: strong=5 fast=3
    Cloud fallbacks: 2
    Local failures: timeout=1 parse=1
```

**cli/user_run.py** -- The run log output includes routing stats in the established
uppercase-key format:

```
ROUTING: strong=5 fast=3
CLOUD_FALLBACK: 2 event(s)
LOCAL_FAILURES: timeout=1 parse=1
```

Both displays are conditional -- they only appear when the counters are non-zero.

---

## Configuration Summary

| Variable | Purpose | Required |
|----------|---------|----------|
| `LLAMA_CPP_STRONG_ALIAS` | Model alias for strong tier | No (defaults to detected model) |
| `LLAMA_CPP_FAST_ALIAS` | Model alias for fast tier | No (defaults to detected model) |
| `GROQ_API_KEY` | Enables cloud fallback via Groq | No (no fallback if unset) |

---

## Key Decisions

1. **Why per-step fallback (not sticky):** Minimizes cloud usage. A single timeout does not
   commit subsequent steps to cloud execution. Each step re-attempts local first.

2. **Why RoutingSignals over intent-only:** Intent classification alone misses critical
   runtime context (budget, retries, step count). Signal-based routing adapts to the
   evolving state of the run, not just the initial task classification.

3. **Why Groq for fallback:** Free tier, already integrated, fast inference. No new
   dependencies or API integrations needed.

4. **Why `__new__` clone for `with_alias()`:** Avoids the HTTP call in
   `_detect_llama_cpp_model()` which would fail or return the wrong model for an alias.
   All attributes are explicitly copied from the source instance.

5. **Why `_consecutive_parse_failures` on instance (not state):** Resets naturally per
   orchestrator lifecycle. Does not pollute checkpointed state or complicate serialization.

---

*Phase: 07.8-multi-model-provider-routing-+-smart-cloud-fallback*
*Completed: 2026-03-10*
