"""ArtifactStore: Postgres-backed store for cross-run tool output artifacts.

Stores key-value artifact pairs produced by tools, with SHA-256 key hash for
exact lookup and vector(384) embedding for semantic search.

Follows the project-standard connection pool injection pattern:
- Pool injected via __init__ (never managed by store)
- psycopg3 sync %s placeholders
- with pool.connection() as conn: conn.execute(...)
- All methods degrade gracefully (no-op / return []) when pool=None
"""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, TypedDict

from agentic_workflows.logger import get_logger

if TYPE_CHECKING:
    from psycopg_pool import ConnectionPool

    from agentic_workflows.context.embedding_provider import EmbeddingProvider

_logger = get_logger("artifact_store")


def _sha256_key(key: str) -> str:
    """SHA-256 hex digest of key for O(1) exact lookup via ix_mission_artifacts_key_hash."""
    return hashlib.sha256(key.encode()).hexdigest()


class ArtifactResult(TypedDict):
    """Result from ArtifactStore.search()."""

    id: int
    run_id: str
    mission_id: str
    key: str
    value: str
    source_tool: str
    score: float


class ArtifactStore:
    """Postgres-backed artifact store with semantic search.

    All methods degrade gracefully (return [] / no-op) when pool=None,
    making this safe to use in SQLite/CI environments without a Postgres connection.

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

    def upsert(
        self,
        *,
        run_id: str,
        mission_id: str,
        key: str,
        value: str,
        source_tool: str,
        embedding: list[float],
    ) -> None:
        """Insert or update an artifact. No-op when pool=None.

        On conflict (run_id, mission_id, key), updates value, source_tool, and embedding.
        """
        if self._pool is None:
            _logger.debug("ARTIFACT STORE upsert skipped pool=None")
            return

        key_hash = _sha256_key(key)
        embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

        sql = """
            INSERT INTO mission_artifacts
                (run_id, mission_id, key, value, source_tool, key_hash, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
            ON CONFLICT (run_id, mission_id, key) DO UPDATE SET
                value = EXCLUDED.value,
                source_tool = EXCLUDED.source_tool,
                key_hash = EXCLUDED.key_hash,
                embedding = EXCLUDED.embedding
        """
        with self._pool.connection() as conn:
            conn.execute(
                sql,
                (run_id, mission_id, key, value, source_tool, key_hash, embedding_str),
            )
        _logger.info("ARTIFACT STORE upsert key_hash=%s run_id=%s", key_hash[:12], run_id)

    def search(
        self,
        embedding: list[float],
        limit: int = 5,
        run_id: str | None = None,
    ) -> list[ArtifactResult]:
        """Search artifacts by semantic similarity using HNSW cosine index.

        Returns [] gracefully when pool=None or Postgres unavailable.
        Optionally filter by run_id for within-run artifact lookups.
        """
        if self._pool is None:
            _logger.debug("ARTIFACT STORE search skipped pool=None")
            return []

        try:
            results = self._search(embedding, limit, run_id)
            _logger.info("ARTIFACT STORE search top_k=%d results=%d", limit, len(results))
            return results
        except Exception as exc:  # noqa: BLE001
            _logger.warning("ARTIFACT STORE error op=search error=%s", exc)
            return []

    def _search(
        self,
        embedding: list[float],
        limit: int,
        run_id: str | None,
    ) -> list[ArtifactResult]:
        emb_str = "[" + ",".join(str(v) for v in embedding) + "]"

        params: tuple[str | int, ...]
        if run_id is not None:
            sql = (
                "SELECT id, run_id, mission_id, key, value, source_tool, "
                "    1 - (embedding <=> %s::vector) AS score "
                "FROM mission_artifacts "
                "WHERE run_id = %s "
                "ORDER BY embedding <=> %s::vector LIMIT %s"
            )
            params = (emb_str, run_id, emb_str, limit)
        else:
            sql = (
                "SELECT id, run_id, mission_id, key, value, source_tool, "
                "    1 - (embedding <=> %s::vector) AS score "
                "FROM mission_artifacts "
                "ORDER BY embedding <=> %s::vector LIMIT %s"
            )
            params = (emb_str, emb_str, limit)

        if self._pool is None:
            return []
        with self._pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            ArtifactResult(
                id=int(r[0]),
                run_id=str(r[1]),
                mission_id=str(r[2]),
                key=str(r[3]),
                value=str(r[4]),
                source_tool=str(r[5]),
                score=float(r[6]),
            )
            for r in rows
        ]
