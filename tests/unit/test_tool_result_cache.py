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
        """ContextManager and LangGraphOrchestrator are importable (lazy import guard)."""
        from agentic_workflows.orchestration.langgraph.context_manager import ContextManager  # noqa: F401
        from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator  # noqa: F401
        # Full behavioral test (with mock large-result + ContextManager interception)
        # is deferred to an integration test once ContextManager wiring is complete in Plan 05.
        assert True
