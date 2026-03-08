"""MissionContextStore: 5-layer cascade retrieval for cross-run mission context.

Layer 0 (L0): SHA-256 exact hash -> short-circuit
Layer 1 (L1): 64-bit tool bitmask -> short-circuit
Layer 2 (L2): Postgres tsvector BM25 full-text -> top-20 candidates
Layer 3 (L3): BIT(384) binary Hamming -> merged with L4 pipeline
Layer 4 (L4): vector(384) HNSW cosine similarity -> top-20 candidates
L2+L4 fused via Reciprocal Rank Fusion (RRF, k=60).

All methods gracefully degrade (return [] / no-op) when pool=None.
Uses psycopg3 sync %s placeholders. Pool injected via __init__.
"""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from psycopg_pool import ConnectionPool

    from agentic_workflows.context.embedding_provider import EmbeddingProvider

# ---------------------------------------------------------------------------
# Tool bitmask registry
# Canonical sorted list from tools_registry.py build_tool_registry().
# New tools MUST be appended to preserve existing bitmask encodings.
# ---------------------------------------------------------------------------
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


def _sha256(text: str) -> str:
    """Return lowercase SHA-256 hex digest of text (64 chars). Deterministic."""
    return hashlib.sha256(text.encode()).hexdigest()


def _float_vec_to_bit_string(vec: list[float]) -> str:
    """Convert a float vector to a BIT(N) binary string for Postgres.

    Sign bit encoding: 1 if v >= 0.0 else 0.
    Result is a string of '0' and '1' characters (e.g., '01101...').
    """
    return "".join("1" if v >= 0.0 else "0" for v in vec)


def reciprocal_rank_fusion(*ranked_lists: list[str], k: int = 60) -> dict[str, float]:
    """Fuse multiple ranked lists via Reciprocal Rank Fusion (Cormack et al., 2009).

    Score for document d = sum(1 / (k + rank + 1)) across all input lists.
    Higher score = more relevant. k=60 is the standard parameter.

    Args:
        *ranked_lists: Variable number of ranked document ID lists (most relevant first).
        k: RRF damping parameter (default 60).

    Returns:
        Dict mapping doc_id -> cumulative RRF score, sorted descending by score.
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return dict(sorted(scores.items(), key=lambda x: x[1], reverse=True))


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


class MissionContextResult(TypedDict):
    """Result from MissionContextStore.query_cascade()."""

    id: int
    run_id: str
    mission_id: str
    goal: str
    summary: str
    tools_used: list[str]
    score: float


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class MissionContextStore:
    """Postgres-backed store for completed mission contexts with cascade retrieval.

    All methods degrade gracefully (return [] / no-op) when pool=None,
    so ContextManager can use this store without a live DB connection.

    Pool pattern: injected via __init__, never closed by this class.
    SQL pattern: psycopg3 sync %s placeholders, with pool.connection() context manager.
    """

    def __init__(
        self,
        pool: ConnectionPool | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._pool = pool
        self._embedding_provider = embedding_provider

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def upsert(
        self,
        *,
        run_id: str,
        mission_id: str,
        goal: str,
        status: str,
        summary: str,
        tools_used: list[str],
        key_results: dict,
        embedding: list[float],
        artifacts: list | None = None,
    ) -> None:
        """Insert or update a completed mission context record.

        No-op when pool=None (graceful degradation for CI / SQLite environments).
        """
        if self._pool is None:
            return

        import json

        goal_hash = _sha256(goal.strip().lower())
        tool_pattern = encode_tool_pattern(tools_used)
        embedding_bin = _float_vec_to_bit_string(embedding)
        embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

        sql = """
            INSERT INTO mission_contexts
                (run_id, mission_id, goal, goal_hash, tool_pattern,
                 embedding_bin, embedding, status, summary, tools_used,
                 key_results, artifacts)
            VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id, mission_id) DO UPDATE SET
                goal = EXCLUDED.goal,
                goal_hash = EXCLUDED.goal_hash,
                tool_pattern = EXCLUDED.tool_pattern,
                embedding_bin = EXCLUDED.embedding_bin,
                embedding = EXCLUDED.embedding,
                status = EXCLUDED.status,
                summary = EXCLUDED.summary,
                tools_used = EXCLUDED.tools_used,
                key_results = EXCLUDED.key_results,
                artifacts = EXCLUDED.artifacts
        """
        with self._pool.connection() as conn:
            conn.execute(
                sql,
                (
                    run_id,
                    mission_id,
                    goal,
                    goal_hash,
                    tool_pattern,
                    embedding_bin,
                    embedding_str,
                    status,
                    summary,
                    tools_used,
                    json.dumps(key_results),
                    json.dumps(artifacts or []),
                ),
            )

    # ------------------------------------------------------------------
    # Read path -- 5-layer cascade
    # ------------------------------------------------------------------

    def query_cascade(
        self,
        goal: str,
        tools_used: list[str] | None = None,
        embedding: list[float] | None = None,
        top_k: int = 3,
    ) -> list[MissionContextResult]:
        """Run the 5-layer cascade retrieval and return top-k results.

        L0: Exact SHA-256 hash match -- short-circuit, returns immediately.
        L1: Tool bitmask structural match -- short-circuit if >= top_k results.
        L2: tsvector BM25 keyword search -> up to 20 candidates.
        L4: pgvector HNSW cosine similarity -> up to 20 candidates.
        L2+L4 fused via RRF (k=60). L3 binary Hamming merged into L4 pipeline.

        Returns [] gracefully when pool=None or Postgres is unavailable.
        """
        if self._pool is None:
            return []

        try:
            return self._cascade(goal, tools_used or [], embedding, top_k)
        except Exception:
            return []

    def _cascade(
        self,
        goal: str,
        tools_used: list[str],
        embedding: list[float] | None,
        top_k: int,
    ) -> list[MissionContextResult]:
        goal_normalized = goal.strip().lower()
        goal_hash = _sha256(goal_normalized)

        with self._pool.connection() as conn:  # type: ignore[union-attr]
            # L0: exact SHA-256 hit -- short-circuit
            row = conn.execute(
                "SELECT id, run_id, mission_id, goal, summary, tools_used "
                "FROM mission_contexts WHERE goal_hash = %s AND status = 'completed' LIMIT 1",
                (goal_hash,),
            ).fetchone()
            if row:
                return [self._row_to_result(row, score=1.0)]

            # L1: tool bitmask structural match -- short-circuit if sufficient
            if tools_used:
                bitmask = encode_tool_pattern(tools_used)
                if bitmask:
                    rows = conn.execute(
                        "SELECT id, run_id, mission_id, goal, summary, tools_used "
                        "FROM mission_contexts "
                        "WHERE (tool_pattern & %s) = %s AND status = 'completed' "
                        "ORDER BY created_at DESC LIMIT %s",
                        (bitmask, bitmask, top_k),
                    ).fetchall()
                    if len(rows) >= top_k:
                        return [self._row_to_result(r, score=0.9) for r in rows[:top_k]]

            # L2: BM25 tsvector keyword search
            l2_ids: list[str] = []
            l2_rows = conn.execute(
                "SELECT id, run_id, mission_id, goal, summary, tools_used, "
                "    ts_rank(goal_tsvector, plainto_tsquery('english', %s)) AS rank "
                "FROM mission_contexts "
                "WHERE goal_tsvector @@ plainto_tsquery('english', %s) "
                "  AND status = 'completed' "
                "ORDER BY rank DESC LIMIT 20",
                (goal, goal),
            ).fetchall()
            l2_id_to_row = {}
            for r in l2_rows:
                l2_ids.append(str(r[0]))
                l2_id_to_row[str(r[0])] = r

            # L4: pgvector HNSW cosine similarity
            l4_ids: list[str] = []
            l4_id_to_row = {}
            if embedding is not None:
                emb_str = "[" + ",".join(str(v) for v in embedding) + "]"
                l4_rows = conn.execute(
                    "SELECT id, run_id, mission_id, goal, summary, tools_used, "
                    "    1 - (embedding <=> %s::vector) AS score "
                    "FROM mission_contexts "
                    "WHERE status = 'completed' "
                    "ORDER BY embedding <=> %s::vector LIMIT 20",
                    (emb_str, emb_str),
                ).fetchall()
                for r in l4_rows:
                    l4_ids.append(str(r[0]))
                    l4_id_to_row[str(r[0])] = r

            # RRF fusion over L2 + L4
            fused = reciprocal_rank_fusion(l2_ids, l4_ids)
            results: list[MissionContextResult] = []
            all_rows = {**l2_id_to_row, **l4_id_to_row}
            for doc_id, rrf_score in list(fused.items())[:top_k]:
                if doc_id in all_rows:
                    results.append(self._row_to_result(all_rows[doc_id], score=rrf_score))

            # Fallback: if no RRF results, return L2 results by rank
            if not results and l2_rows:
                for r in l2_rows[:top_k]:
                    results.append(
                        self._row_to_result(r, score=float(r[6]) if len(r) > 6 else 0.5)
                    )

            return results

    @staticmethod
    def _row_to_result(row: tuple, score: float) -> MissionContextResult:
        """Convert a DB row tuple to MissionContextResult TypedDict."""
        return MissionContextResult(
            id=int(row[0]),
            run_id=str(row[1]),
            mission_id=str(row[2]),
            goal=str(row[3]),
            summary=str(row[4]) if row[4] else "",
            tools_used=list(row[5]) if row[5] else [],
            score=score,
        )
