"""SQLiteRunStore -- WAL-mode SQLite implementation of RunStore."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import UTC, datetime
from typing import Any

import anyio
import structlog as _structlog

_log = _structlog.get_logger()

MAX_RESULT_JSON_BYTES = int(os.environ.get("MAX_RESULT_JSON_BYTES", str(512 * 1024)))

_DEFAULT_DB_PATH = os.environ.get("RUN_STORE_DB", ".tmp/run_store.db")

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT PRIMARY KEY,
    status              TEXT NOT NULL DEFAULT 'pending',
    user_input          TEXT,
    prior_context_json  TEXT,
    client_ip           TEXT,
    request_headers_json TEXT,
    result_json         TEXT,
    created_at          TEXT NOT NULL,
    completed_at        TEXT,
    missions_completed  INTEGER DEFAULT 0,
    tools_used_json     TEXT
)
"""


class SQLiteRunStore:
    """Async-compatible SQLite store with WAL journal mode.

    Sync ``sqlite3`` calls are offloaded to a worker thread via
    ``anyio.to_thread.run_sync`` so that the event loop is never blocked.
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()

    async def initialize(self) -> None:
        """No-op async initializer for protocol compatibility.

        The store is fully initialized in __init__ (synchronous). This method
        exists for callers that await store.initialize() after construction.
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
                        "args_summary": str(t.get("args", ""))[:200] if isinstance(t, dict) else "",
                        "result_truncated": True,
                    }
                    for t in tool_history
                ]
                result_value = truncated

        def _save() -> None:
            with self._lock:
                self._conn.execute(
                    """INSERT INTO runs
                       (run_id, status, user_input, prior_context_json,
                        client_ip, request_headers_json, result_json,
                        created_at, missions_completed, tools_used_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                self._conn.commit()

        await anyio.to_thread.run_sync(_save)

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Retrieve a run by ID."""

        def _get() -> dict[str, Any] | None:
            with self._lock:
                row = self._conn.execute(
                    "SELECT * FROM runs WHERE run_id = ?", (run_id,)
                ).fetchone()
            return dict(row) if row else None

        return await anyio.to_thread.run_sync(_get)

    async def list_runs(
        self, limit: int = 20, cursor: str | None = None
    ) -> list[dict[str, Any]]:
        """Return runs newest-first with optional cursor-based pagination."""

        def _list() -> list[dict[str, Any]]:
            with self._lock:
                if cursor is not None:
                    # Look up the created_at of the cursor row to use as the anchor
                    anchor_row = self._conn.execute(
                        "SELECT created_at FROM runs WHERE run_id = ?", (cursor,)
                    ).fetchone()
                    if anchor_row:
                        rows = self._conn.execute(
                            "SELECT * FROM runs WHERE created_at < ? ORDER BY created_at DESC LIMIT ?",
                            (anchor_row["created_at"], limit),
                        ).fetchall()
                    else:
                        # Cursor not found — return empty page
                        rows = []
                else:
                    rows = self._conn.execute(
                        "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
                    ).fetchall()
                return [dict(r) for r in rows]

        return await anyio.to_thread.run_sync(_list)

    async def update_run(self, run_id: str, **fields: Any) -> None:
        """Update fields on an existing run."""

        def _update() -> None:
            set_clauses: list[str] = []
            values: list[Any] = []
            for key, val in fields.items():
                col = _field_to_column(key)
                if col in _JSON_COLUMNS:
                    set_clauses.append(f"{col} = ?")
                    values.append(_to_json(val))
                else:
                    set_clauses.append(f"{col} = ?")
                    values.append(val)
            if not set_clauses:
                return
            values.append(run_id)
            sql = f"UPDATE runs SET {', '.join(set_clauses)} WHERE run_id = ?"
            with self._lock:
                self._conn.execute(sql, values)
                self._conn.commit()

        await anyio.to_thread.run_sync(_update)

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()


# ------------------------------------------------------------------
# Helpers
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
