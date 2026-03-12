# Phase 8: Multi-Model SYCL Routing and Planner Bottleneck Resolution - Research

**Researched:** 2026-03-11
**Domain:** LlamaCpp port-based multi-server routing, large Python module decomposition, tool-result caching with Postgres/pgvector
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**graph.py Decomposition**
- Strategy: by graph node/role — each major LangGraph node becomes its own file (e.g., `planner_node.py`, `executor_node.py`, `policy_node.py`, `finalize_node.py`). Thin wiring assembles them.
- Helpers co-located with their node — `_build_planner_context()` lives in `planner_node.py`, `_route_specialist_hint()` in `executor_node.py`, etc. Each file is self-contained.
- `LangGraphOrchestrator` moves to `orchestrator.py` — becomes the thin spine that imports all node files and assembles the StateGraph. `graph.py` becomes a re-export shim for backward compat.
- `graph.py` kept as re-export shim — `from .orchestrator import LangGraphOrchestrator` etc. All 657 tests pass unchanged with no import churn.
- No single file >600 lines after decomposition.

**SYCL Server Configuration**
- Two env vars: `LLAMA_CPP_PLANNER_PORT` and `LLAMA_CPP_EXECUTOR_PORT`. If only one is set (or neither), both roles use the same server (current behavior preserved).
- Consistent with Phase 7.8's `LLAMA_CPP_STRONG_ALIAS` / `LLAMA_CPP_FAST_ALIAS` pattern.
- `with_port(port: int) -> LlamaCppChatProvider` factory method — returns a new instance pointing to the overridden base URL port. Symmetrical with existing `with_alias()`. No new subclass.
- Startup behavior: warn + single-server fallback — if a configured server is unreachable at startup, log a warning and fall back to routing both roles through the available server. System runs, role separation is best-effort. Hard fail only if NO server is reachable.

**Result Summarization Storage**
- New `ToolResultCache` Postgres table (migration 005 is already taken by sub_task_cursors — this is 006) — dedicated table, not MissionContextStore or ArtifactStore. Separate concern, separate table, independent evolution path.
- Cache key: `tool_name` + `SHA-256(serialized args)` — exact deduplication. Consistent with Phase 7.3's `goal_hash` pattern.
- TTL + lazy eviction — each row has `expires_at` (configurable, default 7 days via env var). On cache lookup: if expired, treat as miss, delete inline. No background worker.

**Truncation Injection Shape**
- Format: `[Result truncated — {N} chars stored] Tool: {tool_name} | Key: {hash[:8]} | Summary: {first 200 chars}...`
- Uses `[Orchestrator]` prefix convention (Phase 7.1 / Phase 5 pattern).
- Threshold: `LARGE_RESULT_THRESHOLD` env var, default `2000` chars. Results exceeding this are cached and replaced with compact injection.
- Location: `ContextManager.build_planner_context_injection()` — truncation happens before planner injection, not at tool execution time. `tool_history` retains the full result (for audit/retrieval); only the planner message sees the compact form. No graph.py changes required for this path.

### Claude's Discretion
- Exact node file naming (e.g., `planner_node.py` vs `nodes/planner.py`)
- Whether `finalize_node.py` and `policy_node.py` warrant separate files or share a `lifecycle_nodes.py`
- Internal `with_port()` client re-init strategy (new httpx client vs shared base + override)
- `ToolResultCache` migration SQL and exact column layout
- TTL default value (7 days recommended, configurable)

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SYCL-01 | `LlamaCppChatProvider` accepts a port override; orchestrator instantiates role-specific providers at startup via `LLAMA_CPP_PLANNER_PORT` / `LLAMA_CPP_EXECUTOR_PORT` | `with_alias()` factory pattern at provider.py:568 is the exact template; `with_port()` follows same `__new__`-clone approach, overrides `client` only |
| SYCL-02 | `graph.py` decomposed into focused sub-modules (no single file >600 lines); existing 823+ tests pass unchanged | Re-export shim pattern already exists (`langgraph_orchestrator.py`); the graph.py module is 3280 lines; internal symbols tested by private import need shim-forwarding |
| BTLNK-01 | A mission producing output >threshold chars never causes planner to receive more than configured context cap — integration test with large synthetic tool result | `build_planner_context_injection()` at context_manager.py:752 is the interception point; existing `_CONTEXT_CAP = 1500` pattern shows capping approach |
| BTLNK-02 | Large results persisted to Postgres/pgvector and replaced with compact summary pointer — unit test confirms full result retrievable and injected text is ≤ cap | `ArtifactStore` pattern (storage/artifact_store.py) is the template; migration 006 needed; `ToolResultCache` is a new store following same pool-injection + SHA-256 key pattern |
</phase_requirements>

---

## Summary

Phase 8 combines two focused engineering goals into one delivery cycle. The first goal is production-hardening the local SYCL inference stack: allow two llama-server processes (planner model vs executor model) on different ports to serve different agent roles, without breaking the single-server default. The second goal is eliminating the planner context flood that occurs when tool results return large payloads — instead of naively appending thousands of characters to the message window, the system stores the full result in Postgres and injects a compact pointer.

Both goals are well-constrained by prior phase work. `with_alias()` (Phase 7.8) established the factory-clone pattern for `LlamaCppChatProvider`; `with_port()` is a mechanical parallel. `ArtifactStore` + SHA-256 key hashing (Phase 7.3) established the Postgres storage pattern; `ToolResultCache` follows identically. The ContextManager injection point (`build_planner_context_injection()`) already trims to `_CONTEXT_CAP`; adding a pre-injection store-and-replace step is an additive change to the same function.

The graph.py decomposition is the riskiest work unit — at 3280 lines, the file holds everything from `LangGraphOrchestrator.__init__` to all graph node methods. The safe path is: move code to new files, keep `graph.py` as a pure re-export shim, verify all 823+ tests pass. Tests import private symbols (`_derive_annotated_list_fields`, `_ANNOTATED_LIST_FIELDS`, `_active_callbacks_var`, `_HANDOFF_QUEUE_CAP`, `_HANDOFF_RESULTS_CAP`) directly from `graph` — the shim must re-export all of them.

**Primary recommendation:** Work in four isolated plans — (1) `with_port()` + orchestrator port wiring, (2) graph.py decomposition with shim, (3) `ToolResultCache` store + migration, (4) ContextManager interception + integration tests.

---

## Standard Stack

### Core (already in use — no new dependencies)
| Component | Version | Purpose | Status |
|-----------|---------|---------|--------|
| psycopg[binary] + psycopg_pool | project-standard | Postgres connection pool; sync `%s` placeholders | Existing pattern (Phase 7) |
| hashlib (stdlib) | Python 3.12 | SHA-256 key hashing for `ToolResultCache` | Existing pattern (Phase 7.3) |
| httpx | project-standard | Port-override URL construction for `with_port()` | Already used in provider.py |
| OpenAI (SDK) | project-standard | LlamaCppChatProvider's underlying client | Already in provider.py |

### No New Dependencies
This phase adds no new packages. `ToolResultCache` uses the same psycopg3 + SHA-256 pattern already proven in `MissionContextStore` and `ArtifactStore`. `with_port()` constructs a new `base_url` string and re-initializes the OpenAI client inline.

---

## Architecture Patterns

### Recommended Module Structure After Decomposition

The current `orchestration/langgraph/` directory has 30 files. After decomposition, `graph.py` becomes a re-export shim and `orchestrator.py` becomes the main spine:

```
src/agentic_workflows/orchestration/langgraph/
├── graph.py               # RE-EXPORT SHIM ONLY — backward compat for all importers
├── orchestrator.py        # NEW — LangGraphOrchestrator class, __init__, compile_graph, run()
├── planner_node.py        # NEW — _plan_next_action() + all planner helpers
├── executor_node.py       # NEW — _route_to_specialist() + _execute_action() + helpers
├── lifecycle_nodes.py     # NEW — _finalize() + _enforce_memo_policy() + _clarify_node()
├── provider.py            # EXISTING — add with_port() factory method
├── context_manager.py     # EXISTING — add ToolResultCache interception in build_planner_context_injection()
├── state_schema.py        # EXISTING — add tool_result_cache_hits / tool_result_truncations to structural_health
├── ...                    # all other existing files unchanged
storage/
└── tool_result_cache.py   # NEW — ToolResultCache store (follows ArtifactStore pattern)
db/migrations/
└── 006_tool_result_cache.sql  # NEW — tool_result_cache table
```

**Why `lifecycle_nodes.py` for finalize + policy rather than separate files:**
- `_finalize()` is 73 lines; `_enforce_memo_policy()` will fit alongside it comfortably under 600 lines.
- Both are "graph lifecycle" nodes with no helpers that belong to other nodes — co-locating avoids a trivially small standalone file.
- `_clarify_node()` (9 lines) naturally groups here too.

**Why `executor_node.py` contains both `_route_to_specialist` and `_execute_action`:**
- `_execute_action()` at 558 lines is the biggest single method. It handles the full tool dispatch loop.
- `_route_to_specialist()` at 110 lines is the "decide whether to delegate" wrapper — they are tightly coupled (specialist routing is part of execution).
- Together they fit within ~700 lines including helpers; if the limit is tight, helpers can move to `executor_helpers.py`.

**Estimated file sizes after decomposition:**
| File | Approx Lines | Within 600? |
|------|-------------|------------|
| `orchestrator.py` | ~400 | Yes |
| `planner_node.py` | ~1200 (currently 1078 in _plan_next_action + planner helpers) | NO — needs internal split |
| `executor_node.py` | ~700 | Borderline — helpers may split to executor_helpers.py |
| `lifecycle_nodes.py` | ~200 | Yes |

**CRITICAL PLANNING NOTE:** `_plan_next_action()` alone is 1078 lines. This cannot live in one file and meet the 600-line limit. It must be split — the inner planning loop helpers should move to `planner_helpers.py` or inline helpers to a separate `planner_internals.py`. The planner node file calls into these helpers but stays thin.

### Pattern 1: with_port() Factory Method

Follows the same `__new__`-clone approach as `with_alias()` at provider.py:568:

```python
# Source: provider.py:568 (with_alias pattern — with_port is parallel)
def with_port(self, port: int) -> LlamaCppChatProvider:
    """Return a new provider instance pointing to *port* on the same host.

    Constructs a new base_url with the overridden port and creates a fresh
    OpenAI client for that URL. All retry/timeout and grammar settings are
    copied from the source.
    """
    clone = LlamaCppChatProvider.__new__(LlamaCppChatProvider)
    # Copy _RetryingProviderBase attributes
    clone.timeout_seconds = self.timeout_seconds
    clone.max_retries = self.max_retries
    clone.retry_backoff_seconds = self.retry_backoff_seconds
    # Copy LlamaCpp-specific attributes
    clone._grammar_enabled = self._grammar_enabled
    clone.model = self.model
    # Build a new URL with overridden port, create a fresh client
    import re as _re
    old_url = str(self.client.base_url)
    new_url = _re.sub(r':\d+/', f':{port}/', old_url)
    clone.client = OpenAI(api_key="llama-cpp", base_url=new_url, timeout=self.timeout_seconds)
    return clone
```

NOTE: Unlike `with_alias()` which shares the client (same port, different model name), `with_port()` MUST create a new OpenAI client because the base URL changes. The URL regex approach avoids replicating the URL-construction logic from `__init__`.

### Pattern 2: Orchestrator Port Wiring

In `orchestrator.py` (new file), the `__init__` reads port env vars after the alias-based routing block:

```python
# After existing LLAMA_CPP_STRONG_ALIAS / LLAMA_CPP_FAST_ALIAS block
planner_port = os.getenv("LLAMA_CPP_PLANNER_PORT")
executor_port = os.getenv("LLAMA_CPP_EXECUTOR_PORT")
if (planner_port or executor_port) and isinstance(self.provider, LlamaCppChatProvider):
    # Verify reachability; warn + fallback if unreachable
    _planner_provider = self.provider.with_port(int(planner_port)) if planner_port else self.provider
    _executor_provider = self.provider.with_port(int(executor_port)) if executor_port else self.provider
    self._planner_provider = _planner_provider
    self._executor_provider = _executor_provider
else:
    self._planner_provider = self.provider
    self._executor_provider = self.provider
```

The `_generate_with_hard_timeout()` call in `_plan_next_action()` uses `self._planner_provider`; `_route_to_specialist()` / `_execute_action()` use `self._executor_provider`.

**Startup reachability check:** call `_detect_llama_cpp_model(port_base_url)` (already exists in provider.py:470). If it returns `None`, log warning + fall back to `self.provider` for that role.

### Pattern 3: ToolResultCache Storage

Follows `ArtifactStore` pattern exactly (storage/artifact_store.py):

```python
# Source: storage/artifact_store.py pattern
class ToolResultCache:
    def __init__(self, pool: ConnectionPool | None = None) -> None:
        self._pool = pool

    def store(self, *, tool_name: str, args_hash: str, full_result: str,
              summary: str, expires_at: datetime) -> None:
        """Store a large result. No-op when pool=None."""
        if self._pool is None:
            return
        with self._pool.connection() as conn:
            conn.execute("""
                INSERT INTO tool_result_cache
                    (tool_name, args_hash, full_result, summary, result_len, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (tool_name, args_hash)
                DO UPDATE SET full_result=EXCLUDED.full_result,
                              summary=EXCLUDED.summary,
                              result_len=EXCLUDED.result_len,
                              expires_at=EXCLUDED.expires_at
            """, (tool_name, args_hash, full_result, summary, len(full_result), expires_at))

    def get(self, *, tool_name: str, args_hash: str) -> str | None:
        """Retrieve cached full result. Returns None on miss or expiry (deletes expired inline)."""
        if self._pool is None:
            return None
        with self._pool.connection() as conn:
            row = conn.execute("""
                SELECT full_result, expires_at FROM tool_result_cache
                WHERE tool_name=%s AND args_hash=%s
            """, (tool_name, args_hash)).fetchone()
        if row is None:
            return None
        full_result, expires_at = row
        if expires_at < datetime.now(tz=timezone.utc):
            # Lazy TTL eviction
            with self._pool.connection() as conn:
                conn.execute("DELETE FROM tool_result_cache WHERE tool_name=%s AND args_hash=%s",
                             (tool_name, args_hash))
            return None
        return full_result
```

### Pattern 4: ContextManager Interception in build_planner_context_injection()

The interception happens in the existing `build_planner_context_injection()` method, before the cross-run injection logic. The `tool_history` list in state contains full results — these are the candidates for truncation:

```python
# Conceptual location: context_manager.py, build_planner_context_injection()
# Called BEFORE the existing base_result / cross_run_lines assembly

LARGE_RESULT_THRESHOLD = int(os.getenv("LARGE_RESULT_THRESHOLD", "2000"))

# Scan recent tool_history entries for large results
for record in state.get("tool_history", [])[-10:]:  # sliding window, not all history
    result_str = json.dumps(record.get("result", ""), default=str)
    if len(result_str) > LARGE_RESULT_THRESHOLD and self._tool_result_cache is not None:
        tool_name = record.get("tool", "unknown")
        args = record.get("args", {})
        args_hash = hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()
        summary = result_str[:200]
        # store() is no-op if already cached (ON CONFLICT DO UPDATE)
        self._tool_result_cache.store(
            tool_name=tool_name, args_hash=args_hash,
            full_result=result_str, summary=summary,
            expires_at=datetime.now(tz=timezone.utc) + TTL_DELTA,
        )
```

The injection shape replaces the raw result reference in `base_result`:
```
[Result truncated — 4821 chars stored] Tool: data_analysis | Key: a1b2c3d4 | Summary: {"mean": 42.3, "outliers": [99, 101]...
```

### Anti-Patterns to Avoid

- **Importing `graph.py` internals in new node files:** Node files should import from `state_schema`, `context_manager`, etc. directly — not from `graph.py` (creates circular imports once graph.py becomes the shim).
- **Mutating `tool_history` in ContextManager:** The interception must NOT modify `tool_history` — it only controls what the planner *message window* sees. Full results stay in `tool_history` for auditing.
- **Eagerly caching all results:** Only cache when `len(result) > LARGE_RESULT_THRESHOLD`. Small results should never hit Postgres.
- **Sharing the OpenAI client between ports in `with_port()`:** Unlike `with_alias()`, different ports require different base URLs so the OpenAI client MUST be re-initialized with the new URL.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SHA-256 hashing for cache key | Custom hash function | `hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()` | Exact match, already used in Phase 7.3 (`goal_hash`) |
| TTL eviction | Background scheduler/thread | Lazy inline delete on read | No scheduler needed; works in all contexts (CLI, FastAPI, CI); proven pattern |
| Port URL construction | URL parsing library | String regex on existing base URL | `_detect_llama_cpp_model()` already constructs URLs from base; same approach |
| Postgres connection management | New pool class | Inject existing `pg_pool` from app.py lifespan | Matches all other stores (CheckpointStore, MemoStore, ArtifactStore) |
| Test isolation for Postgres stores | Custom fixtures | `pytest.importorskip("psycopg_pool")` + `pg_pool` + `clean_pg` fixtures (already exist) | Project-standard pattern since Phase 7 |

---

## Common Pitfalls

### Pitfall 1: Private Symbol Re-Export Completeness
**What goes wrong:** Tests import private names directly from `graph.py` (e.g., `_derive_annotated_list_fields`, `_ANNOTATED_LIST_FIELDS`, `_active_callbacks_var`, `_HANDOFF_QUEUE_CAP`, `_HANDOFF_RESULTS_CAP`, `_ROLE_TOKEN_BUDGETS`, `_select_prompt_tier`). If the shim only re-exports public names, those tests break.
**Why it happens:** The shim author focuses on `LangGraphOrchestrator` and forgets private symbols used in tests.
**How to avoid:** Before writing the shim, grep all test files for `from agentic_workflows.orchestration.langgraph.graph import` and extract the complete list of symbols. The shim must export every one of them. Current full list from grep:
- `LangGraphOrchestrator`
- `MemoizationPolicyViolation`
- `_derive_annotated_list_fields`
- `_ANNOTATED_LIST_FIELDS`
- `_active_callbacks_var`
- `_HANDOFF_QUEUE_CAP`
- `_HANDOFF_RESULTS_CAP`
- `_ROLE_TOKEN_BUDGETS`
- `_select_prompt_tier`
- `graph_module` (imported as module in test_observability.py — module-level alias must work)

**Warning signs:** `ImportError` on test collection after decomposition.

### Pitfall 2: Planner Node Still Exceeds 600 Lines
**What goes wrong:** `_plan_next_action()` is 1078 lines. Moving it verbatim to `planner_node.py` creates a 1100+ line file.
**Why it happens:** The method grew organically with retry logic, context injection, token budget enforcement, format correction, and few-shot injection all interleaved.
**How to avoid:** Identify pure helper clusters: (a) context/prompt building (~300 lines), (b) retry/fallback loop (~400 lines), (c) response parsing/validation (~200 lines). Move helpers (a) and (c) to `planner_helpers.py`. `planner_node.py` contains `_plan_next_action()` itself calling these helpers, staying under 600 lines.
**Warning signs:** `planner_node.py` line count exceeds 600 after initial move.

### Pitfall 3: with_port() URL Regex Edge Cases
**What goes wrong:** The `LLAMA_CPP_BASE_URL` default is `http://127.0.0.1:8080/v1`. A naive regex that replaces `:\d+` could also match `8080` in an IPv6 address or a URL with no explicit port (port 80 implied).
**Why it happens:** URL manipulation without a parser.
**How to avoid:** Use `urllib.parse.urlparse()` to reconstruct the URL with the overridden port:
```python
from urllib.parse import urlparse, urlunparse
parsed = urlparse(old_base_url)
new_netloc = f"{parsed.hostname}:{port}"
new_url = urlunparse(parsed._replace(netloc=new_netloc))
```
This handles IPv6, implicit ports, and path components correctly.
**Warning signs:** `with_port(9090)` on `http://127.0.0.1:8080/v1` produces malformed URL.

### Pitfall 4: ContextManager tool_result_cache Param Initialization
**What goes wrong:** `ContextManager.__init__` gains a new `tool_result_cache` parameter. `LangGraphOrchestrator` constructs `ContextManager(...)` at graph.py:277. If the planner passes `tool_result_cache=None` (the default), truncation silently skips — but if the orchestrator constructs `ToolResultCache` but doesn't pass it, the feature never activates.
**Why it happens:** Wiring is multi-step: app.py creates `ToolResultCache(pool=pg_pool)`, passes to `LangGraphOrchestrator`, which passes to `ContextManager`.
**How to avoid:** Follow the `ArtifactStore` wiring chain established in Phase 7.5: `app.py lifespan` → `LangGraphOrchestrator.__init__` → `ContextManager.__init__`. Add to `run.py` and `user_run.py` the same lazy conditional import + instantiation as for `ArtifactStore`. Add `tool_result_cache: ToolResultCache | None = None` under TYPE_CHECKING in context_manager.py.
**Warning signs:** No `tool_result_truncations` increments in `structural_health` during runs with large outputs.

### Pitfall 5: Migration Number Collision
**What goes wrong:** CONTEXT.md says "migration 005" for `ToolResultCache`, but `005_sub_task_cursors.sql` already exists.
**Why it happens:** The CONTEXT.md was written before Phase 7.6 added migration 005.
**How to avoid:** The correct number is **006**. File: `db/migrations/006_tool_result_cache.sql`. The conftest fixture that applies migrations sorted (Phase 7.3 decision) will pick it up automatically.
**Warning signs:** `006` would fail if conftest only ran `001-005`.

### Pitfall 6: Circular Imports After Decomposition
**What goes wrong:** `orchestrator.py` imports from `planner_node.py` which imports from `orchestrator.py` (e.g., to access `LangGraphOrchestrator` type hints).
**Why it happens:** Node files need access to the orchestrator instance for `self._plan_next_action(state)` — they are currently methods, not standalone functions.
**How to avoid:** Keep node methods AS methods on `LangGraphOrchestrator` in `orchestrator.py`. What moves to node files is only the pure helper functions that do NOT reference `self`. The class itself stays in `orchestrator.py`. This eliminates circular imports entirely.
**Warning signs:** `ImportError: cannot import name 'LangGraphOrchestrator' from partially-initialized module`.

---

## Code Examples

### Re-export Shim Pattern (graph.py after decomposition)
```python
# Source: existing langgraph_orchestrator.py (already a shim — follow same pattern)
# graph.py after decomposition — pure re-export, no logic
from .orchestrator import (
    LangGraphOrchestrator,
    MemoizationPolicyViolation,
    _ANNOTATED_LIST_FIELDS,
    _HANDOFF_QUEUE_CAP,
    _HANDOFF_RESULTS_CAP,
    _ROLE_TOKEN_BUDGETS,
    _active_callbacks_var,
    _derive_annotated_list_fields,
    _select_prompt_tier,
    _sequential_node,
)

__all__ = [
    "LangGraphOrchestrator",
    "MemoizationPolicyViolation",
    "_ANNOTATED_LIST_FIELDS",
    "_HANDOFF_QUEUE_CAP",
    "_HANDOFF_RESULTS_CAP",
    "_ROLE_TOKEN_BUDGETS",
    "_active_callbacks_var",
    "_derive_annotated_list_fields",
    "_select_prompt_tier",
    "_sequential_node",
]
```

### ToolResultCache Migration SQL
```sql
-- 006_tool_result_cache.sql
CREATE TABLE IF NOT EXISTS tool_result_cache (
    id          SERIAL PRIMARY KEY,
    tool_name   TEXT NOT NULL,
    args_hash   TEXT NOT NULL,         -- SHA-256 of serialized args
    full_result TEXT NOT NULL,
    summary     TEXT NOT NULL,         -- first 200 chars of result
    result_len  INTEGER NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tool_name, args_hash)
);

CREATE INDEX IF NOT EXISTS ix_tool_result_cache_expires
    ON tool_result_cache(expires_at);

CREATE INDEX IF NOT EXISTS ix_tool_result_cache_lookup
    ON tool_result_cache(tool_name, args_hash);
```

### structural_health New Fields
```python
# state_schema.py: new_run_state() and ensure_state_defaults() additions
# Follow exact .setdefault() pattern from existing structural_health block
state_dict["structural_health"].setdefault("tool_result_cache_hits", 0)
state_dict["structural_health"].setdefault("tool_result_truncations", 0)
```

### Startup Reachability Check for Port Providers
```python
# orchestrator.py __init__ — after reading port env vars
if planner_port:
    planner_url = f"http://127.0.0.1:{planner_port}/v1"
    if _detect_llama_cpp_model(planner_url) is None:
        self.logger.warning(
            "LLAMA_CPP_PLANNER_PORT=%s server unreachable — falling back to default server",
            planner_port,
        )
        self._planner_provider = self.provider  # fallback
    else:
        self._planner_provider = self.provider.with_port(int(planner_port))
else:
    self._planner_provider = self.provider
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `graph.py` as monolith (~1700 lines at Phase 1, now 3280) | Decompose into node files + shim | Phase 8 | Maintainability, 600-line ceiling |
| Single llama-server for all roles | Distinct servers per role via port env vars | Phase 8 | Enables model specialization (small/fast executor, large/accurate planner) |
| Raw large results injected into planner window | Store in Postgres, inject compact pointer | Phase 8 | Prevents context overflow on large payloads |
| `with_alias()` for model routing | Add `with_port()` for server routing | Phase 8 | Two factory methods compose: `provider.with_alias("planner").with_port(8081)` |

**Existing infrastructure this phase extends:**
- `with_alias()` at provider.py:568 — direct template for `with_port()`
- `ArtifactStore` at storage/artifact_store.py — direct template for `ToolResultCache`
- `_detect_llama_cpp_model()` at provider.py:470 — reused for startup health check
- `build_planner_context_injection()` at context_manager.py:752 — the injection interception point
- `db/migrations/001-005` convention — migration 006 follows the same sorted-apply pattern

---

## Open Questions

1. **Where does `_planner_provider` get used in `_plan_next_action()`?**
   - What we know: `_generate_with_hard_timeout()` at graph.py:1933 is the call site; it currently uses `self.provider` (or the fallback).
   - What's unclear: Does `_generate_with_hard_timeout()` need a `provider` parameter, or should `self._planner_provider` be the new default for that call?
   - Recommendation: Add a `provider: ChatProvider | None = None` parameter to `_generate_with_hard_timeout()`; planner node calls it with `self._planner_provider`, executor calls with `self._executor_provider`. This is the minimal surgical change.

2. **Does `tool_history` hold `args` reliably for all tools?**
   - What we know: `tool_history` has `call`, `tool`, `args`, `result` (per MEMORY.md). Args are present for hashing.
   - What's unclear: Whether any tool execution path omits args from the record.
   - Recommendation: In `ToolResultCache.store()`, hash `tool_name + args` but also defensively handle `args = {}` (produces a valid, stable hash).

3. **How large can the `_plan_next_action` helpers realistically be split?**
   - What we know: The method is 1078 lines. Helpers include prompt building, context injection calls, retry loops, token budget enforcement, and response parsing.
   - What's unclear: Whether some sub-helpers (e.g., `_build_system_prompt`, already a standalone method) have already been extracted.
   - Recommendation: Profile the method line-by-line before writing the plan. The planner's `_build_system_prompt()` (already extracted to a method) shows the pattern — more methods can follow.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| Quick run command | `pytest tests/unit/ -q -x` |
| Full suite command | `pytest tests/ -q` |
| Coverage command | `pytest tests/ --cov=src --cov-report=term-missing --cov-fail-under=80` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SYCL-01 | `with_port(9090)` returns new provider pointing to port 9090; `generate()` hits new URL | unit | `pytest tests/unit/test_provider.py -x -k port` | ❌ Wave 0 |
| SYCL-01 | Orchestrator reads `LLAMA_CPP_PLANNER_PORT` + `LLAMA_CPP_EXECUTOR_PORT` at init | unit | `pytest tests/unit/test_graph_orchestrator_wiring.py -x -k port` | ❌ Wave 0 |
| SYCL-01 | Unreachable port → warning + fallback to default server (no hard fail) | unit | `pytest tests/unit/test_graph_orchestrator_wiring.py -x -k fallback` | ❌ Wave 0 |
| SYCL-02 | All 823+ existing tests pass after graph.py decomposition | regression | `pytest tests/ -q` | ✅ (existing suite) |
| SYCL-02 | `from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator` resolves | smoke | `pytest tests/unit/test_graph_orchestrator_wiring.py -x` | ✅ |
| BTLNK-01 | Mission with output >threshold never delivers >cap chars to planner | integration | `pytest tests/integration/test_context_overflow.py -x` | ❌ Wave 0 |
| BTLNK-02 | Large result stored in DB; injected text ≤ cap; full result retrievable via `get()` | unit | `pytest tests/unit/test_tool_result_cache.py -x` | ❌ Wave 0 |
| BTLNK-02 | `structural_health["tool_result_truncations"]` increments on overflow | unit | `pytest tests/unit/test_tool_result_cache.py -x -k truncation` | ❌ Wave 0 |
| BTLNK-02 | `ToolResultCache(pool=None)` is safe no-op (CI compatibility) | unit | `pytest tests/unit/test_tool_result_cache.py -x -k pool_none` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/unit/ -q -x`
- **Per wave merge:** `pytest tests/ -q`
- **Phase gate:** Full suite green (823+ tests) before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_provider_port.py` — unit tests for `with_port()` factory
- [ ] `tests/unit/test_tool_result_cache.py` — unit tests for `ToolResultCache` (store, get, TTL eviction, pool=None)
- [ ] `tests/integration/test_context_overflow.py` — integration test: synthetic large result → planner never sees >cap chars
- [ ] Wave 0 stubs should use `NotImplementedError` (not `pytest.skip`) per project convention (Phase 7.6-00 decision)

---

## Sources

### Primary (HIGH confidence)
- Direct code inspection: `src/agentic_workflows/orchestration/langgraph/provider.py` — `with_alias()` at line 568, `_detect_llama_cpp_model()` at line 470, `LlamaCppChatProvider.__init__` at line 520
- Direct code inspection: `src/agentic_workflows/orchestration/langgraph/graph.py` — node method line ranges, private symbol list, 3280-line count
- Direct code inspection: `src/agentic_workflows/orchestration/langgraph/context_manager.py` — `build_planner_context_injection()` at line 752, ContextManager init at line 245
- Direct code inspection: `src/agentic_workflows/storage/artifact_store.py` — pool-injection pattern, SHA-256 key, pool=None no-op
- Direct code inspection: `db/migrations/001-005` — migration file naming convention and SQL patterns
- Direct grep: all test files importing from `graph.py` — complete private symbol list confirmed

### Secondary (MEDIUM confidence)
- `urllib.parse` for port URL construction — Python 3.12 stdlib, documented behavior
- psycopg3 `ON CONFLICT DO UPDATE` — same pattern already in `ArtifactStore.upsert()` (verified in codebase)

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- SYCL provider routing (SYCL-01): HIGH — `with_alias()` is the direct template; verified in codebase
- graph.py decomposition (SYCL-02): HIGH — all import paths verified by grep; re-export shim pattern exists; line counts measured
- ToolResultCache (BTLNK-02): HIGH — ArtifactStore is the direct template; migration convention verified
- ContextManager interception (BTLNK-01): HIGH — `build_planner_context_injection()` inspected; `tool_history` structure confirmed from MEMORY.md
- `_plan_next_action` split feasibility: MEDIUM — known to be 1078 lines; exact split boundaries require file read at plan time
- Migration number (006 not 005): HIGH — `005_sub_task_cursors.sql` confirmed to exist

**Research date:** 2026-03-11
**Valid until:** 2026-04-11 (stable codebase, no fast-moving dependencies)
