"""Unit tests for specialist_executor.py — executor subgraph isolation and invocation."""
from __future__ import annotations

from agentic_workflows.orchestration.langgraph.specialist_executor import (
    ExecutorState,
    build_executor_subgraph,
)
from agentic_workflows.orchestration.langgraph.state_schema import RunState

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_executor_state(**overrides: object) -> dict:
    """Return a fully-populated ExecutorState dict with sensible defaults."""
    base: dict = {
        "task_id": "test-t1",
        "specialist": "executor",
        "mission_id": 1,
        "tool_scope": ["sort_array"],
        "input_context": {},
        "token_budget": 4096,
        "exec_tool_history": [],
        "exec_seen_signatures": [],
        "result": {},
        "tokens_used": 0,
        "status": "success",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Field set assertion
# ---------------------------------------------------------------------------


def test_executor_state_fields() -> None:
    """ExecutorState must have exactly the 11 specified fields."""
    expected = {
        "task_id",
        "specialist",
        "mission_id",
        "tool_scope",
        "input_context",
        "token_budget",
        "exec_tool_history",
        "exec_seen_signatures",
        "result",
        "tokens_used",
        "status",
        "mission_goal",
        "prior_results_summary",
    }
    assert set(ExecutorState.__annotations__) == expected


def test_executor_state_disjoint_from_run_state() -> None:
    """ExecutorState field names must not overlap with RunState field names."""
    executor_keys = set(ExecutorState.__annotations__)
    run_keys = set(RunState.__annotations__)
    overlap = executor_keys & run_keys
    assert overlap == set(), f"Overlapping keys: {overlap}"


# ---------------------------------------------------------------------------
# Subgraph invocation — success path
# ---------------------------------------------------------------------------


def test_executor_subgraph_sort_array() -> None:
    """Executor subgraph dispatches sort_array and returns status=success."""
    graph = build_executor_subgraph(tool_scope=["sort_array"])
    state = _make_executor_state(
        input_context={"tool_name": "sort_array", "args": {"items": [3, 1, 2], "order": "asc"}}
    )
    result = graph.invoke(state)
    assert result["status"] == "success", f"Expected success, got: {result['status']}"
    assert "sorted" in result["result"], f"Expected 'sorted' key in result: {result['result']}"


def test_executor_subgraph_tool_history_recorded() -> None:
    """After a successful call, exec_tool_history must have exactly one entry for sort_array."""
    graph = build_executor_subgraph(tool_scope=["sort_array"])
    state = _make_executor_state(
        input_context={"tool_name": "sort_array", "args": {"items": [5, 2, 8], "order": "asc"}}
    )
    result = graph.invoke(state)
    assert len(result["exec_tool_history"]) == 1
    assert result["exec_tool_history"][0]["tool"] == "sort_array"


# ---------------------------------------------------------------------------
# Subgraph invocation — error path
# ---------------------------------------------------------------------------


def test_executor_subgraph_unknown_tool() -> None:
    """Executor subgraph returns status=error for an unknown tool without raising."""
    graph = build_executor_subgraph(tool_scope=["sort_array"])
    state = _make_executor_state(
        input_context={"tool_name": "nonexistent", "args": {}}
    )
    result = graph.invoke(state)
    assert result["status"] == "error", f"Expected error, got: {result['status']}"
    assert "tool_not_found" in result["result"]["error"], (
        f"Expected 'tool_not_found' in error: {result['result']['error']}"
    )
