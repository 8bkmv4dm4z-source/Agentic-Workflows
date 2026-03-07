"""Tests for ContextManager eviction — replaces old _evict_tool_result_messages tests.

Phase 7.1 Plan 02: all eviction is now handled by ContextManager, not graph.py methods.
"""

from __future__ import annotations

from agentic_workflows.orchestration.langgraph.context_manager import ContextManager


def _state_with_messages(messages: list[dict], mission_contexts=None) -> dict:
    """Build minimal state for ContextManager eviction testing."""
    return {
        "messages": messages,
        "mission_contexts": mission_contexts or {},
        "policy_flags": {},
        "step": 5,
    }


def test_compact_sliding_window_enforced():
    """compact() drops oldest non-system messages when over sliding_window_cap."""
    cm = ContextManager(sliding_window_cap=10)
    messages = [{"role": "system", "content": "sys"}]
    messages += [{"role": "user", "content": f"msg-{i}"} for i in range(20)]
    state = _state_with_messages(messages)
    cm.compact(state)
    assert len(state["messages"]) == 10
    assert state["messages"][0]["role"] == "system"
    assert state["messages"][-1]["content"] == "msg-19"


def test_on_tool_result_replaces_large_result():
    """on_tool_result() replaces messages with content > threshold with placeholders."""
    cm = ContextManager(large_result_threshold=50)
    large_content = "TOOL RESULT (read_file):\n" + "x" * 200
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": large_content},
    ]
    state = _state_with_messages(messages)
    cm.on_tool_result(
        state,
        tool_name="read_file",
        result={"data": "x" * 200},
        args={},
        mission_id=0,
    )
    replaced = state["messages"][1]
    assert replaced["role"] == "user"
    assert "[Orchestrator]" in replaced["content"]
    assert "[tool_result: read_file" in replaced["content"]
    assert "chars" in replaced["content"]


def test_system_prompt_never_evicted():
    """System prompt (messages[0]) is never evicted by compact()."""
    cm = ContextManager(sliding_window_cap=5)
    sys_content = "You are an orchestrator."
    messages = [
        {"role": "system", "content": sys_content},
    ]
    messages += [{"role": "user", "content": f"msg-{i}"} for i in range(10)]
    state = _state_with_messages(messages)
    cm.compact(state)
    assert state["messages"][0]["content"] == sys_content
    assert state["messages"][0]["role"] == "system"


def test_placeholder_format():
    """Evicted message placeholder follows the [Orchestrator] [tool_result: ...] format."""
    cm = ContextManager(large_result_threshold=50)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "TOOL RESULT (my_tool):\n" + "x" * 300},
    ]
    state = _state_with_messages(messages)
    cm.on_tool_result(
        state,
        tool_name="my_tool",
        result={"data": "x" * 300},
        args={},
        mission_id=0,
    )
    placeholder = state["messages"][1]["content"]
    assert placeholder.startswith("[Orchestrator] [tool_result: my_tool,")
    assert "chars, stored in context]" in placeholder


def test_eviction_stops_under_cap():
    """compact() does not remove messages when under sliding_window_cap."""
    cm = ContextManager(sliding_window_cap=30)
    messages = [{"role": "system", "content": "sys"}]
    messages += [{"role": "user", "content": f"msg-{i}"} for i in range(5)]
    state = _state_with_messages(messages)
    cm.compact(state)
    assert len(state["messages"]) == 6  # all preserved


def test_small_results_not_evicted():
    """Small tool results (under threshold) are not replaced."""
    cm = ContextManager(large_result_threshold=4000)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "TOOL RESULT (small):\n{\"ok\": true}"},
    ]
    state = _state_with_messages(messages)
    cm.on_tool_result(
        state,
        tool_name="small",
        result={"ok": True},
        args={},
        mission_id=0,
    )
    assert "TOOL RESULT" in state["messages"][1]["content"]
