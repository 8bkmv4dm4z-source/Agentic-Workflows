# Walkthrough: Phase 7.9 -- Dynamic Context Querying, Memory Consolidation, Compliance Observability

Phase 7.9 adds three production capabilities to the orchestration platform:
dynamic cross-run context querying via a new tool, memory consolidation to
prevent unbounded table growth, and schema compliance observability through
Langfuse metrics and the CLI audit dashboard.

## Overview

| Capability | Module | Purpose |
|------------|--------|---------|
| query_context tool | `tools/query_context.py` | Let the LLM search past missions by semantic similarity |
| Memory consolidation | `storage/memory_consolidation.py` | Merge old episodic missions into consolidated summaries |
| Schema compliance | `observability.py`, `run_audit.py` | Track first-attempt parse success rate per run |

All three features follow the project's graceful degradation pattern: they
activate only when their backing infrastructure (Postgres + pgvector, Langfuse,
or SQLite checkpoints) is available.

---

## query_context Tool

### What It Does

`QueryContextTool` wraps `MissionContextStore.query_cascade()` from Phase 7.3,
exposing the 5-layer cascade search (L0 exact, L1 BIT hamming, L2 vector,
L3 tool-pattern, L4 keyword) as a tool the LLM can invoke mid-plan.

When a mission mentions "recall", "prior", "remember", or "previous", the
keyword map in `mission_parser.py` routes the planner toward `query_context`.

### How It Works

```python
class QueryContextTool(Tool):
    def execute(self, args):
        query = args["query"]
        embedding = self.embedding_provider.embed([query])[0] if self.embedding_provider else None
        hits = self.store.query_cascade(goal=query, top_k=max_results, embedding=embedding)
        return {"results": [...], "count": len(results)}
```

Key design choices:

- **Conditional registration:** `build_tool_registry()` only registers
  `query_context` when a `mission_context_store` is provided. Without Postgres,
  the tool simply does not appear in the planner's tool list.
- **max_results clamped to 10:** Prevents the LLM from requesting unbounded
  result sets that would blow up the context window.
- **TOOL_BITS["query_context"] = 37:** Follows the append-only bitmask policy
  established in Phase 7.3 (next after `retrieve_run_context` at 36).

### Keyword Map Integration

Four entries were added to `_TOOL_KEYWORD_MAP` in `mission_parser.py`:

| Keyword | Maps To |
|---------|---------|
| prior | query_context |
| recall | query_context |
| remember | query_context |
| previous | query_context (appended to existing retrieve_run_context) |

The "previous" keyword uses non-destructive append to preserve backward
compatibility with the existing `retrieve_run_context` mapping.

### Supervisor Few-Shot

Example 4 was added to `supervisor.md`, showing a `query_context -> sort_array`
workflow that demonstrates how the tool feeds cross-run context into downstream
actions.

---

## Memory Consolidation

### Problem

The `mission_contexts` table grows with every completed mission. Over time,
hundreds of semantically similar entries (e.g., repeated file-processing
missions) accumulate and slow down cascade queries.

### Solution: Greedy Single-Linkage Clustering

`consolidate_memories()` in `storage/memory_consolidation.py`:

1. **Fetch** all completed missions older than `age_days` (default 7)
2. **Cluster** by cosine similarity using union-find with path compression
3. **Merge** each multi-member cluster into a single consolidated summary
4. **Transactional DELETE + INSERT** replaces original rows with one merged row

The similarity threshold defaults to 0.85, which groups only truly redundant
missions while preserving distinct operational patterns.

### Cosine Similarity (Pure Python)

```python
def _cosine_similarity(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (mag_a * mag_b) if mag_a and mag_b else 0.0
```

No numpy dependency -- the embedding dimension is 384 (BAAI/bge-small-en-v1.5),
so pure Python is fast enough and avoids adding a heavy C extension to the
production dependency tree.

### Union-Find Clustering

The algorithm uses union-find with path compression for O(n * alpha(n))
amortized per union/find operation:

```python
def _find(i):
    while cluster_ids[i] != i:
        cluster_ids[i] = cluster_ids[cluster_ids[i]]  # path compression
        i = cluster_ids[i]
    return i
```

Overall complexity is O(n^2) for the pairwise comparison loop, which is
acceptable because consolidation runs as a batch job on old data, not in the
hot path.

### Summary Merging

Merged summaries combine goals from all cluster members, union their tools_used
sets, and truncate to 500 characters to prevent unbounded growth. When an
embedding_provider is available, the merged summary gets a fresh embedding;
otherwise, the cluster embeddings are averaged.

### CLI Usage

```bash
python -m agentic_workflows.orchestration.langgraph.run_audit --consolidate
```

This requires `DATABASE_URL` to be set (Postgres only). The `--consolidate`
flag triggers an early-exit branch in `main()` that runs consolidation and
returns before the normal summary flow.

---

## Schema Compliance Observability

### Langfuse Score Reporting

`report_schema_compliance()` in `observability.py` fires after every LLM parse
attempt in `graph.py._plan_next_action()`:

- **value=1.0** when the LLM produced valid JSON on the first attempt
- **value=0.0** when fallback parsing was required

Three call sites in `graph.py`:
1. Main parse path (after `_parse_all_actions_json`)
2. Cloud fallback path (after cloud provider output parsing)
3. Context overflow retry path (after compaction + retry)

Each reports the active specialist role and run_id, with `session_id` mapping
to enable cross-run Langfuse grouping.

All calls use `contextlib.suppress(Exception)` for fire-and-forget behavior --
a Langfuse outage never affects orchestration.

### Cross-Run Dashboard Columns

Phase 7.9 Plan 04 added four new columns to the `run_audit.py` CLI dashboard:

| Column | Source | Description |
|--------|--------|-------------|
| compliance | computed | `(steps - fallbacks - fmt_retries) / steps` as percentage |
| fallbacks | structural_health.json_parse_fallback | Fallback parser invocations |
| fmt_retry | structural_health.format_retries | Format correction retries |
| cloud_fb | structural_health.cloud_fallback_count | Cloud fallback triggers |

The `RunSummary` dataclass gained four fields:
- `schema_compliance_rate: float` (default 1.0)
- `json_parse_fallbacks: int` (default 0)
- `format_retries: int` (default 0)
- `cloud_fallback_count: int` (default 0)

Compliance rate is computed in `summarize_runs()` from the `structural_health`
dict stored in checkpointed run state:

```python
sh = dict(state.get("structural_health", {}))
fallbacks = int(sh.get("json_parse_fallback", 0))
fmt_retries = int(sh.get("format_retries", 0))
first_success = max(0, step_count - fallbacks - fmt_retries)
compliance_rate = first_success / max(1, step_count)
```

When `structural_health` is absent (pre-7.6 runs), compliance defaults to 1.0.

---

## Architecture Decisions

| Decision | Rationale |
|----------|-----------|
| Pure Python cosine (no numpy) | 384-dim vectors; avoids heavy C extension in production deps |
| Greedy single-linkage (no sklearn) | Simple, deterministic, adequate for batch consolidation |
| Langfuse scores (not custom DB) | Reuses existing observability stack; cross-run grouping via session_id |
| run_audit.py for --consolidate | Batch operation fits audit CLI pattern; keeps run.py focused on execution |
| Conditional tool registration | query_context only appears when Postgres + MissionContextStore is available |
| Union-find with path compression | O(n * alpha(n)) amortized -- efficient for greedy clustering |

---

## Testing Strategy

### Unit Tests

| Module | Tests | Coverage |
|--------|-------|----------|
| `test_query_context.py` | 10 | Tool behavior, registry registration, max_results clamping |
| `test_keyword_map_query_context.py` | 5 | Keyword map entries, directive few-shot presence |
| `test_memory_consolidation.py` | 14 | Cosine similarity, clustering, merging, edge cases |
| `test_schema_compliance.py` | 7 | Langfuse score creation, wiring, graceful degradation |
| `test_run_audit_compliance.py` | 4 | RunSummary fields, compliance computation, table output |

### Integration Tests

- `test_memory_consolidation_pg.py`: Postgres integration confirming row
  reduction after consolidation (requires `DATABASE_URL` + pg_pool fixture).

### Regression Verification

Full test suite (`pytest tests/ -q`) run at end of each plan to confirm SC-6:
all existing tests pass unchanged. Pre-existing `test_action_queue` failure
noted but not caused by Phase 7.9 changes.

---

## File Index

| File | Role |
|------|------|
| `src/agentic_workflows/tools/query_context.py` | QueryContextTool wrapping cascade search |
| `src/agentic_workflows/storage/memory_consolidation.py` | Clustering + consolidation logic |
| `src/agentic_workflows/observability.py` | report_schema_compliance() Langfuse metric |
| `src/agentic_workflows/orchestration/langgraph/run_audit.py` | --consolidate CLI + compliance dashboard columns |
| `src/agentic_workflows/orchestration/langgraph/graph.py` | 3 compliance reporting call sites |
| `src/agentic_workflows/orchestration/langgraph/mission_parser.py` | Keyword map entries for query_context |
| `src/agentic_workflows/orchestration/langgraph/tools_registry.py` | Conditional query_context registration |
| `src/agentic_workflows/directives/supervisor.md` | Example 4 few-shot for query_context |
