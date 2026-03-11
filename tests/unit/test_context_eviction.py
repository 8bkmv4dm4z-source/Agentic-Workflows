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
    """on_tool_result() replaces messages with content > threshold with placeholders.

    Message format is 'TOOL_RESULT #N (tool_name):' (underscore, step number) — this is
    the format produced by graph.py _execute_action and the retroactive replacement in
    on_tool_result must match it correctly.
    """
    cm = ContextManager(large_result_threshold=50)
    large_result = {"data": "x" * 200}
    import json
    large_json = json.dumps(large_result)
    # Use the real message format produced by graph.py
    large_content = f"TOOL_RESULT #1 (read_file): {large_json}\nContinue."
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "system", "content": large_content},
    ]
    state = _state_with_messages(messages)
    cm.on_tool_result(
        state,
        tool_name="read_file",
        result=large_result,
        args={},
        mission_id=0,
    )
    replaced = state["messages"][1]
    assert replaced["role"] == "system"
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
    """Evicted message placeholder follows the [tool_result: tool_name, N chars, stored in context] format."""
    import json
    cm = ContextManager(large_result_threshold=50)
    result = {"data": "x" * 300}
    result_json = json.dumps(result)
    # Use the real message format produced by graph.py _execute_action
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "system", "content": f"TOOL_RESULT #1 (my_tool): {result_json}\nContinue."},
    ]
    state = _state_with_messages(messages)
    cm.on_tool_result(
        state,
        tool_name="my_tool",
        result=result,
        args={},
        mission_id=0,
    )
    placeholder = state["messages"][1]["content"]
    assert "[tool_result: my_tool," in placeholder
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
