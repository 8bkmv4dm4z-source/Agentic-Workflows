# Phase 7.3 Walkthrough: Hybrid Deterministic + Semantic Context System

Phase 7.3 adds persistent cross-run mission context to the agent system. When a mission
completes, its goal, tools used, and summary are persisted to Postgres. On the next run,
the planner can see similar past missions and avoid re-discovering what worked. This
walkthrough explains every architectural decision in the system -- why hybrid retrieval
beats pure vector search, why fastembed beats sentence-transformers, how the 5-layer
cascade is structured, and what makes the RRF fusion formula so reliable.

---

## What Changed

### Files Created

| File | Purpose |
|------|---------|
| `src/agentic_workflows/context/__init__.py` | New context package (embedding stack) |
| `src/agentic_workflows/context/embedding_provider.py` | EmbeddingProvider Protocol, MockEmbeddingProvider, FastEmbedProvider, get_embedding_provider() |
| `src/agentic_workflows/storage/mission_context_store.py` | MissionContextStore with 5-layer cascade, RRF, TOOL_BITS, encode_tool_pattern |
| `src/agentic_workflows/storage/artifact_store.py` | ArtifactStore for cross-run artifact key/value persistence |
| `db/migrations/003_mission_contexts.sql` | mission_contexts table + BIT(384) + vector(384) HNSW index |
| `db/migrations/004_mission_artifacts.sql` | mission_artifacts table + indexes |
| `docker/docker-compose.stress.yml` | 3 API replicas + pgBouncer + nginx L7 load balancer |
| `scripts/stress_test.py` | asyncio concurrent /run load test |
| `docs/WALKTHROUGH_PHASE7.3.md` | This file |

### Files Modified

| File | Change |
|------|--------|
| `db/migrations/002_foundation.sql` | `vector(1536)` → `vector(384)` in file_chunks and solved_tasks |
| `src/agentic_workflows/orchestration/langgraph/context_manager.py` | Optional `mission_context_store` + `embedding_provider` params; `_persist_mission_context()`; cross-run cascade injection in `build_planner_context_injection()` |
| `src/agentic_workflows/orchestration/langgraph/graph.py` | Optional `embedding_provider` + `mission_context_store` params passed through to ContextManager |
| `pyproject.toml` | `[context]` optional dep group with `fastembed>=0.3` |
| `tests/conftest.py` | `clean_pg` fixture extended with `mission_contexts`/`mission_artifacts` tables |

### What This Phase Does NOT Do

This boundary matters because scoping violations cause the biggest delivery delays.

- **graph.py decomposition** — The orchestrator is still a 1700-line monolith. That is
  a Phase 7.4 concern. Phase 7.3 is additive, not structural.
- **LangGraph Send() parallel execution** — Missions still run sequentially. Phase 7.5.
- **LLM-generated summaries** — Summaries are built deterministically from structured
  data. LLM-based summarization is deferred to post-7.3 stabilization.
- **Cross-encoder reranking** — No L5 reranker yet. Pure RRF is sufficient for now.
- **Kubernetes / cloud deploy** — Out of scope for this project milestone.

---

## Why Hybrid Retrieval?

### The Problem with Pure Vector Search

If you search "compute fibonacci(50) and write to fib50.txt", a pure vector search might
return results about computing pi, writing JSON files, or other numerical file-writing
tasks. The embedding model learned that these goals are *semantically similar*, which
is exactly the wrong behavior when you need an exact cache hit.

Three failure modes plague pure vector search alone:

1. **False positives from semantic proximity.** "Sort an array of integers" and "rank
   a list of items by score" have similar embeddings even though they use different
   tools and produce different outputs.

2. **False negatives on exact matches.** If the exact same goal was executed before, a
   hash lookup is both more accurate and 1000x faster than a vector scan.

3. **No tool structure awareness.** Two missions might have identical goals but one was
   executed with `data_analysis` + `sort_array` while the other used `math_stats`.
   The vector embedding captures the goal text, not the execution path.

### The Industry Pattern

Zep (memory layer), Haystack (RAG framework), Hindsight MCP, and Cognee all converged
on the same pattern independently: run deterministic filters first, fall back to semantic
search for things that slip through. This is not a novel insight -- it is the established
engineering consensus as of 2024.

The +15-30% recall improvement over single-list approaches comes from two sources:
deterministic layers capturing exact matches that confuse embeddings, and RRF fusion
combining BM25 and cosine signals into a single ranking that exploits their different
failure modes.

### Why This Architecture Now

Phase 7 gave us Postgres with pgvector already enabled. Phase 7.1 gave us ContextManager
with structured mission tracking. Phase 7.3 wires these together into a persistence layer
that survives process restarts and is shared across horizontal replicas. The underlying
infrastructure was already there; Phase 7.3 is the application layer on top of it.

---

## The 5-Layer Cascade (L0-L4)

The cascade is a short-circuit pipeline. Each layer runs only if the previous layer did
not return enough results. L0 and L1 are exact-match layers that can short-circuit the
entire pipeline. L2 and L4 are approximate layers whose results are fused together.

```
query goal
    │
    ▼
L0: SHA-256 exact hash match ──── HIT ──→ return immediately (score=1.0)
    │ MISS
    ▼
L1: tool bitmask structural match ─ ≥ top_k ──→ return immediately (score=0.9)
    │ < top_k
    ▼
L2: tsvector BM25 keyword search ──→ up to 20 candidates (ranked by ts_rank)
    │
L4: pgvector HNSW cosine ──────────→ up to 20 candidates (ranked by cosine distance)
    │
    ▼
  RRF fusion ──→ top-k results returned to caller
```

### L0: SHA-256 Exact Hash

The goal text is lowercased, stripped, and SHA-256-hashed before storage. The hash is
stored in a `goal_hash` column with a B-tree index. On query, the same normalization
happens and the hash is looked up first.

This is the fastest possible retrieval: one index lookup, zero Postgres work beyond
that. It short-circuits all downstream layers. If the exact same goal was run before,
you get the result instantly.

```sql
SELECT id, run_id, mission_id, goal, summary, tools_used
FROM mission_contexts
WHERE goal_hash = %s AND status = 'completed'
LIMIT 1;
```

Why normalize before hashing? "Compute fibonacci(50)" and "compute fibonacci(50) " (with
trailing space) should be the same cache key. Lowercase + strip achieves this without
any language-specific preprocessing.

### L1: Tool Bitmask

Each tool name in the system is assigned a fixed bit position in a 64-bit integer (fits
in Postgres `BIGINT`). The list of tools used in a mission is encoded into a bitmask at
write time and stored in the `tool_pattern` column.

A query with `tools_used=["write_file", "math_stats"]` encodes to bitmask `0b10011`
(bits 3 and 4 set). The L1 query finds missions whose tool_pattern includes ALL of those
bits:

```sql
WHERE (tool_pattern & %s) = %s AND status = 'completed'
ORDER BY created_at DESC LIMIT %s
```

This is a structural match: missions that used the same tools (or a superset of them)
are ranked above missions that used completely different tools. It short-circuits to L2-L4
only if there are fewer than `top_k` bitmask matches.

The bitmask fits in 64 bits because the system has 37 tools (36 always-present + 1
conditional). New tools are appended at higher bit positions to preserve existing
bitmask encodings -- this is an append-only registry.

### L2: BM25 Full-Text (tsvector)

Postgres has a first-class full-text search engine. The `goal` text is converted to a
`tsvector` at write time and stored in a `goal_tsvector` column with a GIN index.

At query time, `plainto_tsquery('english', goal)` converts the query text into a tsquery,
and `ts_rank()` produces a BM25-like relevance score. This catches keyword matches that
embeddings sometimes confuse:

```sql
SELECT id, ..., ts_rank(goal_tsvector, plainto_tsquery('english', %s)) AS rank
FROM mission_contexts
WHERE goal_tsvector @@ plainto_tsquery('english', %s)
  AND status = 'completed'
ORDER BY rank DESC LIMIT 20;
```

BM25 is deterministic and indexed -- it never requires a full table scan, and its results
are reproducible given the same text. This makes it reliable as the first approximate
layer.

### L3: Binary Hamming (merged with L4)

Binary quantization converts the 384-dimensional float32 embedding to a string of 384
`'0'` and `'1'` characters using the sign bit of each dimension:

```python
def _float_vec_to_bit_string(vec: list[float]) -> str:
    return "".join("1" if v >= 0.0 else "0" for v in vec)
```

This BIT(384) representation is stored in the `embedding_bin` column. Hamming distance
over binary vectors is 32x smaller (384 bits vs 384 float32 values = 1536 bytes) and
10x faster than cosine distance.

The recall cost is only 0.3% -- sign-bit quantization preserves the angular geometry of
the original vector space with minimal loss. In practice, this means L3 can serve as a
fast pre-filter or can be merged into the L4 pipeline. In this implementation, L3 is
merged with L4 to simplify the query path. The `embedding_bin` column exists for future
standalone use.

### L4: pgvector HNSW Cosine

The full float32 embedding is stored in a `vector(384)` column with an HNSW
(Hierarchical Navigable Small World) index:

```sql
CREATE INDEX ON mission_contexts USING hnsw (embedding vector_cosine_ops);
```

The `<=>` operator in pgvector computes cosine distance (lower = more similar):

```sql
SELECT id, ..., 1 - (embedding <=> %s::vector) AS score
FROM mission_contexts
WHERE status = 'completed'
ORDER BY embedding <=> %s::vector LIMIT 20;
```

The HNSW index enables approximate nearest-neighbor search without scanning the full
table -- O(log N) instead of O(N). For collections under 1 million rows, HNSW provides
better recall than IVFFlat without any training phase.

### RRF Fusion

The L2 and L4 results are two ranked lists of mission IDs. Reciprocal Rank Fusion
combines them into a single ranked list that exploits the different failure modes of
keyword and semantic search.

---

## Embedding Stack

### fastembed vs sentence-transformers

The first decision in any local embedding system is the library. The two main choices are
`fastembed` (Qdrant's library) and `sentence-transformers` (Hugging Face's library).

| Dimension | fastembed | sentence-transformers |
|-----------|-----------|----------------------|
| Runtime | ONNX (no PyTorch) | PyTorch required |
| Install size | ~80MB | ~1.5GB (with PyTorch) |
| Startup time | ~2s (ONNX JIT) | ~8s (PyTorch init) |
| Maintenance | Qdrant (active) | Hugging Face (active) |
| CI-friendliness | High (small, fast) | Low (PyTorch bloats CI) |

The decision is `fastembed`. No PyTorch dependency means no 1.5GB install, no CUDA
driver complexity, no GPU requirement. The ONNX runtime is CPU-native and produces
identical results across platforms.

### BAAI/bge-small-en-v1.5

The model is `BAAI/bge-small-en-v1.5`: 384 dimensions, ~24MB download, trained by
Beijing Academy of Artificial Intelligence. It scores at the top of its size class on
the MTEB (Massive Text Embedding Benchmark) for retrieval tasks. At 384 dimensions it
balances accuracy vs storage: 4 bytes × 384 = 1.5KB per vector, which is manageable
even with millions of rows.

The model is downloaded on first use and cached locally (`~/.cache/huggingface/` by
default). CI uses `MockEmbeddingProvider` so no download ever happens in CI.

### MockEmbeddingProvider

The mock provider is the key to keeping CI fast and dependency-free. It uses SHA-256
of the input text as a random number generator seed, producing a deterministic
384-dimensional unit-norm vector with no model download:

```python
class MockEmbeddingProvider:
    dimensions: int = 384

    def embed_sync(self, text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest(), "big")
        rng = random.Random(seed)
        vec = [rng.gauss(0, 1) for _ in range(self.dimensions)]
        norm = sum(v * v for v in vec) ** 0.5
        return [v / norm for v in vec] if norm > 0 else vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_sync(t) for t in texts]
```

The unit-norm normalization ensures the vectors are on the unit sphere, which is the
correct input format for cosine similarity (pgvector's `<=>` operator expects this).

"Same text always returns the same vector" is the critical property. Tests can call
`embed_sync()` twice and assert equality without any model or network dependency.

### EMBEDDING_PROVIDER Env Var

```python
# EMBEDDING_PROVIDER=mock (default) -> MockEmbeddingProvider
# EMBEDDING_PROVIDER=fastembed     -> FastEmbedProvider

provider = get_embedding_provider()
embedding = provider.embed_sync("compute fibonacci(50)")
```

The factory function reads `EMBEDDING_PROVIDER` at call time (not at module import
time), so switching providers requires only an environment variable change, not a code
change. CI leaves the variable unset, getting `mock` by default. Production sets
`EMBEDDING_PROVIDER=fastembed`.

### EmbeddingProvider Protocol

The `EmbeddingProvider` is defined as a `typing.Protocol`, consistent with the project's
structural subtyping approach (established in Phase 6 with RunStore):

```python
@runtime_checkable
class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def embed_sync(self, text: str) -> list[float]: ...
    @property
    def dimensions(self) -> int: ...
```

Neither `MockEmbeddingProvider` nor `FastEmbedProvider` inherits from this Protocol.
They satisfy it structurally -- by having the right method signatures. This means any
future provider (e.g., OpenAI embeddings) can be dropped in without modifying the
Protocol or any of the code that accepts `EmbeddingProvider`.

---

## Reciprocal Rank Fusion

### What It Is

Reciprocal Rank Fusion (Cormack et al., 2009) is a rank aggregation method for combining
multiple ranked lists into a single consensus ranking. The formula is simple:

```
score(d) = Σ  1 / (k + rank(d, list) + 1)
          lists
```

Where `k=60` is a damping parameter that prevents very high-ranked documents from
dominating the score. The rank is 0-indexed (first item = rank 0).

```python
def reciprocal_rank_fusion(*ranked_lists: list[str], k: int = 60) -> dict[str, float]:
    """Fuse multiple ranked lists via RRF (Cormack et al., 2009).

    Score for document d = sum(1 / (k + rank + 1)) across all input lists.
    Higher score = more relevant. k=60 is the standard parameter.
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return dict(sorted(scores.items(), key=lambda x: x[1], reverse=True))
```

### Why k=60

The k parameter controls the contribution of rank-1 documents. With k=60:
- Rank 0 (first): 1/(60+0+1) = 0.0164
- Rank 1 (second): 1/(60+1+1) = 0.0161
- Rank 10 (eleventh): 1/(60+10+1) = 0.0141

The scores decrease slowly, meaning a document at rank 10 still contributes meaningfully.
Smaller k values make top-ranked documents dominate; larger k values flatten the curve.

k=60 is the value from the original 2009 paper and is used unchanged in production
systems (Elasticsearch, Weaviate, Pinecone all use k=60 as their default). It requires
no tuning and is proven robust across a wide range of document collections.

### Why No Tunable Weights

A natural impulse is to weight BM25 results more heavily than cosine results (or vice
versa) based on the query type. In practice, tunable weights consistently underperform
RRF with no weights. The explanation from the literature: keyword and semantic search
fail on different queries, and the ranking signals they produce are already calibrated
within their respective methods. Adding a weight just introduces a tuning parameter
that needs validation data to set correctly -- and that validation data rarely exists in
production.

RRF avoids this by treating rank position as the only signal, ignoring the raw scores
from each method entirely. A document ranked first by BM25 (ts_rank=0.9) gets the same
RRF contribution as a document ranked first by cosine similarity (score=0.97). The
methods' internal scores are incommensurable anyway -- you cannot meaningfully compare
a BM25 ts_rank to a cosine similarity score.

---

## BIT(384) Binary Quantization

### Why Binary Quantization

Float32 vectors are the standard output from embedding models. They are also expensive:
384 dimensions × 4 bytes = 1.5KB per vector. Binary quantization converts each float
to a single bit (sign bit), producing a 384-bit = 48-byte representation.

| Metric | float32 vector(384) | BIT(384) binary |
|--------|---------------------|-----------------|
| Storage | 1,536 bytes | 48 bytes |
| Size ratio | 1x | 32x smaller |
| Distance op | Cosine (float multiply) | Hamming (XOR + popcount) |
| Speed | 1x | ~10x faster |
| Recall loss | 0% | ~0.3% |

The 0.3% recall loss is essentially free -- it comes from rounding each float to the
sign of its dimension. Because the angular structure of the embedding space is mostly
preserved, the nearest neighbors in BIT space are almost always the same as in float32
space.

### The Conversion

```python
def _float_vec_to_bit_string(vec: list[float]) -> str:
    """Convert a float vector to a BIT(N) binary string for Postgres.

    Sign bit encoding: 1 if v >= 0.0 else 0.
    Result is a string of '0' and '1' characters (e.g., '01101...').
    """
    return "".join("1" if v >= 0.0 else "0" for v in vec)
```

This produces a 384-character string like `'01101010...'`. This is the exact format
Postgres expects for the `BIT(384)` column type. The key pitfall: do not pass Python
`bytes` or an integer -- Postgres expects the binary literal string representation.

### How It Is Stored

The `mission_contexts` table has two embedding columns:
- `embedding_bin BIT(384)` -- the binary quantization for fast Hamming search
- `embedding vector(384)` -- the full float32 for cosine HNSW search

At write time, both columns are populated from the same `list[float]`:

```python
embedding_bin = _float_vec_to_bit_string(embedding)
embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"
# embedding_str is passed as %s::vector to Postgres
```

---

## HNSW vs IVFFlat

pgvector supports two approximate nearest-neighbor index types. The choice matters for
recall, build time, and query latency.

### IVFFlat

IVFFlat (Inverted File Index with Flat Quantization) partitions the vector space into
`nlist` clusters using k-means. At query time, it searches the nearest clusters plus
`nprobe` additional ones. The accuracy depends on how well the training clusters match
the query distribution.

The problem for this project: IVFFlat requires a training phase on existing data.
`CREATE INDEX` runs k-means clustering on the current table contents. If the table is
empty (as it is when migrations run), the index is created on zero data, which is
meaningless. You would need to re-create the index after data is loaded -- but then
migration is not idempotent.

### HNSW

HNSW (Hierarchical Navigable Small World) builds a multi-layer proximity graph. Each
new vector is inserted by finding its approximate nearest neighbors in the graph and
adding edges. This means the index builds incrementally as data is inserted -- no
separate training phase.

For collections under 1 million rows, HNSW provides better recall than IVFFlat at
comparable query latency. The index builds slightly slower than IVFFlat (O(N log N) vs
O(N × nlist)), but since our migration runs on an empty table, the initial build cost
is zero.

The migration creates the HNSW index on an empty table:

```sql
CREATE INDEX ON mission_contexts USING hnsw (embedding vector_cosine_ops);
```

After data is inserted, the index is automatically maintained by pgvector. No manual
REINDEX is needed for normal insert volumes.

**Decision:** HNSW. No training phase, better accuracy for this data scale, correct
behavior when index is created on an empty table.

---

## Tool Bitmask Registry

### TOOL_BITS: The Canonical Registry

Every tool in the system is assigned a fixed bit position in a 64-bit integer. The
registry is an ordered dict with 37 entries:

```python
TOOL_BITS: dict[str, int] = {
    "repeat_message": 0,
    "sort_array": 1,
    "string_ops": 2,
    "math_stats": 3,
    "write_file": 4,
    "memoize": 5,
    "retrieve_memo": 6,
    "task_list_parser": 7,
    "text_analysis": 8,
    "data_analysis": 9,
    "json_parser": 10,
    "regex_matcher": 11,
    "outline_code": 12,
    "read_file_chunk": 13,
    "describe_db_schema": 14,
    "read_file": 15,
    "run_bash": 16,
    "http_request": 17,
    "datetime_ops": 18,
    "extract_table": 19,
    "fill_template": 20,
    "hash_content": 21,
    "query_db": 22,
    "recognize_pattern": 23,
    "clear_context": 24,
    "update_file_section": 25,
    "list_directory": 26,
    "search_files": 27,
    "search_content": 28,
    "summarize_text": 29,
    "compare_texts": 30,
    "classify_intent": 31,
    "format_converter": 32,
    "file_manager": 33,
    "encode_decode": 34,
    "validate_data": 35,
    # Conditional tool -- appended last to preserve existing bitmasks
    "retrieve_run_context": 36,
}
```

37 tools use bits 0-36. The maximum value is `2^37 - 1 ≈ 1.37 × 10^11`, which fits
comfortably in a Postgres `BIGINT` (signed 64-bit, max 2^63 - 1).

### Append-Only Policy

The bit position of each tool is permanent. If `write_file` is bit 4, it stays at bit
4 forever. New tools are always appended at the next available bit position.

If you reassigned bit positions, all existing `tool_pattern` values in the database
would become invalid -- a mission that used `write_file` would no longer match bitmask
queries for `write_file`. The append-only policy prevents this silent data corruption.

### encode_tool_pattern

```python
def encode_tool_pattern(tools_used: list[str]) -> int:
    """Encode a list of tool names into a 64-bit integer bitmask.

    Unknown tool names are silently ignored (forward-compat with new tools).
    The bitmask fits in a Postgres BIGINT column (signed 64-bit, max bit 36 used).
    """
    result = 0
    for tool in tools_used:
        bit = TOOL_BITS.get(tool)
        if bit is not None:
            result |= 1 << bit
    return result
```

Unknown tools are silently ignored. This provides forward-compatibility: if a new
tool name appears in the data before the registry is updated, it is excluded from the
bitmask rather than causing an error.

---

## ContextManager Integration

### Design Goal: Backward Compatibility

The ContextManager is used with zero arguments in more than 20 places in the codebase.
Adding new behavior must not require any of those callers to change. The solution is
optional parameters with `None` defaults:

```python
def __init__(
    self,
    large_result_threshold: int = 4000,
    sliding_window_cap: int = 20,
    step_threshold: int = 10,
    mission_context_store: MissionContextStore | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> None:
```

When both new parameters are `None` (the default), the ContextManager behaves exactly
as before Phase 7.3. No tests need updating. No callers need updating. The new behavior
activates only when a real store and provider are passed in.

### TYPE_CHECKING Import Guard

The `MissionContextStore` and `EmbeddingProvider` types are needed for type annotations
in `context_manager.py`, but importing them at runtime would add overhead (and potential
circular import issues). The solution is a `TYPE_CHECKING` guard:

```python
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentic_workflows.context.embedding_provider import EmbeddingProvider
    from agentic_workflows.storage.mission_context_store import MissionContextStore
```

These imports are visible to mypy and IDEs for type checking but are never executed at
runtime. This is the same pattern used in `graph.py` for all optional store types.

### _persist_mission_context()

When a mission completes, `on_mission_complete()` calls `_persist_mission_context()` at
the very end. If `mission_context_store` is `None`, it is a no-op:

```python
def _persist_mission_context(self, ctx: MissionContext) -> None:
    """Persist completed mission context to Postgres. No-op if store is None."""
    if self._mission_context_store is None or self._embedding_provider is None:
        return
    try:
        embedding = self._embedding_provider.embed_sync(ctx.goal)
        self._mission_context_store.upsert(
            run_id=...,
            mission_id=str(ctx.mission_id),
            goal=ctx.goal,
            status=ctx.status,
            summary=ctx.summary,
            tools_used=ctx.tools_used,
            key_results=ctx.key_results,
            embedding=embedding,
        )
    except Exception:
        _logger.warning("Failed to persist mission context -- continuing without persistence")
```

The try/except is mandatory. If Postgres is down, if the embedding model fails to load,
if the network is unreachable -- none of these should crash the graph. Cross-run context
persistence is a quality-of-life feature, not a correctness requirement.

### build_planner_context_injection() -- Cross-Run Hits

At the start of each mission, `build_planner_context_injection()` is called to inject
relevant prior context into the planner prompt. Phase 7.3 adds cross-run hits from the
cascade:

```python
# In build_planner_context_injection():
if self._mission_context_store and self._embedding_provider:
    try:
        goal = current_mission.goal if current_mission else ""
        embedding = self._embedding_provider.embed_sync(goal)
        hits = self._mission_context_store.query_cascade(
            goal=goal,
            tools_used=current_mission.tools_used if current_mission else [],
            embedding=embedding,
            top_k=3,
        )
        for hit in hits:
            cross_run_line = f'[Cross-run] Similar: "{hit["goal"]}" -> {hit["summary"]}'
            parts.append(cross_run_line)
    except Exception:
        pass  # graceful degradation
```

The injected lines look like:

```
[Cross-run] Similar: "compute fibonacci(50) and write to fib50.txt" -> Mission 1: ... Tools: math_stats -> write_file | result: 50 numbers computed
```

The 1500-character cap on the full injection prevents context bloat. The
`policy_flags["injected_mission_ids"]` permanent dedup set (established in Phase 7.1)
ensures the same mission is never injected twice in one run.

### Graceful Degradation Contract

Every cross-run operation has exactly one guarantee: it will never crash the graph.

- If `pool=None`, `query_cascade()` returns `[]`
- If Postgres is unreachable, `query_cascade()` catches the exception and returns `[]`
- If embedding fails, `_persist_mission_context()` catches the exception and logs a warning
- If context injection fails, the except block passes silently

This means the new code paths have zero impact on graph reliability. A failure in the
persistence layer is invisible to the orchestrator and the user.

---

## graph.py Wiring

### Optional Params Pattern

`LangGraphOrchestrator.__init__` already uses keyword-only parameters (enforced by `*`
after `self`). Adding new optional params follows the existing pattern:

```python
def __init__(
    self,
    *,
    provider: ChatProvider | None = None,
    # ... existing params ...
    on_specialist_route: Any = None,
    embedding_provider: EmbeddingProvider | None = None,
    mission_context_store: MissionContextStore | None = None,
) -> None:
```

These are then passed to `ContextManager` at construction:

```python
# Before (Phase 7.2):
self.context_manager = ContextManager()

# After (Phase 7.3):
self.context_manager = ContextManager(
    mission_context_store=mission_context_store,
    embedding_provider=embedding_provider,
)
```

The TYPE_CHECKING guard in graph.py (same pattern as context_manager.py) ensures no
runtime import overhead for the new optional type annotations.

---

## Multi-Replica Stress Test

### Architecture

The stress test environment uses a 4-service Docker Compose configuration:

```
[stress_test.py]
       │ HTTP POST /run
       ▼
   [nginx:80] ── L7 load balancer (round-robin)
       │
    ┌──┼──┐
    ▼  ▼  ▼
[api] [api] [api] ── 3 replicas (P1_PROVIDER=scripted, no real LLM cost)
       │
       ▼
  [pgBouncer:6432] ── connection pooler
       │
       ▼
  [postgres:5432] ── pgvector/pgvector:pg16
```

### Why pgBouncer

Each API replica maintains its own `psycopg_pool.ConnectionPool` with `min_size=2,
max_size=10`. With 3 replicas, the maximum simultaneous Postgres connections is
`3 × 10 = 30`. Add the stress test's 10 concurrent HTTP clients and you reach 30-40
active connections.

Default Postgres allows `max_connections=100`, so 30-40 connections is within bounds.
But under sustained load with poor connection hygiene, connection counts can spike.
pgBouncer acts as a connection multiplexer in `transaction` mode: it accepts up to 200
client connections but maintains only 20 actual Postgres connections. Requests that
arrive between transactions share the same physical connection.

pgBouncer `transaction` mode is compatible with the project's `autocommit=True` pool
configuration -- each statement is its own transaction, so pgBouncer can safely
multiplex at the transaction boundary.

### Why nginx, Not docker-compose --scale

When you run `docker compose up --scale api=3`, all 3 replicas try to bind to the same
host port (8000). Only one can succeed. The other two fail with `port already in use`.

The solution is an nginx L7 reverse proxy that binds to host port 8000 and routes
requests to the 3 replicas via Docker's internal DNS:

```nginx
upstream api_backend {
    server api:8000;   # Docker resolves 'api' to all 3 replica IPs (round-robin)
}
```

This is a standard pattern for local multi-replica testing. Docker's internal DNS
automatically load-balances across all containers with the same service name.

### Why P1_PROVIDER=scripted

Running a stress test with a real LLM provider (OpenAI, Groq) costs money and is slow.
The `ScriptedProvider` returns pre-defined responses deterministically, enabling
LLM-free, cost-free load testing that still exercises the full FastAPI → LangGraph →
Postgres code path.

### Running the Stress Test

```bash
# Step 1: Start the multi-replica environment (one-time setup)
docker compose -f docker/docker-compose.stress.yml up --build

# Step 2: In another terminal, run the stress test
python scripts/stress_test.py --url http://localhost:8000 --concurrency 10 --total 50
```

The script sends 50 POST /run requests with 10 in flight at once. It reports:
- Total requests, successes, failures
- Average and p95 response time

Expected output (healthy system):
```
Total: 50  Successes: 50  Failures: 0
Avg: 2.3s  p95: 4.1s
```

The stress test is manual-only. It is not part of the CI matrix because a docker-compose
multi-replica setup with pgBouncer is infeasible in GitHub Actions free tier.

---

## Database Migrations

### Migration 003: mission_contexts

```sql
CREATE TABLE IF NOT EXISTS mission_contexts (
    id             BIGSERIAL PRIMARY KEY,
    run_id         TEXT NOT NULL,
    mission_id     TEXT NOT NULL,
    goal           TEXT NOT NULL,
    goal_hash      TEXT NOT NULL,           -- SHA-256 of normalized goal (for L0)
    tool_pattern   BIGINT NOT NULL DEFAULT 0, -- 64-bit bitmask (for L1)
    goal_tsvector  TSVECTOR,                -- generated from goal (for L2 BM25)
    embedding_bin  BIT(384),               -- binary quantization (for L3 Hamming)
    embedding      VECTOR(384),            -- full float32 (for L4 HNSW cosine)
    status         TEXT NOT NULL DEFAULT 'completed',
    summary        TEXT,
    tools_used     TEXT[],
    key_results    JSONB DEFAULT '{}',
    artifacts      JSONB DEFAULT '[]',
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(run_id, mission_id)
);

-- Indexes for each cascade layer
CREATE INDEX ON mission_contexts (goal_hash);                -- L0
CREATE INDEX ON mission_contexts (tool_pattern);             -- L1
CREATE INDEX ON mission_contexts USING GIN (goal_tsvector); -- L2
CREATE INDEX ON mission_contexts USING hnsw (embedding vector_cosine_ops); -- L4
```

The UNIQUE constraint on `(run_id, mission_id)` enables the `ON CONFLICT DO UPDATE`
upsert pattern. If the same mission is reported twice (e.g., on retry), it updates in
place rather than inserting a duplicate.

### Migration 004: mission_artifacts

```sql
CREATE TABLE IF NOT EXISTS mission_artifacts (
    id          BIGSERIAL PRIMARY KEY,
    run_id      TEXT NOT NULL,
    mission_id  TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    source_tool TEXT,
    key_hash    TEXT NOT NULL,              -- SHA-256 of key for dedup
    embedding   VECTOR(384),               -- embedding of key for semantic lookup
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(run_id, mission_id, key)
);
```

### Migration 002 Update: vector(1536) → vector(384)

The existing `002_foundation.sql` created `file_chunks.embedding vector(1536)` and
`solved_tasks.embedding vector(1536)`. These placeholder tables have never been written
to by any code. The update migrates them safely:

```sql
ALTER TABLE file_chunks
    ALTER COLUMN embedding TYPE vector(384)
    USING NULL::vector(384);

ALTER TABLE solved_tasks
    ALTER COLUMN embedding TYPE vector(384)
    USING NULL::vector(384);
```

The `USING NULL::vector(384)` coercion is safe because the columns are always NULL
(no code has ever written to these tables). This avoids the need to DROP and recreate
the tables, which would fail if Postgres had already run the original 002 migration.

---

## Test Coverage

### Unit Tests (no Postgres required)

Unit tests use `MockEmbeddingProvider` and mock the Postgres pool. They run in under 30
seconds in CI with no external dependencies:

| Test file | Coverage |
|-----------|---------|
| `tests/unit/test_embedding_provider.py` | MockEmbeddingProvider determinism, dimensions, FastEmbedProvider lazy import |
| `tests/unit/test_mission_context_store.py` | encode_tool_pattern, _sha256, pool=None graceful fallback |
| `tests/unit/test_artifact_store.py` | ArtifactStore pool=None graceful fallback |
| `tests/unit/test_rrf_fusion.py` | reciprocal_rank_fusion correctness with known input |

### Integration Tests (Postgres required)

Integration tests use a real Postgres connection from the `pg_pool` fixture. They skip
automatically when `DATABASE_URL` is not set:

```python
pytest.importorskip("psycopg_pool")   # Skip at collection time if psycopg_pool missing
requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set -- skipping Postgres tests",
)

@requires_postgres
@pytest.mark.postgres
class TestMissionContextCascade:
    def test_query_cascade_l0_exact_hit(self, pg_pool, clean_pg): ...
    def test_query_cascade_l4_cosine(self, pg_pool, clean_pg): ...
    def test_cross_run_injection(self, pg_pool, clean_pg): ...
```

### Smoke Test

The smoke test verifies the full cross-run flow end-to-end: two missions with similar
goals are run, and the planner context for mission 2 includes a `[Cross-run]` hit
referencing mission 1. This is the one test that cannot be unit-tested because it
requires the full ContextManager + MissionContextStore + Postgres integration.

### Stress Test

Manual only. See "Running the Stress Test" above.

---

## Known Pitfalls

These are the specific issues encountered during implementation. They are documented here
so the next person does not spend two hours debugging them.

**1. vector(1536) migration requires USING NULL cast.**
`ALTER TABLE ... TYPE vector(384)` without `USING NULL::vector(384)` fails on any
Postgres instance that already ran `002_foundation.sql`. The column has never been
written to, but Postgres still requires an explicit cast. The USING clause is mandatory.
Warning sign: `ERROR: column "embedding" is of type vector(1536) but expression is of
type vector(384)`.

**2. fastembed must NOT be imported at module level.**
`embedding_provider.py` is imported by `context_manager.py` and `graph.py` in all
environments, including CI where fastembed is not installed. The import must be deferred
to `FastEmbedProvider.__init__` with a `try/except ImportError`. Warning sign:
`ImportError: No module named 'fastembed'` at test collection time.

**3. MockEmbeddingProvider dimension must be 384, not 256.**
SHA-256 produces 32 bytes = 256 bits. The mock uses those bytes as a random seed to
generate 384 Gaussian samples, then normalizes to unit norm. If you use the SHA-256
bytes directly as the vector, you get 256 dimensions and Postgres will reject the INSERT
with a dimension mismatch error.

**4. build_planner_context_injection cap is a new addition.**
The 1500-char cap on the injection output is added in Phase 7.3. It does not exist in
earlier code. If you see tests asserting on specific injection string lengths, update
them to account for the cap. The previous 800-char mention in MEMORY.md referred to a
log reference, not a code limit.

**5. clean_pg fixture must include new tables.**
The existing `clean_pg` fixture truncates `graph_checkpoints, runs, memo_entries`. It
must be extended to truncate `mission_contexts` and `mission_artifacts`. Use per-table
`try/except` so the fixture degrades gracefully on database instances that have not run
migrations 003 and 004 yet.

**6. BIT(384) must be passed as a plain Python string.**
Postgres expects the BIT literal as a string of `'0'` and `'1'` characters: `'01101...'`.
Passing Python `bytes` or an `int` will cause `psycopg.errors.InvalidTextRepresentation`.
The `_float_vec_to_bit_string()` function returns the correct format.

**7. HNSW index must be created on an empty table in the migration.**
Creating an HNSW index on a populated table is slow (it scans all rows). Migration 003
creates the index immediately after `CREATE TABLE`, while the table is empty, making
the index creation instant. For production migrations with existing data, use
`CREATE INDEX CONCURRENTLY` to avoid locking the table.

**8. on_mission_complete is synchronous -- no asyncio in the persistence path.**
The entire graph runs synchronously inside `anyio.to_thread.run_sync`. If
`MissionContextStore.upsert()` uses async code or `asyncio.run()`, it will raise
`RuntimeError: no running event loop` (or worse, silently deadlock). The persistence
path must be fully synchronous: `with self._pool.connection() as conn: conn.execute(...)`.

---

## Common Operations

**Start Postgres with pgvector for local development:**
```bash
docker compose up -d postgres
export DATABASE_URL=postgresql://agentic:agentic@localhost:5433/agentic_workflows
```

**Run unit tests only (no Postgres required):**
```bash
pytest tests/unit/ -q
```

**Run integration tests including Postgres stores:**
```bash
export DATABASE_URL=postgresql://agentic:agentic@localhost:5433/agentic_workflows
pytest tests/ -q --cov=src/agentic_workflows --cov-fail-under=80
```

**Run the stress test:**
```bash
docker compose -f docker/docker-compose.stress.yml up --build
python scripts/stress_test.py --url http://localhost:8000 --concurrency 10 --total 50
```

**Enable production embeddings (requires fastembed installed):**
```bash
pip install "agentic-workflows[context]"
export EMBEDDING_PROVIDER=fastembed
```

**Check which embedding provider is active:**
```python
from agentic_workflows.context.embedding_provider import get_embedding_provider
provider = get_embedding_provider()
print(type(provider).__name__)  # MockEmbeddingProvider or FastEmbedProvider
print(provider.dimensions)      # 384
```

---

## References

- `.planning/phases/07.3-semantic-context-system-pgvector-fastembed/07.3-CONTEXT.md` -- Implementation decisions and phase boundary
- `.planning/phases/07.3-semantic-context-system-pgvector-fastembed/07.3-RESEARCH.md` -- Pitfall catalog, integration codebase facts, code examples
- `src/agentic_workflows/context/embedding_provider.py` -- EmbeddingProvider Protocol, MockEmbeddingProvider, FastEmbedProvider
- `src/agentic_workflows/storage/mission_context_store.py` -- MissionContextStore, cascade implementation, RRF, TOOL_BITS
- `src/agentic_workflows/storage/artifact_store.py` -- ArtifactStore
- `src/agentic_workflows/orchestration/langgraph/context_manager.py` -- ContextManager integration (lines 230+)
- `db/migrations/003_mission_contexts.sql` -- Table schema and indexes
- `db/migrations/004_mission_artifacts.sql` -- Artifacts table schema
- `docker/docker-compose.stress.yml` -- Multi-replica stress topology
- `scripts/stress_test.py` -- Concurrent load test script
- Cormack, G. V., Clarke, C. L. A., & Buettcher, S. (2009). Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods. *SIGIR 2009*.

---

## Phase 7.5 — Artifact Persistence: Closing the Dead-Store Gap

Phase 7.3 created `ArtifactStore` and the `mission_artifacts` table, but the store was never wired
into the live execution path. `application.state.artifact_store` existed in `app.py` but was never
passed to `LangGraphOrchestrator`. Phase 7.5 closes that gap.

### What Changed

| File | Change |
|------|--------|
| `context_manager.py` | `ContextManager.__init__` accepts `artifact_store: ArtifactStore \| None = None`; `_persist_mission_context()` iterates `mission_context["artifacts"]` and calls `artifact_store.upsert()` for each |
| `graph.py` | `LangGraphOrchestrator.__init__` accepts `artifact_store: ArtifactStore \| None = None`; forwards it to `ContextManager` |
| `run.py` | `_build_orchestrator()` creates `ArtifactStore(pool=pool)` inside the `DATABASE_URL` block and passes it to the orchestrator |
| `user_run.py` | `UserSession.__post_init__()` creates `ArtifactStore(pool=self._pg_pool)` inside the `DATABASE_URL` block and passes it to the orchestrator |
| `app.py` | `LangGraphOrchestrator(...)` now receives `artifact_store=artifact_store` (the store was already created at `application.state.artifact_store` but not forwarded) |

### The Wiring Chain

```
Tool execution (e.g. write_file)
    → ContextManager.on_tool_result()
        → extract_artifacts() populates ctx.artifacts (list[ArtifactRecord])
    → ContextManager.on_mission_complete()
        → _persist_mission_context(persist_ctx)  # persist_ctx includes "artifacts" list
            → for art in artifacts:
                → self._artifact_store.upsert(run_id, mission_id, key, value, source_tool, embedding)
                    → INSERT INTO mission_artifacts ON CONFLICT DO UPDATE
```

### Backward Compatibility

Every new parameter uses `artifact_store: ArtifactStore | None = None` with a `None` default.
All existing code that constructs `LangGraphOrchestrator()` or `ContextManager()` without this
parameter continues to work unchanged. When `artifact_store=None`, the upsert call is guarded:

```python
if self._artifact_store is not None:
    for art in artifacts:
        ...
        self._artifact_store.upsert(...)
```

### Pool=None No-Op

`ArtifactStore` already implements a graceful `pool=None` no-op in `ArtifactStore.upsert()`:

```python
def upsert(self, ...) -> None:
    if self._pool is None:
        _logger.debug("ARTIFACT STORE upsert skipped pool=None")
        return
```

This means the store is safe to instantiate in SQLite/CI environments where `DATABASE_URL` is not
set. In those cases, `pool=None` is passed and all upserts silently skip.

### Artifact Embedding

Each artifact is embedded using `self._embedding_provider.embed_sync(art["value"][:200])` (the
same provider already injected into `ContextManager` for mission context embeddings). When no
embedding provider is configured, the fallback is a zero vector `[0.0] * 384`, which stores the
artifact without semantic search capability but preserves all structured fields.

### Integration Test

`tests/integration/test_artifact_store_runtime.py` verifies SC-1 end-to-end:

```python
cm.on_tool_result(state, "write_file", result=..., args=..., mission_id=1)
cm.on_mission_complete(state, mission_id=1)

with pg_pool.connection() as conn:
    rows = conn.execute(
        "SELECT key, source_tool FROM mission_artifacts WHERE run_id = %s", (run_id,)
    ).fetchall()

assert "file_path" in [r[0] for r in rows]
```

The test uses `pg_pool` + `clean_pg` fixtures from `conftest.py` (session pool, per-test TRUNCATE)
and is skipped automatically when `DATABASE_URL` is not set — CI-safe.
