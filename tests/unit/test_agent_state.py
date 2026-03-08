"""Tests for core/agent_state.py — AgentState dataclass."""
from __future__ import annotations

from agentic_workflows.core.agent_state import AgentState


def make_state():
    return AgentState(messages=[])


def test_initial_state():
    s = make_state()
    assert s.messages == []
    assert s.step == 0
    assert s.seen_tool_calls == set()


def test_add_message_basic():
    s = make_state()
    s.add_message("user", "hello")
    assert len(s.messages) == 1
    assert s.messages[0]["role"] == "user"
    assert s.messages[0]["content"] == "hello"


def test_add_message_with_name():
    s = make_state()
    s.add_message("tool", "result", name="my_tool")
    assert s.messages[0]["name"] == "my_tool"


def test_add_message_without_name_no_name_key():
    s = make_state()
    s.add_message("assistant", "hi")
    assert "name" not in s.messages[0]


def test_add_multiple_messages():
    s = make_state()
    s.add_message("system", "sys")
    s.add_message("user", "q")
    s.add_message("assistant", "a")
    assert len(s.messages) == 3


def test_register_tool_call_new():
    s = make_state()
    result = s.register_tool_call("my_tool", {"arg": "val"})
    assert result is True
    assert len(s.seen_tool_calls) == 1


def test_register_tool_call_duplicate():
    s = make_state()
    s.register_tool_call("my_tool", {"arg": "val"})
    result = s.register_tool_call("my_tool", {"arg": "val"})
    assert result is False
    assert len(s.seen_tool_calls) == 1


def test_register_different_args_not_duplicate():
    s = make_state()
    s.register_tool_call("my_tool", {"arg": "val1"})
    result = s.register_tool_call("my_tool", {"arg": "val2"})
    assert result is True
    assert len(s.seen_tool_calls) == 2


def test_register_different_tools_not_duplicate():
    s = make_state()
    s.register_tool_call("tool_a", {"x": 1})
    result = s.register_tool_call("tool_b", {"x": 1})
    assert result is True


def test_all_roles_accepted():
    s = make_state()
    for role in ("system", "user", "assistant", "tool"):
        s.add_message(role, f"msg from {role}")
    assert len(s.messages) == 4
