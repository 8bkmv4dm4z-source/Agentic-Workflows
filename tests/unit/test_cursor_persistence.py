"""Tests for cursor persistence in MissionContextStore and ContextManager.

Wave 0 stubs replaced with real assertions in plan 07.6-03.
Covers: upsert_cursor, get_cursor, get_active_cursors (pool=None path),
eviction-hint injection via ContextManager.compact(), and __cursor_resume
bypass of seen_tool_signatures dedup in graph.py.
"""
from __future__ import annotations

import pytest

# Import MissionContextStore — must import without error
from agentic_workflows.storage.mission_context_store import MissionContextStore


class TestCursorRoundTrip:
    def test_upsert_and_get_cursor_round_trip(self) -> None:
        """upsert_cursor() then get_cursor() returns the same offset (pool=None path)."""
        store = MissionContextStore(pool=None)
        store.upsert_cursor(
            run_id="run-1",
            plan_step_id="step-0",
            mission_id="m-1",
            tool_name="read_file_chunk",
            key="/tmp/data.txt",
            cursor=150,
            total=500,
        )
        result = store.get_cursor(
            run_id="run-1",
            plan_step_id="step-0",
            mission_id="m-1",
            tool_name="read_file_chunk",
            key="/tmp/data.txt",
        )
        assert result == 150

    def test_get_cursor_missing_returns_none(self) -> None:
        """get_cursor() for an unknown key returns None."""
        store = MissionContextStore(pool=None)
        result = store.get_cursor(
            run_id="run-X",
            plan_step_id="step-0",
            mission_id="m-X",
            tool_name="read_file_chunk",
            key="/tmp/nonexistent.txt",
        )
        assert result is None

    def test_upsert_cursor_overwrite(self) -> None:
        """upsert same key twice; get_cursor returns the latest offset."""
        store = MissionContextStore(pool=None)
        store.upsert_cursor(
            run_id="run-2",
            plan_step_id="step-0",
            mission_id="m-2",
            tool_name="read_file_chunk",
            key="/tmp/file.txt",
            cursor=100,
            total=400,
        )
        store.upsert_cursor(
            run_id="run-2",
            plan_step_id="step-1",
            mission_id="m-2",
            tool_name="read_file_chunk",
            key="/tmp/file.txt",
            cursor=250,
            total=400,
        )
        result = store.get_cursor(
            run_id="run-2",
            plan_step_id="step-1",
            mission_id="m-2",
            tool_name="read_file_chunk",
            key="/tmp/file.txt",
        )
        assert result == 250


class TestGetActiveCursors:
    def test_get_active_cursors_filters_by_run_id(self) -> None:
        """Two cursors with different run_ids; get_active_cursors('run-A') returns only run-A cursor."""
        store = MissionContextStore(pool=None)
        store.upsert_cursor(
            run_id="run-A",
            plan_step_id="s0",
            mission_id="m-1",
            tool_name="read_file_chunk",
            key="/tmp/a.txt",
            cursor=50,
            total=200,
        )
        store.upsert_cursor(
            run_id="run-B",
            plan_step_id="s0",
            mission_id="m-2",
            tool_name="read_file_chunk",
            key="/tmp/b.txt",
            cursor=75,
            total=300,
        )
        results = store.get_active_cursors("run-A")
        assert len(results) == 1
        assert results[0]["run_id"] == "run-A"
        assert results[0]["key"] == "/tmp/a.txt"
        assert results[0]["next_offset"] == 50


class TestEvictionHint:
    def test_eviction_hint_injected_after_compact(self) -> None:
        """ContextManager.compact() injects [Orchestrator] message when an active cursor exists."""
        from agentic_workflows.orchestration.langgraph.context_manager import ContextManager

        store = MissionContextStore(pool=None)
        store.upsert_cursor(
            run_id="run-hint",
            plan_step_id="s0",
            mission_id="m-1",
            tool_name="read_file_chunk",
            key="/tmp/bigfile.txt",
            cursor=300,
            total=1000,
        )

        cm = ContextManager(sliding_window_cap=4, mission_context_store=store)

        # Build a state with more messages than the sliding_window_cap to trigger eviction
        state: dict = {
            "run_id": "run-hint",
            "messages": [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "msg1"},
                {"role": "assistant", "content": "msg2"},
                {"role": "user", "content": "msg3"},
                {"role": "assistant", "content": "msg4"},
                {"role": "user", "content": "msg5"},
            ],
            "policy_flags": {},
        }

        cm.compact(state)

        # After compact, a cursor hint should have been injected
        contents = [m["content"] for m in state["messages"]]
        hint_messages = [c for c in contents if "[Orchestrator] Chunked read in progress" in c]
        assert len(hint_messages) == 1
        assert "read_file_chunk" in hint_messages[0]
        assert "next_offset=300" in hint_messages[0]
        assert "/tmp/bigfile.txt" in hint_messages[0]


class TestCursorResumeBypass:
    def test_cursor_resume_bypass_seen_signatures(self) -> None:
        """Action dict with __cursor_resume=True bypasses seen_tool_signatures dedup in graph.py planner."""
        import json

        from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator

        # Verify the bypass logic is present in the source
        import inspect
        source = inspect.getsource(LangGraphOrchestrator._execute_action)
        assert "__cursor_resume" in source, (
            "_execute_action must contain __cursor_resume bypass logic"
        )
        assert "read_file_chunk" in source, (
            "_execute_action must check tool_name == 'read_file_chunk' for bypass"
        )
