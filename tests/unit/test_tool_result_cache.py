"""Wave 0 test stubs for BTLNK-02: ToolResultCache store/get/TTL/pool-none.

All tests raise NotImplementedError — RED state. Implement in Plan 03/04.
"""
from __future__ import annotations

try:
    from agentic_workflows.storage.tool_result_cache import ToolResultCache
except ImportError:
    ToolResultCache = None  # type: ignore


class TestToolResultCacheRoundTrip:
    def test_store_and_get_round_trip(self) -> None:
        """store result then get by same key returns the full result."""
        raise NotImplementedError("stub — implement in Plan 03/04")

    def test_get_returns_none_on_miss(self) -> None:
        """get() for unknown key returns None."""
        raise NotImplementedError("stub — implement in Plan 03/04")

    def test_get_deletes_expired_and_returns_none(self) -> None:
        """store with expires_at in the past then get() returns None."""
        raise NotImplementedError("stub — implement in Plan 03/04")


class TestToolResultCachePoolNone:
    def test_pool_none_store_is_noop(self) -> None:
        """ToolResultCache(pool=None).store(...) does not raise."""
        raise NotImplementedError("stub — implement in Plan 03/04")

    def test_pool_none_get_returns_none(self) -> None:
        """ToolResultCache(pool=None).get(...) returns None."""
        raise NotImplementedError("stub — implement in Plan 03/04")


class TestToolResultCacheArgsHash:
    def test_args_hash_is_stable(self) -> None:
        """Same tool_name + args always produce the same cache key."""
        raise NotImplementedError("stub — implement in Plan 03/04")


class TestStructuralHealthTruncations:
    def test_structural_health_truncations_increments(self) -> None:
        """After ContextManager intercepts a large result, structural_health['tool_result_truncations'] == 1."""

        def _test() -> None:
            from agentic_workflows.orchestration.langgraph.context_manager import ContextManager  # noqa: F401
            from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator  # noqa: F401

        _test()
        raise NotImplementedError("stub — implement in Plan 03/04")
