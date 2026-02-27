from __future__ import annotations

"""Durable checkpoint persistence for Phase 1 graph runs.

This store is intentionally simple (SQLite) while keeping a stable interface for
future backend replacement (for example Postgres).
"""

from pathlib import Path
import json
import sqlite3
from typing import Any

from execution.langgraph.state_schema import RunState, utc_now_iso


class SQLiteCheckpointStore:
    """Persist node-level state snapshots for replay and debugging."""

    def __init__(self, db_path: str = ".tmp/langgraph_checkpoints.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_schema(self) -> None:
        """Create checkpoint table/index if absent."""
        with self._connect() as conn:
            conn.executescript(
                """
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
            )

    def save(self, *, run_id: str, step: int, node_name: str, state: RunState) -> None:
        """Write a checkpoint snapshot for a specific node transition."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO graph_checkpoints (run_id, step, node_name, state_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    step,
                    node_name,
                    json.dumps(state, sort_keys=True, default=str),
                    utc_now_iso(),
                ),
            )

    def load_latest(self, run_id: str) -> RunState | None:
        """Load the most recent checkpointed state for a run."""
        with self._connect() as conn:
            row = conn.execute(
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
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT step, node_name, created_at
                FROM graph_checkpoints
                WHERE run_id = ?
                ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]
