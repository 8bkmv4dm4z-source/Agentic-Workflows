"""Unit tests for PostgresMemoStore.

All tests require a live Postgres database (DATABASE_URL env var).
Skipped automatically when DATABASE_URL is not set or psycopg_pool is not installed.
"""

from __future__ import annotations

import os

import pytest

# Skip entire module if psycopg_pool is not installed
pytest.importorskip("psycopg_pool")

from agentic_workflows.orchestration.langgraph.memo_postgres import (  # noqa: E402
    PostgresMemoStore,
)

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set -- skipping Postgres tests",
)


@requires_postgres
@pytest.mark.postgres
class TestPostgresMemoStore:
    """PostgresMemoStore CRUD operations against a real Postgres database."""

    def test_put_and_get_roundtrip(self, pg_pool, clean_pg):
        """put + get round-trip preserves value and hash."""
        store = PostgresMemoStore(pg_pool)
        put_result = store.put(run_id="run-1", key="k1", value={"data": 42})

        assert put_result.inserted is True
        assert put_result.key == "k1"
        assert put_result.namespace == "run"
        assert put_result.value_hash  # non-empty hash

        get_result = store.get(run_id="run-1", key="k1")
        assert get_result.found is True
        assert get_result.value == {"data": 42}
        assert get_result.value_hash == put_result.value_hash

    def test_put_upsert_updates_value(self, pg_pool, clean_pg):
        """put with same key updates the value (upsert behavior)."""
        store = PostgresMemoStore(pg_pool)
        store.put(run_id="run-u", key="k1", value={"v": 1})
        store.put(run_id="run-u", key="k1", value={"v": 2})

        result = store.get(run_id="run-u", key="k1")
        assert result.found is True
        assert result.value == {"v": 2}

    def test_get_returns_not_found_for_missing_key(self, pg_pool, clean_pg):
        """get returns found=False for a key that does not exist."""
        store = PostgresMemoStore(pg_pool)
        result = store.get(run_id="run-miss", key="nonexistent")
        assert result.found is False
        assert result.value is None
        assert result.value_hash is None

    def test_get_latest_returns_most_recent_across_runs(self, pg_pool, clean_pg):
        """get_latest returns the most recent entry across different run_ids."""
        store = PostgresMemoStore(pg_pool)
        store.put(run_id="run-old", key="shared-key", value={"v": "old"})
        store.put(run_id="run-new", key="shared-key", value={"v": "new"})

        result = store.get_latest(key="shared-key")
        assert result.found is True
        assert result.value == {"v": "new"}
        assert result.run_id == "run-new"

    def test_list_entries_returns_entries_for_run(self, pg_pool, clean_pg):
        """list_entries returns all entries for a run in order."""
        store = PostgresMemoStore(pg_pool)
        store.put(run_id="run-list", key="k1", value={"a": 1}, step=0)
        store.put(run_id="run-list", key="k2", value={"b": 2}, step=1)
        store.put(run_id="run-list", key="k3", value={"c": 3}, step=2)

        entries = store.list_entries(run_id="run-list")
        assert len(entries) == 3
        keys = [e["key"] for e in entries]
        assert keys == ["k1", "k2", "k3"]

    def test_delete_removes_entry(self, pg_pool, clean_pg):
        """delete removes entry; get returns found=False afterwards."""
        store = PostgresMemoStore(pg_pool)
        store.put(run_id="run-del", key="k1", value={"x": 1})

        deleted = store.delete(run_id="run-del", key="k1")
        assert deleted == 1

        result = store.get(run_id="run-del", key="k1")
        assert result.found is False

    def test_delete_with_value_hash_only_deletes_matching(self, pg_pool, clean_pg):
        """delete with value_hash only removes entry if hash matches."""
        store = PostgresMemoStore(pg_pool)
        put_result = store.put(run_id="run-hash", key="k1", value={"x": 1})
        real_hash = put_result.value_hash

        # Wrong hash: should not delete
        deleted = store.delete(run_id="run-hash", key="k1", value_hash="wrong-hash")
        assert deleted == 0

        # Correct hash: should delete
        deleted = store.delete(run_id="run-hash", key="k1", value_hash=real_hash)
        assert deleted == 1

        result = store.get(run_id="run-hash", key="k1")
        assert result.found is False

    def test_get_cache_value_returns_dict(self, pg_pool, clean_pg):
        """get_cache_value returns dict for cache namespace entries."""
        store = PostgresMemoStore(pg_pool)
        store.put(run_id="shared", key="cache-key", value={"cached": True}, namespace="cache")

        result = store.get_cache_value(key="cache-key")
        assert result is not None
        assert result == {"cached": True}

    def test_get_cache_value_returns_none_for_missing(self, pg_pool, clean_pg):
        """get_cache_value returns None when no cache entry exists."""
        store = PostgresMemoStore(pg_pool)
        result = store.get_cache_value(key="nonexistent-cache")
        assert result is None
