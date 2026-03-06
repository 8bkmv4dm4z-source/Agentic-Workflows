"""PostgresCheckpointStore -- Postgres implementation of CheckpointStore.

Mirrors the SQLiteCheckpointStore API exactly, using psycopg + ConnectionPool
for synchronous operations (called from sync graph nodes).
"""

from __future__ import annotations

import json
from typing import Any

from psycopg_pool import ConnectionPool

from agentic_workflows.orchestration.langgraph.state_schema import RunState, utc_now_iso


class PostgresCheckpointStore:
    """Persist node-level state snapshots in Postgres for replay and debugging."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def save(self, *, run_id: str, step: int, node_name: str, state: RunState) -> None:
        """Write a checkpoint snapshot for a specific node transition."""
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO graph_checkpoints (run_id, step, node_name, state_json, created_at)
                VALUES (%s, %s, %s, %s, %s)
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
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT state_json
                FROM graph_checkpoints
                WHERE run_id = %s
                ORDER BY step DESC, id DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        """Return lightweight checkpoint metadata for timeline inspection."""
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT step, node_name, created_at
                FROM graph_checkpoints
                WHERE run_id = %s
                ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
        return [
            {"step": r[0], "node_name": r[1], "created_at": str(r[2])}
            for r in rows
        ]

    def list_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        """Query distinct run_ids ordered by most recent checkpoint."""
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT run_id, MAX(step) AS step_count,
                       MAX(node_name) AS node_name,
                       MAX(created_at) AS timestamp
                FROM graph_checkpoints
                GROUP BY run_id
                ORDER BY MAX(id) DESC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "run_id": r[0],
                "step_count": r[1],
                "node_name": r[2],
                "timestamp": str(r[3]),
            }
            for r in rows
        ]

    def load_latest_run(self) -> RunState | None:
        """Load the final state of the most recent run (any run_id)."""
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT state_json
                FROM graph_checkpoints
                ORDER BY id DESC
                LIMIT 1
                """,
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])
