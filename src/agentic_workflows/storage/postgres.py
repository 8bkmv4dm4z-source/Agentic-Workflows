"""PostgresRunStore -- Postgres implementation of RunStore protocol.

Mirrors the SQLiteRunStore API exactly, using psycopg + ConnectionPool.
Async methods wrap synchronous pool operations via anyio.to_thread.run_sync.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

import anyio
import structlog as _structlog
from psycopg_pool import ConnectionPool

_log = _structlog.get_logger()

MAX_RESULT_JSON_BYTES = int(os.environ.get("MAX_RESULT_JSON_BYTES", str(512 * 1024)))

# Column ordering for SELECT * queries -- must match 001_init.sql table definition
_RUN_COLUMNS = (
    "run_id",
    "status",
    "user_input",
    "prior_context_json",
    "client_ip",
    "request_headers_json",
    "result_json",
    "created_at",
    "completed_at",
    "missions_completed",
    "tools_used_json",
)


class PostgresRunStore:
    """Async-compatible Postgres store for run persistence.

    Sync psycopg calls are offloaded to a worker thread via
    ``anyio.to_thread.run_sync`` so that the event loop is never blocked.
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    async def initialize(self) -> None:
        """No-op async initializer for protocol compatibility.

        Tables are created by SQL migration scripts (db/migrations/).
        """

    # ------------------------------------------------------------------
    # RunStore protocol methods
    # ------------------------------------------------------------------

    async def save_run(self, run_id: str, *, status: str, **fields: Any) -> None:
        """Insert a new run record."""

        # Guard against oversized result blobs: truncate tool_history if needed.
        result_value = fields.get("result")
        if result_value is not None:
            candidate = _to_json(result_value) or ""
            if len(candidate.encode()) > MAX_RESULT_JSON_BYTES:
                _log.warning(
                    "run_store.result_truncated",
                    run_id=run_id,
                    original_bytes=len(candidate.encode()),
                    limit_bytes=MAX_RESULT_JSON_BYTES,
                )
                truncated = dict(result_value)
                tool_history = truncated.get("tools_used", [])
                truncated["tools_used"] = [
                    {
                        "tool": t.get("tool", "") if isinstance(t, dict) else str(t),
                        "args_summary": str(t.get("args", ""))[:200]
                        if isinstance(t, dict)
                        else "",
                        "result_truncated": True,
                    }
                    for t in tool_history
                ]
                result_value = truncated

        def _save() -> None:
            with self._pool.connection() as conn:
                conn.execute(
                    """INSERT INTO runs
                       (run_id, status, user_input, prior_context_json,
                        client_ip, request_headers_json, result_json,
                        created_at, missions_completed, tools_used_json)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        run_id,
                        status,
                        fields.get("user_input"),
                        _to_json(fields.get("prior_context")),
                        fields.get("client_ip"),
                        _to_json(fields.get("request_headers")),
                        _to_json(result_value),
                        datetime.now(UTC).isoformat(),
                        fields.get("missions_completed", 0),
                        _to_json(fields.get("tools_used")),
                    ),
                )

        await anyio.to_thread.run_sync(_save)

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Retrieve a run by ID."""

        def _get() -> dict[str, Any] | None:
            with self._pool.connection() as conn:
                row = conn.execute(
                    "SELECT * FROM runs WHERE run_id = %s", (run_id,)
                ).fetchone()
            if row is None:
                return None
            return dict(zip(_RUN_COLUMNS, row, strict=False))

        return await anyio.to_thread.run_sync(_get)

    async def list_runs(
        self, limit: int = 20, cursor: str | None = None
    ) -> list[dict[str, Any]]:
        """Return runs newest-first with optional cursor-based pagination."""

        def _list() -> list[dict[str, Any]]:
            with self._pool.connection() as conn:
                if cursor is not None:
                    # Look up the created_at of the cursor row to use as the anchor
                    anchor_row = conn.execute(
                        "SELECT created_at FROM runs WHERE run_id = %s", (cursor,)
                    ).fetchone()
                    if anchor_row:
                        rows = conn.execute(
                            "SELECT * FROM runs WHERE created_at < %s "
                            "ORDER BY created_at DESC LIMIT %s",
                            (anchor_row[0], limit),
                        ).fetchall()
                    else:
                        # Cursor not found -- return empty page
                        rows = []
                else:
                    rows = conn.execute(
                        "SELECT * FROM runs ORDER BY created_at DESC LIMIT %s", (limit,)
                    ).fetchall()
                return [dict(zip(_RUN_COLUMNS, r, strict=False)) for r in rows]

        return await anyio.to_thread.run_sync(_list)

    async def update_run(self, run_id: str, **fields: Any) -> None:
        """Update fields on an existing run."""

        def _update() -> None:
            set_clauses: list[str] = []
            values: list[Any] = []
            for key, val in fields.items():
                col = _field_to_column(key)
                if col in _JSON_COLUMNS:
                    set_clauses.append(f"{col} = %s")
                    values.append(_to_json(val))
                else:
                    set_clauses.append(f"{col} = %s")
                    values.append(val)
            if not set_clauses:
                return
            values.append(run_id)
            sql = f"UPDATE runs SET {', '.join(set_clauses)} WHERE run_id = %s"
            with self._pool.connection() as conn:
                conn.execute(sql, values)

        await anyio.to_thread.run_sync(_update)

    def close(self) -> None:
        """No-op -- pool lifecycle managed externally by app.py lifespan."""


# ------------------------------------------------------------------
# Helpers (copied from SQLiteRunStore for consistency)
# ------------------------------------------------------------------

_JSON_COLUMNS = frozenset({
    "prior_context_json",
    "request_headers_json",
    "result_json",
    "tools_used_json",
})

_FIELD_TO_COL: dict[str, str] = {
    "prior_context": "prior_context_json",
    "request_headers": "request_headers_json",
    "result": "result_json",
    "tools_used": "tools_used_json",
}


def _field_to_column(field: str) -> str:
    return _FIELD_TO_COL.get(field, field)


def _to_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=str)
