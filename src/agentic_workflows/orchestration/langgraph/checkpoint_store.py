from __future__ import annotations

"""Durable checkpoint persistence for Phase 1 graph runs.

This store is intentionally simple (SQLite) while keeping a stable interface for
future backend replacement (for example Postgres).

Uses a persistent connection with WAL journal mode for performance (W2-3).
"""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from agentic_workflows.orchestration.langgraph.state_schema import RunState, utc_now_iso

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS graph_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    step INTEGER NOT NULL,
    node_name TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_graph_checkpoints_run_step
ON graph_checkpoints(run_id, step);
"""


def _json_default(x: Any) -> Any:
    """JSON serializer that handles sets (sorted list) and falls back to str."""
    if isinstance(x, set):
        return sorted(x)
    return str(x)


class SQLiteCheckpointStore:
    """Persist node-level state snapshots for replay and debugging.

    Uses a single persistent connection with WAL journal mode and a threading
    lock, matching the pattern from SQLiteRunStore in storage/sqlite.py.
    """

    def __init__(self, db_path: str = ".tmp/langgraph_checkpoints.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def save(self, *, run_id: str, step: int, node_name: str, state: RunState) -> None:
        """Write a checkpoint snapshot for a specific node transition."""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO graph_checkpoints (run_id, step, node_name, state_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    step,
                    node_name,
                    json.dumps(state, sort_keys=True, default=_json_default),
                    utc_now_iso(),
                ),
            )
            self._conn.commit()

    def load_latest(self, run_id: str) -> RunState | None:
        """Load the most recent checkpointed state for a run."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT state_json
                FROM graph_checkpoints
                WHERE run_id = ?
                ORDER BY step DESC, id DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["state_json"])

    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        """Return lightweight checkpoint metadata for timeline inspection."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT step, node_name, created_at
                FROM graph_checkpoints
                WHERE run_id = ?
                ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        """Query distinct run_ids ordered by most recent checkpoint."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT run_id, MAX(step) AS step_count, node_name, MAX(created_at) AS timestamp
                FROM graph_checkpoints
                GROUP BY run_id
                ORDER BY MAX(id) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def load_latest_run(self) -> RunState | None:
        """Load the final state of the most recent run (any run_id)."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT state_json
                FROM graph_checkpoints
                ORDER BY id DESC
                LIMIT 1
                """,
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["state_json"])

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()
