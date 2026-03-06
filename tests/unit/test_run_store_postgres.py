"""Unit tests for PostgresRunStore.

All tests require a live Postgres database (DATABASE_URL env var).
Skipped automatically when DATABASE_URL is not set or psycopg_pool is not installed.
"""

from __future__ import annotations

import os

import pytest

# Skip entire module if psycopg_pool is not installed
pytest.importorskip("psycopg_pool")

from agentic_workflows.storage.postgres import PostgresRunStore  # noqa: E402

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set -- skipping Postgres tests",
)


@requires_postgres
@pytest.mark.postgres
class TestPostgresRunStore:
    """PostgresRunStore async CRUD operations against a real Postgres database."""

    async def test_save_and_get_roundtrip(self, pg_pool, clean_pg):
        """save_run + get_run round-trip preserves all fields."""
        store = PostgresRunStore(pg_pool)
        await store.initialize()

        await store.save_run("run-1", status="pending", user_input="hello world")
        result = await store.get_run("run-1")

        assert result is not None
        assert result["run_id"] == "run-1"
        assert result["status"] == "pending"
        assert result["user_input"] == "hello world"

    async def test_list_runs_newest_first_with_limit(self, pg_pool, clean_pg):
        """list_runs returns runs newest-first, respecting limit."""
        store = PostgresRunStore(pg_pool)

        await store.save_run("run-a", status="pending", user_input="first")
        await store.save_run("run-b", status="pending", user_input="second")
        await store.save_run("run-c", status="pending", user_input="third")

        runs = await store.list_runs(limit=2)
        assert len(runs) == 2
        # Newest first: run-c, run-b
        assert runs[0]["run_id"] == "run-c"
        assert runs[1]["run_id"] == "run-b"

    async def test_list_runs_cursor_pagination(self, pg_pool, clean_pg):
        """list_runs with cursor returns only runs older than the cursor."""
        store = PostgresRunStore(pg_pool)

        await store.save_run("run-x", status="pending", user_input="oldest")
        await store.save_run("run-y", status="pending", user_input="middle")
        await store.save_run("run-z", status="pending", user_input="newest")

        # Paginate from the middle: should return only run-x (older than run-y)
        runs = await store.list_runs(limit=10, cursor="run-y")
        run_ids = [r["run_id"] for r in runs]
        assert "run-x" in run_ids
        assert "run-y" not in run_ids
        assert "run-z" not in run_ids

    async def test_update_run_reflects_changes(self, pg_pool, clean_pg):
        """update_run modifies fields; get_run reflects the changes."""
        store = PostgresRunStore(pg_pool)

        await store.save_run("run-upd", status="pending", user_input="to update")
        await store.update_run("run-upd", status="completed", missions_completed=3)

        result = await store.get_run("run-upd")
        assert result is not None
        assert result["status"] == "completed"
        assert result["missions_completed"] == 3

    async def test_get_run_returns_none_for_unknown(self, pg_pool, clean_pg):
        """get_run returns None for a run_id that does not exist."""
        store = PostgresRunStore(pg_pool)
        assert await store.get_run("nonexistent-run-id") is None
