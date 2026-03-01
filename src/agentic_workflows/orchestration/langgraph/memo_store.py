from __future__ import annotations

"""Schema-backed memoization store for Phase 1.

The store tracks memo entries per run and namespace, enabling deterministic
verification that memoization occurred during execution.
"""

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentic_workflows.logger import get_logger
from agentic_workflows.orchestration.langgraph.state_schema import hash_json


@dataclass(frozen=True)
class PutResult:
    """Metadata returned after writing a memo entry."""

    inserted: bool
    run_id: str
    key: str
    namespace: str
    value_hash: str


@dataclass(frozen=True)
class MemoLookupResult:
    """Lookup result used by retrieval tools and diagnostics."""

    found: bool
    run_id: str
    key: str
    namespace: str
    value: Any | None
    value_hash: str | None


class SQLiteMemoStore:
    """SQLite implementation of run-scoped memo storage."""

    def __init__(self, db_path: str = ".tmp/memo_store.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger("langgraph.memo_store")
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_schema(self) -> None:
        """Create memo table/index schema if absent."""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memo_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    value_hash TEXT NOT NULL,
                    source_tool TEXT NOT NULL,
                    step INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS uq_memo_entries_run_key
                ON memo_entries(run_id, namespace, key);
                """
            )

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

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memo_entries (
                    run_id, namespace, key, value_json, value_hash, source_tool, step, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, namespace, key) DO UPDATE SET
                    value_json=excluded.value_json,
                    value_hash=excluded.value_hash,
                    source_tool=excluded.source_tool,
                    step=excluded.step,
                    created_at=excluded.created_at
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
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT value_json, value_hash
                FROM memo_entries
                WHERE run_id = ? AND namespace = ? AND key = ?
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
            value=json.loads(row["value_json"]),
            value_hash=row["value_hash"],
        )

    def get_latest(self, *, key: str, namespace: str = "run") -> MemoLookupResult:
        """Retrieve latest memoized value by key across all run ids."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT run_id, value_json, value_hash
                FROM memo_entries
                WHERE namespace = ? AND key = ?
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

        run_id = str(row["run_id"])
        self.logger.info(
            "MEMO GET LATEST HIT run_id=%s namespace=%s key=%s", run_id, namespace, key
        )
        return MemoLookupResult(
            found=True,
            run_id=run_id,
            key=key,
            namespace=namespace,
            value=json.loads(row["value_json"]),
            value_hash=row["value_hash"],
        )

    def list_entries(self, *, run_id: str, namespace: str = "run") -> list[dict[str, Any]]:
        """List memo metadata for visibility/reporting (no model call required)."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT key, value_hash, source_tool, step, created_at
                FROM memo_entries
                WHERE run_id = ? AND namespace = ?
                ORDER BY step ASC, id ASC
                """,
                (run_id, namespace),
            ).fetchall()
        entries = [dict(row) for row in rows]
        self.logger.info(
            "MEMO LIST run_id=%s namespace=%s count=%s",
            run_id,
            namespace,
            len(entries),
        )
        return entries
