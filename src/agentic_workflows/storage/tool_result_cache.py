"""ToolResultCache — stores large tool results with TTL for planner context compression.

Pool-injection pattern (Phase 7 standard): pass pool=None for SQLite-only / CI deployments.
All methods are no-ops when pool is None, matching ArtifactStore and MissionContextStore behavior.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg_pool import ConnectionPool

_DEFAULT_TTL_DAYS = int(os.getenv("TOOL_RESULT_CACHE_TTL_DAYS", "7"))


def make_args_hash(tool_name: str, args: dict) -> str:
    """Stable SHA-256 hash of tool_name + sorted JSON args."""
    payload = json.dumps({"tool": tool_name, "args": args}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


class ToolResultCache:
    """Postgres-backed cache for large tool results. No-op when pool=None."""

    def __init__(self, pool: ConnectionPool | None = None) -> None:
        self._pool = pool

    def store(
        self,
        *,
        tool_name: str,
        args_hash: str,
        full_result: str,
        summary: str,
        expires_at: datetime | None = None,
    ) -> None:
        """Persist a large result. No-op when pool=None."""
        if self._pool is None:
            return
        if expires_at is None:
            expires_at = datetime.now(tz=UTC) + timedelta(days=_DEFAULT_TTL_DAYS)
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO tool_result_cache
                    (tool_name, args_hash, full_result, summary, result_len, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (tool_name, args_hash)
                DO UPDATE SET
                    full_result = EXCLUDED.full_result,
                    summary     = EXCLUDED.summary,
                    result_len  = EXCLUDED.result_len,
                    expires_at  = EXCLUDED.expires_at
                """,
                (tool_name, args_hash, full_result, summary, len(full_result), expires_at),
            )

    def get(self, *, tool_name: str, args_hash: str) -> str | None:
        """Retrieve cached full result. Returns None on miss or expired entry (lazy TTL eviction)."""
        if self._pool is None:
            return None
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT full_result, expires_at
                FROM tool_result_cache
                WHERE tool_name = %s AND args_hash = %s
                """,
                (tool_name, args_hash),
            ).fetchone()
        if row is None:
            return None
        full_result, expires_at = row
        if expires_at < datetime.now(tz=UTC):
            # Lazy TTL eviction — delete inline on read
            with self._pool.connection() as conn:
                conn.execute(
                    "DELETE FROM tool_result_cache WHERE tool_name = %s AND args_hash = %s",
                    (tool_name, args_hash),
                )
            return None
        return full_result
