"""Unit tests for SQLiteRunStore."""

from __future__ import annotations

import os

import pytest

from agentic_workflows.storage.sqlite import SQLiteRunStore


@pytest.fixture
def store(tmp_path):
    """Create an isolated SQLiteRunStore in a temp directory."""
    db_path = str(tmp_path / "test_runs.db")
    s = SQLiteRunStore(db_path=db_path)
    yield s
    s.close()


@pytest.mark.asyncio
async def test_save_and_get_run(store):
    await store.save_run("r1", status="pending", user_input="hello world")
    row = await store.get_run("r1")
    assert row is not None
    assert row["run_id"] == "r1"
    assert row["status"] == "pending"
    assert row["user_input"] == "hello world"
    assert row["created_at"] is not None


@pytest.mark.asyncio
async def test_update_run(store):
    await store.save_run("r2", status="pending")
    await store.update_run("r2", status="completed", missions_completed=3)
    row = await store.get_run("r2")
    assert row is not None
    assert row["status"] == "completed"
    assert row["missions_completed"] == 3


@pytest.mark.asyncio
async def test_list_runs(store):
    for i in range(3):
        await store.save_run(f"r{i}", status="completed")
    runs = await store.list_runs(limit=2)
    assert len(runs) == 2
    # Most recent first (r2 created last)
    assert runs[0]["run_id"] == "r2"


@pytest.mark.asyncio
async def test_get_nonexistent_run(store):
    row = await store.get_run("does-not-exist")
    assert row is None


@pytest.mark.asyncio
async def test_wal_mode(store):
    """Verify WAL journal mode is active."""
    result = store._conn.execute("PRAGMA journal_mode").fetchone()
    assert result[0] == "wal"


@pytest.mark.asyncio
async def test_save_run_with_json_fields(store):
    await store.save_run(
        "r-json",
        status="completed",
        prior_context=[{"role": "user", "content": "hi"}],
        tools_used=["search_files", "write_file"],
        result={"answer": "done", "tools_used": []},
    )
    row = await store.get_run("r-json")
    assert row is not None
    # JSON columns stored as strings
    assert '"role"' in row["prior_context_json"]
    assert '"search_files"' in row["tools_used_json"]
