"""Unit tests for state_schema.py.

Tests Annotated reducer annotations on RunState list fields and
message compaction in ensure_state_defaults().
"""

from __future__ import annotations

import operator
import typing

import pytest

from agentic_workflows.orchestration.langgraph.state_schema import (
    RunState,
    ensure_state_defaults,
)


# ---------------------------------------------------------------------------
# Reducer annotation tests (Task 1)
# ---------------------------------------------------------------------------


def test_tool_history_has_annotated_reducer():
    """RunState.tool_history must be Annotated[list[ToolRecord], operator.add]."""
    hints = typing.get_type_hints(RunState, include_extras=True)
    hint = hints["tool_history"]
    assert hasattr(hint, "__metadata__"), "tool_history must be Annotated with reducer"
    assert hint.__metadata__[0] is operator.add, "reducer must be operator.add"


def test_memo_events_has_annotated_reducer():
    """RunState.memo_events must be Annotated[list[MemoEvent], operator.add]."""
    hints = typing.get_type_hints(RunState, include_extras=True)
    hint = hints["memo_events"]
    assert hasattr(hint, "__metadata__"), "memo_events must be Annotated with reducer"
    assert hint.__metadata__[0] is operator.add, "reducer must be operator.add"


def test_seen_tool_signatures_has_annotated_reducer():
    """RunState.seen_tool_signatures must be Annotated[list[str], operator.add]."""
    hints = typing.get_type_hints(RunState, include_extras=True)
    hint = hints["seen_tool_signatures"]
    assert hasattr(hint, "__metadata__"), "seen_tool_signatures must be Annotated"
    assert hint.__metadata__[0] is operator.add, "reducer must be operator.add"


def test_mission_reports_has_annotated_reducer():
    """RunState.mission_reports must be Annotated[list[MissionReport], operator.add]."""
    hints = typing.get_type_hints(RunState, include_extras=True)
    hint = hints["mission_reports"]
    assert hasattr(hint, "__metadata__"), "mission_reports must be Annotated with reducer"
    assert hint.__metadata__[0] is operator.add, "reducer must be operator.add"


# ---------------------------------------------------------------------------
# Message compaction tests (Task 2)
# ---------------------------------------------------------------------------


def _make_messages(n: int, include_system: bool = True) -> list[dict]:
    msgs = []
    if include_system:
        msgs.append({"role": "system", "content": "system prompt"})
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"message {i}"})
    return msgs


def test_compaction_fires_above_threshold():
    """Messages exceeding threshold are compacted to threshold."""
    msgs = _make_messages(50)  # 1 system + 50 non-system = 51 total
    state = ensure_state_defaults({"messages": msgs})
    assert len(state["messages"]) <= 40


def test_compaction_preserves_system_message():
    """System message at index 0 is always preserved after compaction."""
    msgs = _make_messages(50)
    state = ensure_state_defaults({"messages": msgs})
    assert any(m["role"] == "system" for m in state["messages"])


def test_compaction_keeps_most_recent():
    """After compaction, the most recent non-system messages are retained."""
    msgs = _make_messages(50)
    last_msg = msgs[-1]
    state = ensure_state_defaults({"messages": msgs})
    assert last_msg in state["messages"]


def test_compaction_does_not_fire_at_threshold(monkeypatch):
    """Exactly at threshold, no compaction occurs."""
    monkeypatch.setenv("P1_MESSAGE_COMPACTION_THRESHOLD", "10")
    msgs = _make_messages(9)  # 1 system + 9 non-system = 10 total (at threshold)
    state = ensure_state_defaults({"messages": msgs})
    assert len(state["messages"]) == 10


def test_compaction_threshold_env_var(monkeypatch):
    """P1_MESSAGE_COMPACTION_THRESHOLD env var controls compaction threshold."""
    monkeypatch.setenv("P1_MESSAGE_COMPACTION_THRESHOLD", "5")
    msgs = _make_messages(20)  # well above threshold of 5
    state = ensure_state_defaults({"messages": msgs})
    assert len(state["messages"]) <= 5
