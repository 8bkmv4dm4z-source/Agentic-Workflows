"""Shared test fixtures for the agentic-workflows test suite."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agentic_workflows.orchestration.langgraph.checkpoint_store import SQLiteCheckpointStore
from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory that is cleaned up after the test."""
    return tmp_path


@pytest.fixture
def memo_store(tmp_path: Path) -> SQLiteMemoStore:
    """Provide a fresh SQLiteMemoStore backed by a temp database."""
    return SQLiteMemoStore(db_path=str(tmp_path / "memo.db"))


@pytest.fixture
def checkpoint_store(tmp_path: Path) -> SQLiteCheckpointStore:
    """Provide a fresh SQLiteCheckpointStore backed by a temp database."""
    return SQLiteCheckpointStore(db_path=str(tmp_path / "checkpoints.db"))


class ScriptedProvider:
    """Test provider that returns pre-scripted JSON responses."""

    def __init__(self, responses: list[dict]) -> None:
        self._responses = [json.dumps(item) for item in responses]
        self._index = 0

    def generate(self, messages):  # noqa: ANN001
        if self._index < len(self._responses):
            value = self._responses[self._index]
            self._index += 1
            return value
        return self._responses[-1]


# ---------------------------------------------------------------------------
# Postgres fixtures (skipped when DATABASE_URL is not set)
# ---------------------------------------------------------------------------

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set -- skipping Postgres tests",
)


@pytest.fixture(scope="session")
def pg_pool():
    """Create a psycopg ConnectionPool for Postgres tests.

    The pool is opened once per test session and closed on teardown.
    Tables are created via the 001_init.sql migration (idempotent).
    """
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        pytest.skip("DATABASE_URL not set")

    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(
        conninfo=db_url,
        min_size=1,
        max_size=5,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    pool.open(wait=True)

    # Apply migrations (idempotent CREATE IF NOT EXISTS)
    migration_path = Path(__file__).resolve().parent.parent / "db" / "migrations" / "001_init.sql"
    if migration_path.exists():
        sql = migration_path.read_text()
        with pool.connection() as conn:
            conn.execute(sql, prepare=False)

    yield pool

    pool.close()


@pytest.fixture
def clean_pg(pg_pool):
    """Truncate all Postgres tables between tests for clean state."""
    with pg_pool.connection() as conn:
        conn.execute("TRUNCATE graph_checkpoints, runs, memo_entries")
    yield
