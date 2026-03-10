"""Unit tests for QueryContextTool."""

from __future__ import annotations

from unittest.mock import MagicMock

from agentic_workflows.tools.query_context import QueryContextTool


def _make_mock_store(results: list[dict] | None = None):
    store = MagicMock()
    store.query_cascade.return_value = results or []
    return store


def test_returns_formatted_results_from_store():
    """QueryContextTool formats cascade results correctly."""
    store = _make_mock_store([
        {
            "id": "abc",
            "run_id": "r1",
            "mission_id": 1,
            "goal": "sort numbers",
            "summary": "sorted [1,2,3]",
            "tools_used": ["sort_array"],
            "score": 0.85,
            "source_layer": "L2",
        },
        {
            "id": "def",
            "run_id": "r2",
            "mission_id": 2,
            "goal": "write file",
            "summary": "wrote output.txt",
            "tools_used": ["write_file"],
            "score": 0.72,
            "source_layer": "L1",
        },
    ])
    tool = QueryContextTool(store)
    result = tool.execute({"query": "sort and write"})

    assert result["count"] == 2
    assert len(result["results"]) == 2
    assert result["results"][0]["goal"] == "sort numbers"
    assert result["results"][0]["summary"] == "sorted [1,2,3]"
    assert result["results"][0]["tools_used"] == ["sort_array"]
    assert result["results"][0]["score"] == 0.85
    assert result["results"][0]["source_layer"] == "L2"
    store.query_cascade.assert_called_once()


def test_empty_query_returns_error():
    """Empty query string returns error dict."""
    store = _make_mock_store()
    tool = QueryContextTool(store)
    result = tool.execute({"query": ""})
    assert "error" in result
    assert "query is required" in result["error"]


def test_missing_query_returns_error():
    """Missing query key returns error dict."""
    store = _make_mock_store()
    tool = QueryContextTool(store)
    result = tool.execute({})
    assert "error" in result


def test_empty_results_from_store():
    """Store returning empty list gives count=0."""
    store = _make_mock_store([])
    tool = QueryContextTool(store)
    result = tool.execute({"query": "unknown topic"})
    assert result["count"] == 0
    assert result["results"] == []


def test_max_results_clamped_to_10():
    """max_results > 10 is clamped to 10."""
    store = _make_mock_store()
    tool = QueryContextTool(store)
    tool.execute({"query": "test", "max_results": 50})
    call_kwargs = store.query_cascade.call_args
    assert call_kwargs.kwargs.get("top_k", call_kwargs[1].get("top_k")) <= 10


def test_default_max_results_is_3():
    """Default max_results is 3 when not specified."""
    store = _make_mock_store()
    tool = QueryContextTool(store)
    tool.execute({"query": "test"})
    call_kwargs = store.query_cascade.call_args
    assert call_kwargs.kwargs.get("top_k", call_kwargs[1].get("top_k")) == 3


def test_embedding_provider_used_when_available():
    """When embedding_provider is given, embed() is called."""
    store = _make_mock_store()
    embed_provider = MagicMock()
    embed_provider.embed.return_value = [[0.1, 0.2, 0.3]]
    tool = QueryContextTool(store, embedding_provider=embed_provider)
    tool.execute({"query": "test"})
    embed_provider.embed.assert_called_once_with(["test"])
    call_kwargs = store.query_cascade.call_args
    assert call_kwargs.kwargs.get("embedding") == [0.1, 0.2, 0.3]


def test_no_embedding_provider_passes_none():
    """Without embedding_provider, embedding=None passed to cascade."""
    store = _make_mock_store()
    tool = QueryContextTool(store)
    tool.execute({"query": "test"})
    call_kwargs = store.query_cascade.call_args
    assert call_kwargs.kwargs.get("embedding") is None


def test_tool_not_registered_without_store():
    """build_tool_registry without mission_context_store does not include query_context."""
    from unittest.mock import MagicMock as MM

    from agentic_workflows.orchestration.langgraph.tools_registry import build_tool_registry

    mock_memo = MM()
    registry = build_tool_registry(mock_memo)
    assert "query_context" not in registry


def test_tool_registered_with_store():
    """build_tool_registry with mission_context_store registers query_context."""
    from unittest.mock import MagicMock as MM

    from agentic_workflows.orchestration.langgraph.tools_registry import build_tool_registry

    mock_memo = MM()
    mock_ctx_store = MM()
    registry = build_tool_registry(mock_memo, mission_context_store=mock_ctx_store)
    assert "query_context" in registry
    assert registry["query_context"].name == "query_context"
