"""Unit tests for SQLiteRunStore."""

from __future__ import annotations

import asyncio
import json
import unittest.mock

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


@pytest.mark.asyncio
async def test_large_result_truncated(store):
    """RunResult > 512KB stores truncated tool_history; mission_reports intact."""
    # Build a result dict with tools_used containing 100 entries each with ~6KB result
    large_tool_entry = {
        "tool": "read_file",
        "args": {"path": "/some/file.txt"},
        "result": {"content": "x" * 6000},
    }
    large_result = {
        "answer": "done",
        "tools_used": [dict(large_tool_entry) for _ in range(100)],
        "mission_report": [{"mission_id": "m1", "result": "completed"}],
    }
    await store.save_run("large-r1", status="completed", result=large_result)
    row = await store.get_run("large-r1")
    assert row is not None
    stored = json.loads(row["result_json"])
    # tool_history should be truncated
    assert stored["tools_used"][0].get("result_truncated") is True
    # mission_reports must remain intact
    assert stored["mission_report"][0]["mission_id"] == "m1"
    # answer must remain
    assert stored["answer"] == "done"


@pytest.mark.asyncio
async def test_large_result_warning_logged(store, caplog):
    """Large RunResult triggers a structlog warning (captured via Python logging bridge)."""
    import logging

    large_tool_entry = {
        "tool": "read_file",
        "args": {"path": "/some/file.txt"},
        "result": {"content": "x" * 6000},
    }
    large_result = {
        "answer": "done",
        "tools_used": [dict(large_tool_entry) for _ in range(100)],
        "mission_report": [],
    }
    # structlog may log via Python stdlib logging; capture at WARNING level
    with caplog.at_level(logging.WARNING):
        await store.save_run("large-r2", status="completed", result=large_result)

    # Check for the warning key either in caplog records or via a mock approach
    # Since structlog may not bridge to caplog, use mock patching of _log.warning
    # This test verifies structlog warning is called by patching at module level
    import agentic_workflows.storage.sqlite as sqlite_mod

    with unittest.mock.patch.object(sqlite_mod._log, "warning") as mock_warn:
        large_result2 = {
            "answer": "done",
            "tools_used": [dict(large_tool_entry) for _ in range(100)],
            "mission_report": [],
        }
        await store.save_run("large-r3", status="completed", result=large_result2)
        assert mock_warn.called, "Expected structlog warning to be called for large result"
        call_args = mock_warn.call_args
        # First positional arg should be the event key
        assert "run_store.result_truncated" in str(call_args)


@pytest.mark.asyncio
async def test_result_under_limit_not_truncated(store):
    """Small RunResult is stored without modification."""
    small_result = {
        "answer": "done",
        "tools_used": [{"tool": "read_file", "args": {}, "result": {"content": "small"}}],
        "mission_report": [{"mission_id": "m1"}],
    }
    await store.save_run("small-r1", status="completed", result=small_result)
    row = await store.get_run("small-r1")
    assert row is not None
    stored = json.loads(row["result_json"])
    # Should NOT have result_truncated key
    assert "result_truncated" not in stored["tools_used"][0]
    assert stored["tools_used"][0]["result"] == {"content": "small"}


@pytest.mark.asyncio
async def test_concurrent_update_run(store):
    """5 simultaneous update_run calls complete without OperationalError."""
    await store.save_run("conc", status="running")
    results = await asyncio.gather(
        *[store.update_run("conc", status="running", missions_completed=i) for i in range(5)],
        return_exceptions=True,
    )
    errors = [r for r in results if isinstance(r, Exception)]
    assert errors == [], f"Concurrent update_run raised: {errors}"
    row = await store.get_run("conc")
    assert row["status"] == "running"  # all updates used same status


@pytest.mark.asyncio
async def test_makedirs_on_init(tmp_path):
    """SQLiteRunStore must not crash if its parent directory does not yet exist."""
    db_path = str(tmp_path / "nonexistent_subdir" / "runs.db")
    store = SQLiteRunStore(db_path=db_path)
    await store.save_run("init-test", status="running")
    row = await store.get_run("init-test")
    assert row is not None
    store.close()
