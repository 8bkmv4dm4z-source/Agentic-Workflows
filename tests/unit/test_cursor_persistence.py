"""Wave 0 stub tests for cursor persistence in MissionContextStore.

All tests raise NotImplementedError — RED state until plan 07.6-03 implements
upsert_cursor, get_cursor, get_active_cursors, and eviction-hint injection.
"""
from __future__ import annotations

import pytest

# Import MissionContextStore — must import without error
from agentic_workflows.storage.mission_context_store import MissionContextStore


class TestCursorRoundTrip:
    def test_upsert_and_get_cursor_round_trip(self) -> None:
        """upsert_cursor() then get_cursor() returns the same offset (pool=None path)."""
        raise NotImplementedError("stub — implement in plan 07.6-03")

    def test_get_cursor_missing_returns_none(self) -> None:
        """get_cursor() for an unknown key returns None."""
        raise NotImplementedError("stub — implement in plan 07.6-03")

    def test_upsert_cursor_overwrite(self) -> None:
        """upsert same key twice; get_cursor returns the latest offset."""
        raise NotImplementedError("stub — implement in plan 07.6-03")


class TestGetActiveCursors:
    def test_get_active_cursors_filters_by_run_id(self) -> None:
        """Two cursors with different run_ids; get_active_cursors('run-A') returns only run-A cursor."""
        raise NotImplementedError("stub — implement in plan 07.6-03")


class TestEvictionHint:
    def test_eviction_hint_injected_after_compact(self) -> None:
        """ContextManager.compact() injects [Orchestrator] message when an active cursor exists."""
        raise NotImplementedError("stub — implement in plan 07.6-03")


class TestCursorResumeBypass:
    def test_cursor_resume_bypass_seen_signatures(self) -> None:
        """Action dict with __cursor_resume=True bypasses seen_tool_signatures dedup in graph.py planner."""
        raise NotImplementedError("stub — implement in plan 07.6-03")
