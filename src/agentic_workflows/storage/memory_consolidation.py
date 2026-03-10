"""Memory consolidation: cluster old episodic missions by semantic similarity.

Prevents unbounded growth of mission_contexts table by merging semantically
similar old missions into consolidated summaries. Uses greedy single-linkage
clustering on cosine similarity of embeddings.

All methods gracefully degrade (return early) when pool=None.
Uses psycopg3 sync %s placeholders.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from agentic_workflows.logger import get_logger

if TYPE_CHECKING:
    from psycopg_pool import ConnectionPool

    from agentic_workflows.context.embedding_provider import EmbeddingProvider

_logger = get_logger("memory_consolidation")


# ---------------------------------------------------------------------------
# Pure math helpers
# ---------------------------------------------------------------------------


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors. Returns 0.0 for zero vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


def _cluster_by_similarity(
    items: list[dict], threshold: float = 0.85
) -> list[list[dict]]:
    """Greedy single-linkage clustering.

    Items are grouped if *any* pair in the cluster has similarity >= threshold.
    Returns a list of clusters (each cluster is a list of item dicts).
    """
    if not items:
        return []

    # Track which cluster index each item belongs to
    n = len(items)
    cluster_ids: list[int] = list(range(n))  # each item starts in its own cluster

    def _find(i: int) -> int:
        while cluster_ids[i] != i:
            cluster_ids[i] = cluster_ids[cluster_ids[i]]  # path compression
            i = cluster_ids[i]
        return i

    def _union(i: int, j: int) -> None:
        ri, rj = _find(i), _find(j)
        if ri != rj:
            cluster_ids[ri] = rj

    # Compare all pairs
    for i in range(n):
        for j in range(i + 1, n):
            sim = _cosine_similarity(items[i]["embedding"], items[j]["embedding"])
            if sim >= threshold:
                _union(i, j)

    # Collect clusters
    clusters_map: dict[int, list[dict]] = {}
    for idx, item in enumerate(items):
        root = _find(idx)
        clusters_map.setdefault(root, []).append(item)

    return list(clusters_map.values())


# ---------------------------------------------------------------------------
# Summary merging
# ---------------------------------------------------------------------------


def _merge_cluster_summary(cluster: list[dict]) -> str:
    """Combine goals from cluster members into a consolidated summary.

    Merges tools_used as a union set (stored on first item for later use).
    Truncates to 500 chars.
    """
    goals = [item.get("goal", "") for item in cluster]
    all_tools: set[str] = set()
    for item in cluster:
        for t in item.get("tools_used", []):
            all_tools.add(t)

    summary = f"Consolidated {len(cluster)} missions: " + "; ".join(goals)
    if len(summary) > 500:
        summary = summary[:497] + "..."

    # Store merged tools on first item for the caller
    if cluster:
        cluster[0]["_merged_tools"] = sorted(all_tools)

    return summary


# ---------------------------------------------------------------------------
# DB row conversion
# ---------------------------------------------------------------------------


def _row_to_item(row: tuple) -> dict:
    """Convert a DB row tuple to a dict for clustering.

    Expected column order: id, run_id, mission_id, goal, summary, tools_used, embedding
    """
    tools_raw = row[5]
    if isinstance(tools_raw, str):
        # Postgres text[] comes as '{a,b,c}' string
        tools_raw = tools_raw.strip("{}").split(",") if tools_raw.strip("{}") else []
    elif tools_raw is None:
        tools_raw = []

    embedding_raw = row[6]
    if isinstance(embedding_raw, str):
        # Postgres vector comes as '[0.1,0.2,...]' string
        embedding_raw = [float(x) for x in embedding_raw.strip("[]").split(",")]
    elif embedding_raw is None:
        embedding_raw = []

    return {
        "id": row[0],
        "run_id": row[1],
        "mission_id": row[2],
        "goal": row[3],
        "summary": row[4],
        "tools_used": tools_raw if isinstance(tools_raw, list) else list(tools_raw),
        "embedding": embedding_raw if isinstance(embedding_raw, list) else list(embedding_raw),
    }


# ---------------------------------------------------------------------------
# Main consolidation entry point
# ---------------------------------------------------------------------------


def consolidate_memories(
    pool: ConnectionPool | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    age_days: int = 7,
    similarity_threshold: float = 0.85,
) -> dict[str, Any]:
    """Cluster old completed missions by cosine similarity and merge them.

    Args:
        pool: psycopg3 ConnectionPool. If None, returns early with zero counts.
        embedding_provider: Optional provider to re-embed merged summaries.
        age_days: Only consolidate missions older than this many days.
        similarity_threshold: Cosine similarity threshold for clustering.

    Returns:
        Dict with keys: clusters, consolidated, kept.
    """
    empty = {"clusters": 0, "consolidated": 0, "kept": 0}
    if pool is None:
        return empty

    with pool.connection() as conn:
        cursor = conn.execute(
            "SELECT id, run_id, mission_id, goal, summary, tools_used, embedding "
            "FROM mission_contexts "
            "WHERE status = 'completed' "
            "AND created_at < NOW() - INTERVAL '%s days'",
            (age_days,),
        )
        rows = cursor.fetchall()

    if not rows:
        _logger.info("No old missions to consolidate (age_days=%d)", age_days)
        return empty

    # Convert to item dicts, skip rows without embeddings
    items = []
    for row in rows:
        item = _row_to_item(row)
        if item["embedding"]:
            items.append(item)

    if not items:
        _logger.info("No missions with embeddings to consolidate")
        return empty

    clusters = _cluster_by_similarity(items, threshold=similarity_threshold)

    consolidated_count = 0
    kept_count = 0

    with pool.connection() as conn:
        for cluster in clusters:
            if len(cluster) < 2:
                kept_count += len(cluster)
                continue

            # Merge this cluster
            summary = _merge_cluster_summary(cluster)
            merged_tools = cluster[0].get("_merged_tools", cluster[0].get("tools_used", []))

            # Compute embedding for merged summary
            if embedding_provider:
                try:
                    merged_embedding = embedding_provider.embed([summary])[0]
                except Exception:
                    _logger.warning("Failed to embed merged summary, averaging instead")
                    merged_embedding = _average_embeddings(cluster)
            else:
                merged_embedding = _average_embeddings(cluster)

            # Use first item as base record
            base = cluster[0]
            ids_to_delete = [item["id"] for item in cluster]

            # Transactional: DELETE originals + INSERT consolidated
            conn.execute(
                "DELETE FROM mission_contexts WHERE id = ANY(%s)",
                (ids_to_delete,),
            )
            conn.execute(
                "INSERT INTO mission_contexts "
                "(run_id, mission_id, goal, summary, tools_used, embedding, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'completed')",
                (
                    base["run_id"],
                    base["mission_id"],
                    base["goal"],
                    summary,
                    merged_tools,
                    str(merged_embedding) if merged_embedding else None,
                ),
            )
            consolidated_count += len(cluster)

    result = {
        "clusters": len([c for c in clusters if len(c) >= 2]),
        "consolidated": consolidated_count,
        "kept": kept_count,
    }
    _logger.info("Consolidation complete: %s", result)
    return result


def _average_embeddings(cluster: list[dict]) -> list[float]:
    """Average the embeddings of cluster members."""
    if not cluster:
        return []
    dim = len(cluster[0].get("embedding", []))
    if dim == 0:
        return []
    avg = [0.0] * dim
    for item in cluster:
        emb = item.get("embedding", [])
        for i in range(min(dim, len(emb))):
            avg[i] += emb[i]
    n = len(cluster)
    return [x / n for x in avg]
