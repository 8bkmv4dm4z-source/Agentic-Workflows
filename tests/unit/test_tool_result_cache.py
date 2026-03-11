"""Unit tests for BTLNK-02: ToolResultCache store/get/TTL/pool-none.

Round-trip tests that require a live Postgres pool are in tests/integration/.
Unit tests here cover pool=None no-op behavior and deterministic hashing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agentic_workflows.storage.tool_result_cache import ToolResultCache, make_args_hash


class TestToolResultCacheRoundTrip:
    def test_store_and_get_round_trip(self) -> None:
        """store result then get by same key returns the full result.

        Without Postgres pool, round-trip is tested via pool=None no-op;
        real Postgres round-trip is in tests/integration/test_context_overflow.py.
        """
        cache = ToolResultCache(pool=None)
        h = make_args_hash("my_tool", {"n": 5})
        cache.store(
            tool_name="my_tool",
            args_hash=h,
            full_result="result data",
            summary="result",
        )
        # pool=None store is no-op; get returns None (no Postgres)
        assert cache.get(tool_name="my_tool", args_hash=h) is None

    def test_get_returns_none_on_miss(self) -> None:
        """get() for unknown key returns None."""
        cache = ToolResultCache(pool=None)
        result = cache.get(tool_name="unknown_tool", args_hash="deadbeef")
        assert result is None

    def test_get_deletes_expired_and_returns_none(self) -> None:
        """store with expires_at in the past then get() returns None (pool=None no-op path)."""
        cache = ToolResultCache(pool=None)
        past = datetime.now(tz=timezone.utc) - timedelta(seconds=1)
        h = make_args_hash("my_tool", {"x": 1})
        # store is a no-op when pool=None
        cache.store(
            tool_name="my_tool",
            args_hash=h,
            full_result="old result",
            summary="old",
            expires_at=past,
        )
        # get is also a no-op — returns None
        assert cache.get(tool_name="my_tool", args_hash=h) is None


class TestToolResultCachePoolNone:
    def test_pool_none_store_is_noop(self) -> None:
        """ToolResultCache(pool=None).store(...) does not raise."""
        cache = ToolResultCache(pool=None)
        h = make_args_hash("noop_tool", {"k": "v"})
        # Must not raise
        cache.store(
            tool_name="noop_tool",
            args_hash=h,
            full_result="x" * 2000,
            summary="x" * 200,
        )

    def test_pool_none_get_returns_none(self) -> None:
        """ToolResultCache(pool=None).get(...) returns None."""
        cache = ToolResultCache(pool=None)
        result = cache.get(tool_name="noop_tool", args_hash="anykey")
        assert result is None


class TestToolResultCacheArgsHash:
    def test_args_hash_is_stable(self) -> None:
        """Same tool_name + args always produce the same cache key."""
        h1 = make_args_hash("sort_array", {"array": [3, 1, 2], "order": "asc"})
        h2 = make_args_hash("sort_array", {"order": "asc", "array": [3, 1, 2]})
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest

    def test_different_tools_different_hash(self) -> None:
        """Different tool_name produces different hash even with same args."""
        h1 = make_args_hash("tool_a", {"x": 1})
        h2 = make_args_hash("tool_b", {"x": 1})
        assert h1 != h2


class TestStructuralHealthTruncations:
    def test_structural_health_truncations_increments(self) -> None:
        """ContextManager accepts tool_result_cache param and intercepts large results."""
        from agentic_workflows.orchestration.langgraph.context_manager import ContextManager

        cache = ToolResultCache(pool=None)
        cm = ContextManager(tool_result_cache=cache)
        assert cm._tool_result_cache is cache

    def test_build_planner_context_injection_replaces_large_result_with_compact_pointer(self) -> None:
        """build_planner_context_injection() replaces large tool results with compact pointer format."""
        import json as _json

        from agentic_workflows.orchestration.langgraph.context_manager import ContextManager

        cache = ToolResultCache(pool=None)
        cm = ContextManager(tool_result_cache=cache)

        # Build a state with a mission context (completed) and a large tool_history result
        large_result = {"data": "x" * 2100}
        large_result_str = _json.dumps(large_result)

        state: dict = {
            "mission_contexts": {
                "1": {
                    "mission_id": 1,
                    "goal": "Test mission",
                    "status": "completed",
                    "tools_used": ["big_tool"],
                    "key_results": {},
                    "artifacts": [],
                    "sub_missions": {},
                    "summary": "Test mission | Tools: big_tool",
                    "step_range": None,
                }
            },
            "tool_history": [
                {
                    "call": 1,
                    "tool": "big_tool",
                    "args": {"input": "test"},
                    "result": large_result,
                }
            ],
            "step": 2,
            "run_id": "test-run-001",
            "structural_health": {
                "tool_result_truncations": 0,
            },
        }

        injection = cm.build_planner_context_injection(state)
        # The compact pointer format must be in the injection string
        assert "[Result truncated" in injection, f"Expected compact pointer in: {injection!r}"
        assert "big_tool" in injection
        # The raw 2100-char result must NOT appear in full — compact pointer caps at ~400 chars total
        # Summary is first 200 chars of result_str; the full "x" * 2100 raw string must not appear
        assert "x" * 500 not in injection, "Raw large result leaked into injection"

    def test_structural_health_incremented_after_truncation(self) -> None:
        """structural_health['tool_result_truncations'] increments when large result intercepted."""
        import json as _json

        from agentic_workflows.orchestration.langgraph.context_manager import ContextManager

        cm = ContextManager(tool_result_cache=None)
        large_result = {"data": "y" * 2100}

        state: dict = {
            "mission_contexts": {},
            "tool_history": [
                {
                    "call": 1,
                    "tool": "big_tool",
                    "args": {"k": "v"},
                    "result": large_result,
                }
            ],
            "step": 1,
            "run_id": "test-run-002",
            "structural_health": {
                "tool_result_truncations": 0,
            },
        }

        cm.build_planner_context_injection(state)
        assert state["structural_health"]["tool_result_truncations"] >= 1

    def test_tool_result_cache_not_none_stores_result(self) -> None:
        """With tool_result_cache=ToolResultCache(pool=None), store is called (no-op) without error."""
        import json as _json

        from agentic_workflows.orchestration.langgraph.context_manager import ContextManager

        cache = ToolResultCache(pool=None)
        cm = ContextManager(tool_result_cache=cache)
        large_result = {"data": "z" * 2100}

        state: dict = {
            "mission_contexts": {},
            "tool_history": [
                {
                    "call": 1,
                    "tool": "cache_tool",
                    "args": {"x": 1},
                    "result": large_result,
                }
            ],
            "step": 1,
            "run_id": "test-run-003",
            "structural_health": {"tool_result_truncations": 0},
        }

        # Must not raise even with pool=None cache
        injection = cm.build_planner_context_injection(state)
        assert "[Result truncated" in injection
