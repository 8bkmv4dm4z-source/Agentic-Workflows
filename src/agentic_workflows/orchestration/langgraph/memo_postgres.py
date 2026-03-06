"""PostgresMemoStore -- Postgres implementation of MemoStore.

Mirrors the SQLiteMemoStore API exactly, using psycopg + ConnectionPool
for synchronous operations (called from sync graph node code).
"""

from __future__ import annotations

import json
from typing import Any

from psycopg_pool import ConnectionPool

from agentic_workflows.logger import get_logger
from agentic_workflows.orchestration.langgraph.memo_store import MemoLookupResult, PutResult
from agentic_workflows.orchestration.langgraph.state_schema import hash_json


class PostgresMemoStore:
    """Postgres implementation of run-scoped memo storage."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool
        self.logger = get_logger("langgraph.memo_store.postgres")

    def put(
        self,
        *,
        run_id: str,
        key: str,
        value: Any,
        namespace: str = "run",
        source_tool: str = "memoize",
        step: int = 0,
        created_at: str = "",
    ) -> PutResult:
        """Insert or update a memo entry with deterministic hash metadata."""
        value_json = json.dumps(value, sort_keys=True, default=str)
        value_hash = hash_json(value)
        timestamp = created_at or ""
        if not timestamp:
            from agentic_workflows.orchestration.langgraph.state_schema import utc_now_iso

            timestamp = utc_now_iso()

        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO memo_entries (
                    run_id, namespace, key, value_json, value_hash,
                    source_tool, step, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(run_id, namespace, key) DO UPDATE SET
                    value_json=EXCLUDED.value_json,
                    value_hash=EXCLUDED.value_hash,
                    source_tool=EXCLUDED.source_tool,
                    step=EXCLUDED.step,
                    created_at=EXCLUDED.created_at
                """,
                (run_id, namespace, key, value_json, value_hash, source_tool, step, timestamp),
            )

        self.logger.info(
            "MEMO PUT run_id=%s namespace=%s key=%s value_hash=%s source_tool=%s step=%s",
            run_id,
            namespace,
            key,
            value_hash,
            source_tool,
            step,
        )

        return PutResult(
            inserted=True,
            run_id=run_id,
            key=key,
            namespace=namespace,
            value_hash=value_hash,
        )

    def get(self, *, run_id: str, key: str, namespace: str = "run") -> MemoLookupResult:
        """Retrieve a memoized value for a specific run and key."""
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT value_json, value_hash
                FROM memo_entries
                WHERE run_id = %s AND namespace = %s AND key = %s
                """,
                (run_id, namespace, key),
            ).fetchone()

        if row is None:
            self.logger.info("MEMO GET MISS run_id=%s namespace=%s key=%s", run_id, namespace, key)
            return MemoLookupResult(
                found=False,
                run_id=run_id,
                key=key,
                namespace=namespace,
                value=None,
                value_hash=None,
            )

        self.logger.info("MEMO GET HIT run_id=%s namespace=%s key=%s", run_id, namespace, key)
        return MemoLookupResult(
            found=True,
            run_id=run_id,
            key=key,
            namespace=namespace,
            value=json.loads(row[0]),
            value_hash=row[1],
        )

    def get_latest(self, *, key: str, namespace: str = "run") -> MemoLookupResult:
        """Retrieve latest memoized value by key across all run ids."""
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT run_id, value_json, value_hash
                FROM memo_entries
                WHERE namespace = %s AND key = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (namespace, key),
            ).fetchone()

        if row is None:
            self.logger.info("MEMO GET LATEST MISS namespace=%s key=%s", namespace, key)
            return MemoLookupResult(
                found=False,
                run_id="",
                key=key,
                namespace=namespace,
                value=None,
                value_hash=None,
            )

        found_run_id = str(row[0])
        self.logger.info(
            "MEMO GET LATEST HIT run_id=%s namespace=%s key=%s", found_run_id, namespace, key
        )
        return MemoLookupResult(
            found=True,
            run_id=found_run_id,
            key=key,
            namespace=namespace,
            value=json.loads(row[1]),
            value_hash=row[2],
        )

    def list_entries(self, *, run_id: str, namespace: str = "run") -> list[dict[str, Any]]:
        """List memo metadata for visibility/reporting (no model call required)."""
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT key, value_hash, source_tool, step, created_at
                FROM memo_entries
                WHERE run_id = %s AND namespace = %s
                ORDER BY step ASC, id ASC
                """,
                (run_id, namespace),
            ).fetchall()
        entries = [
            {
                "key": r[0],
                "value_hash": r[1],
                "source_tool": r[2],
                "step": r[3],
                "created_at": str(r[4]),
            }
            for r in rows
        ]
        self.logger.info(
            "MEMO LIST run_id=%s namespace=%s count=%s",
            run_id,
            namespace,
            len(entries),
        )
        return entries

    def delete(
        self, *, run_id: str, key: str, namespace: str = "run", value_hash: str | None = None
    ) -> int:
        """Delete memo entries by key (optionally constrained by hash)."""
        with self._pool.connection() as conn:
            if value_hash:
                cursor = conn.execute(
                    """
                    DELETE FROM memo_entries
                    WHERE run_id = %s AND namespace = %s AND key = %s AND value_hash = %s
                    """,
                    (run_id, namespace, key, value_hash),
                )
            else:
                cursor = conn.execute(
                    """
                    DELETE FROM memo_entries
                    WHERE run_id = %s AND namespace = %s AND key = %s
                    """,
                    (run_id, namespace, key),
                )
            deleted = cursor.rowcount or 0
        self.logger.info(
            "MEMO DELETE run_id=%s namespace=%s key=%s value_hash=%s deleted=%s",
            run_id,
            namespace,
            key,
            value_hash or "",
            deleted,
        )
        return deleted

    def get_cache_value(self, *, key: str, run_id: str = "shared") -> dict[str, Any] | None:
        """Return cached dict payload for shared cache keys, if present."""
        lookup = self.get(run_id=run_id, key=key, namespace="cache")
        if not lookup.found:
            return None
        if not isinstance(lookup.value, dict):
            return None
        return lookup.value
