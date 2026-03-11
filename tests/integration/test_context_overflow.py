"""Wave 0 integration test stubs for BTLNK-01: large-result planner context cap.

All tests raise NotImplementedError — RED state. Implement in Plan 05.
Requires psycopg_pool (Postgres). Skipped in SQLite-only CI environments.
"""
from __future__ import annotations

import pytest

psycopg_pool = pytest.importorskip("psycopg_pool")

requires_postgres = pytest.mark.skipif(
    True,  # Always skip until Plan 05 implements these
    reason="Stub — implement in Plan 05",
)


@requires_postgres
def test_large_result_never_reaches_planner_raw() -> None:
    """After a tool returns >2000 chars, planner injection contains compact pointer not raw result."""
    raise NotImplementedError("stub — implement in Plan 05")


@requires_postgres
def test_full_result_retrievable_from_cache() -> None:
    """After truncation, ToolResultCache.get() returns the original full result."""
    raise NotImplementedError("stub — implement in Plan 05")
