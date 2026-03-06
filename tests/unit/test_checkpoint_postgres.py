"""Unit tests for PostgresCheckpointStore.

All tests require a live Postgres database (DATABASE_URL env var).
Skipped automatically when DATABASE_URL is not set or psycopg_pool is not installed.
"""

from __future__ import annotations

import os

import pytest

# Skip entire module if psycopg_pool is not installed
pytest.importorskip("psycopg_pool")

from agentic_workflows.orchestration.langgraph.checkpoint_postgres import (  # noqa: E402
    PostgresCheckpointStore,
)
from agentic_workflows.orchestration.langgraph.state_schema import new_run_state  # noqa: E402

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set -- skipping Postgres tests",
)


@requires_postgres
@pytest.mark.postgres
class TestPostgresCheckpointStore:
    """PostgresCheckpointStore CRUD operations against a real Postgres database."""

    def test_save_and_load_latest_roundtrip(self, pg_pool, clean_pg):
        """save() + load_latest() round-trip preserves mission_text in state."""
        store = PostgresCheckpointStore(pg_pool)
        state = new_run_state("test mission", "test-run-1")
        store.save(run_id="test-run-1", step=1, node_name="plan", state=state)

        loaded = store.load_latest("test-run-1")
        assert loaded is not None
        assert loaded["run_id"] == "test-run-1"
        assert loaded["missions"][0] == "test mission"

    def test_load_latest_returns_highest_step(self, pg_pool, clean_pg):
        """When multiple steps exist, load_latest returns the highest step."""
        store = PostgresCheckpointStore(pg_pool)
        state1 = new_run_state("mission step 1", "run-step")
        state2 = new_run_state("mission step 2", "run-step")
        state2["step"] = 2

        store.save(run_id="run-step", step=1, node_name="plan", state=state1)
        store.save(run_id="run-step", step=2, node_name="execute", state=state2)

        loaded = store.load_latest("run-step")
        assert loaded is not None
        assert loaded["step"] == 2

    def test_list_checkpoints_returns_all_for_run(self, pg_pool, clean_pg):
        """list_checkpoints returns all checkpoint metadata for a given run_id."""
        store = PostgresCheckpointStore(pg_pool)
        state = new_run_state("list test", "run-list")

        store.save(run_id="run-list", step=1, node_name="plan", state=state)
        store.save(run_id="run-list", step=2, node_name="execute", state=state)
        store.save(run_id="run-list", step=3, node_name="evaluate", state=state)

        checkpoints = store.list_checkpoints("run-list")
        assert len(checkpoints) == 3
        assert checkpoints[0]["node_name"] == "plan"
        assert checkpoints[1]["node_name"] == "execute"
        assert checkpoints[2]["node_name"] == "evaluate"

    def test_list_runs_returns_distinct_run_ids(self, pg_pool, clean_pg):
        """list_runs returns distinct run_ids with metadata."""
        store = PostgresCheckpointStore(pg_pool)
        state = new_run_state("multi-run test", "run-a")

        store.save(run_id="run-a", step=1, node_name="plan", state=state)
        store.save(run_id="run-b", step=1, node_name="plan", state=state)

        runs = store.list_runs()
        run_ids = [r["run_id"] for r in runs]
        assert "run-a" in run_ids
        assert "run-b" in run_ids
        assert len(runs) >= 2

    def test_load_latest_run_returns_most_recent(self, pg_pool, clean_pg):
        """load_latest_run returns the most recently saved checkpoint state."""
        store = PostgresCheckpointStore(pg_pool)
        state_a = new_run_state("first run", "run-first")
        state_b = new_run_state("second run", "run-second")

        store.save(run_id="run-first", step=1, node_name="plan", state=state_a)
        store.save(run_id="run-second", step=1, node_name="plan", state=state_b)

        latest = store.load_latest_run()
        assert latest is not None
        assert latest["missions"][0] == "second run"

    def test_load_latest_returns_none_for_unknown(self, pg_pool, clean_pg):
        """load_latest returns None for a run_id that does not exist."""
        store = PostgresCheckpointStore(pg_pool)
        assert store.load_latest("nonexistent-run-id") is None
