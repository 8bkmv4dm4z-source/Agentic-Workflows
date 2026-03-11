"""Unit tests for RetrieveToolResultTool."""
from __future__ import annotations

from unittest.mock import MagicMock

from agentic_workflows.storage.tool_result_cache import ToolResultCache
from agentic_workflows.tools.retrieve_tool_result import RetrieveToolResultTool


def _make_tool(full_result: str | None) -> RetrieveToolResultTool:
    """Build a RetrieveToolResultTool backed by a mock cache."""
    mock_cache = MagicMock()
    mock_cache.get_by_key.return_value = full_result
    return RetrieveToolResultTool(mock_cache)


class TestRetrieveToolResultToolMiss:
    """Cache miss and invalid args scenarios."""

    def test_missing_key_returns_error(self) -> None:
        tool = _make_tool(None)
        result = tool.execute({})
        assert result == {"error": "key is required"}

    def test_empty_key_returns_error(self) -> None:
        tool = _make_tool(None)
        result = tool.execute({"key": "   "})
        assert result == {"error": "key is required"}

    def test_pool_none_cache_returns_cache_miss_error(self) -> None:
        # ToolResultCache with pool=None always returns None from get_by_key
        cache = ToolResultCache(pool=None)
        tool = RetrieveToolResultTool(cache)
        result = tool.execute({"key": "abc123def456abc1"})
        assert result == {"error": "cache miss — result expired or not found"}

    def test_constructor_with_pool_none_cache_does_not_raise(self) -> None:
        cache = ToolResultCache(pool=None)
        tool = RetrieveToolResultTool(cache)
        assert tool.name == "retrieve_tool_result"


class TestRetrieveToolResultToolChunking:
    """Successful retrieval and chunking scenarios."""

    def test_successful_retrieval_returns_chunk_dict(self) -> None:
        content = "Hello world, this is a test result."
        tool = _make_tool(content)
        result = tool.execute({"key": "abc12345", "offset": 0, "limit": 3000})
        assert result["result"] == content
        assert result["offset"] == 0
        assert result["limit"] == 3000
        assert result["total"] == len(content)
        assert result["has_more"] is False

    def test_has_more_true_when_result_exceeds_chunk(self) -> None:
        content = "A" * 6000
        tool = _make_tool(content)
        result = tool.execute({"key": "abc12345", "offset": 0, "limit": 3000})
        assert result["result"] == content[:3000]
        assert result["offset"] == 0
        assert result["limit"] == 3000
        assert result["total"] == 6000
        assert result["has_more"] is True

    def test_has_more_false_when_chunk_covers_remainder(self) -> None:
        content = "A" * 6000
        tool = _make_tool(content)
        # Second chunk: offset=3000 retrieves last 3000 chars
        result = tool.execute({"key": "abc12345", "offset": 3000, "limit": 3000})
        assert result["result"] == content[3000:]
        assert result["offset"] == 3000
        assert result["total"] == 6000
        assert result["has_more"] is False

    def test_offset_beyond_total_returns_empty_result(self) -> None:
        content = "short"
        tool = _make_tool(content)
        result = tool.execute({"key": "abc12345", "offset": 100, "limit": 3000})
        assert result["result"] == ""
        assert result["total"] == len(content)
        assert result["has_more"] is False

    def test_default_offset_and_limit_applied(self) -> None:
        content = "X" * 100
        tool = _make_tool(content)
        result = tool.execute({"key": "abc12345"})
        assert result["result"] == content
        assert result["offset"] == 0
        assert result["limit"] == 3000
        assert result["has_more"] is False
