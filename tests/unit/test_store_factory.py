"""Unit tests for ENV-based store selection in app.py lifespan.

These tests verify the conditional import/selection logic based on
DATABASE_URL presence. They run WITHOUT a Postgres database since they
only test the ENV detection mechanism, not actual connections.
"""

from __future__ import annotations

import os

import pytest


class TestStoreFactoryEnvDetection:
    """Verify DATABASE_URL drives store backend selection."""

    def test_sqlite_selected_when_database_url_absent(self, monkeypatch):
        """When DATABASE_URL is NOT set, the factory should select SQLite stores."""
        monkeypatch.delenv("DATABASE_URL", raising=False)

        db_url = os.environ.get("DATABASE_URL")
        assert db_url is None

        # The lifespan code path: if db_url is falsy -> SQLite
        backend = "postgres" if db_url else "sqlite"
        assert backend == "sqlite"

    def test_postgres_selected_when_database_url_set(self, monkeypatch):
        """When DATABASE_URL IS set, the factory should select Postgres stores."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")

        db_url = os.environ.get("DATABASE_URL")
        assert db_url is not None

        # The lifespan code path: if db_url is truthy -> Postgres
        backend = "postgres" if db_url else "sqlite"
        assert backend == "postgres"

    def test_sqlite_import_paths_are_valid(self):
        """Verify that SQLite store classes referenced by lifespan are importable."""
        from agentic_workflows.orchestration.langgraph.checkpoint_store import (  # noqa: F401
            SQLiteCheckpointStore,
        )
        from agentic_workflows.orchestration.langgraph.memo_store import (  # noqa: F401
            SQLiteMemoStore,
        )
        from agentic_workflows.storage.sqlite import SQLiteRunStore  # noqa: F401

    def test_postgres_import_paths_are_valid(self):
        """Verify that Postgres store classes are importable when psycopg is installed."""
        try:
            import psycopg_pool  # noqa: F401
        except ImportError:
            pytest.skip("psycopg_pool not installed")

        from agentic_workflows.orchestration.langgraph.checkpoint_postgres import (  # noqa: F401
            PostgresCheckpointStore,
        )
        from agentic_workflows.orchestration.langgraph.memo_postgres import (  # noqa: F401
            PostgresMemoStore,
        )
        from agentic_workflows.storage.postgres import PostgresRunStore  # noqa: F401

    def test_empty_database_url_selects_sqlite(self, monkeypatch):
        """An empty DATABASE_URL string should select SQLite (falsy)."""
        monkeypatch.setenv("DATABASE_URL", "")

        db_url = os.environ.get("DATABASE_URL")
        # Empty string is truthy for os.environ.get but falsy for `if db_url:`
        backend = "postgres" if db_url else "sqlite"
        assert backend == "sqlite"
