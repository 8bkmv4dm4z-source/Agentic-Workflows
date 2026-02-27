from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import sqlite3
from typing import Any

from execution.langgraph.state_schema import hash_json


@dataclass(frozen=True)
class PutResult:
    inserted: bool
    run_id: str
    key: str
    namespace: str
    value_hash: str


@dataclass(frozen=True)
class MemoLookupResult:
    found: bool
    run_id: str
    key: str
    namespace: str
    value: Any | None
    value_hash: str | None


class SQLiteMemoStore:
    def __init__(self, db_path: str = ".tmp/memo_store.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_schema(self) -> None:
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
        value_json = json.dumps(value, sort_keys=True, default=str)
        value_hash = hash_json(value)
        timestamp = created_at or ""
        if not timestamp:
            from execution.langgraph.state_schema import utc_now_iso

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

        return PutResult(
            inserted=True,
            run_id=run_id,
            key=key,
            namespace=namespace,
            value_hash=value_hash,
        )

    def get(self, *, run_id: str, key: str, namespace: str = "run") -> MemoLookupResult:
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
            return MemoLookupResult(
                found=False,
                run_id=run_id,
                key=key,
                namespace=namespace,
                value=None,
                value_hash=None,
            )

        return MemoLookupResult(
            found=True,
            run_id=run_id,
            key=key,
            namespace=namespace,
            value=json.loads(row["value_json"]),
            value_hash=row["value_hash"],
        )
