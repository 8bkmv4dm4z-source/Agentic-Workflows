"""Unit tests for state_schema.py.

Tests Annotated reducer annotations on RunState list fields and
message compaction in ensure_state_defaults().
"""

from __future__ import annotations

import operator
import typing

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


def test_seen_tool_signatures_is_plain_set():
    """RunState.seen_tool_signatures must be set[str] (no Annotated wrapper)."""
    hints = typing.get_type_hints(RunState, include_extras=True)
    hint = hints["seen_tool_signatures"]
    # Must NOT have Annotated metadata — it should be a plain set[str]
    assert not hasattr(hint, "__metadata__"), (
        "seen_tool_signatures must NOT be Annotated (should be plain set[str])"
    )
    # Verify it's set[str]
    origin = getattr(hint, "__origin__", None)
    assert origin is set, f"Expected set origin, got {origin}"


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
    """Messages exceeding threshold are compacted via ContextManager.compact()."""
    from agentic_workflows.orchestration.langgraph.context_manager import ContextManager
    cm = ContextManager(sliding_window_cap=40)
    msgs = _make_messages(50)  # 1 system + 50 non-system = 51 total
    state = {"messages": msgs, "policy_flags": {}, "step": 0}
    cm.compact(state)
    assert len(state["messages"]) <= 40


def test_compaction_preserves_system_message():
    """System message at index 0 is always preserved after compaction."""
    from agentic_workflows.orchestration.langgraph.context_manager import ContextManager
    cm = ContextManager(sliding_window_cap=40)
    msgs = _make_messages(50)
    state = {"messages": msgs, "policy_flags": {}, "step": 0}
    cm.compact(state)
    assert any(m["role"] == "system" for m in state["messages"])


def test_compaction_keeps_most_recent():
    """After compaction, the most recent non-system messages are retained."""
    from agentic_workflows.orchestration.langgraph.context_manager import ContextManager
    cm = ContextManager(sliding_window_cap=40)
    msgs = _make_messages(50)
    last_msg = msgs[-1]
    state = {"messages": msgs, "policy_flags": {}, "step": 0}
    cm.compact(state)
    assert last_msg in state["messages"]


def test_compaction_does_not_fire_at_threshold():
    """Exactly at threshold, no compaction occurs."""
    from agentic_workflows.orchestration.langgraph.context_manager import ContextManager
    cm = ContextManager(sliding_window_cap=10)
    msgs = _make_messages(9)  # 1 system + 9 non-system = 10 total (at threshold)
    state = {"messages": msgs, "policy_flags": {}, "step": 0}
    cm.compact(state)
    assert len(state["messages"]) == 10


def test_compaction_threshold_configurable():
    """ContextManager sliding_window_cap controls compaction threshold."""
    from agentic_workflows.orchestration.langgraph.context_manager import ContextManager
    cm = ContextManager(sliding_window_cap=5)
    msgs = _make_messages(20)  # well above threshold of 5
    state = {"messages": msgs, "policy_flags": {}, "step": 0}
    cm.compact(state)
    assert len(state["messages"]) <= 5


# ---------------------------------------------------------------------------
# _ANNOTATED_LIST_FIELDS synchronization test
# ---------------------------------------------------------------------------


def test_annotated_list_fields_synchronized():
    """_ANNOTATED_LIST_FIELDS must contain every Annotated[list[...], operator.add] field in RunState.

    seen_tool_signatures is NOT in this set (converted to plain set[str] in W2-4).
    """
    from typing import Annotated, get_args, get_origin, get_type_hints

    from agentic_workflows.orchestration.langgraph.graph import _ANNOTATED_LIST_FIELDS

    hints = get_type_hints(RunState, include_extras=True)
    reducer_fields = set()
    for name, hint in hints.items():
        if get_origin(hint) is Annotated:
            args = get_args(hint)
            if len(args) >= 2 and args[1] is operator.add:
                reducer_fields.add(name)

    assert reducer_fields == _ANNOTATED_LIST_FIELDS, (
        f"Mismatch: RunState has {reducer_fields}, _ANNOTATED_LIST_FIELDS has {_ANNOTATED_LIST_FIELDS}"
    )
    assert "seen_tool_signatures" not in _ANNOTATED_LIST_FIELDS, (
        "seen_tool_signatures must NOT be in _ANNOTATED_LIST_FIELDS (converted to set[str])"
    )


# ---------------------------------------------------------------------------
# seen_tool_signatures checkpoint roundtrip test (W2-4)
# ---------------------------------------------------------------------------


def test_seen_tool_signatures_checkpoint_roundtrip():
    """seen_tool_signatures set survives JSON roundtrip via set-aware serializer."""
    import json

    original = {"sig1", "sig2", "sig3"}
    state = {"seen_tool_signatures": original, "step": 0}

    # Serialize with set-aware default (matches checkpoint_store pattern)
    serialized = json.dumps(
        state, sort_keys=True,
        default=lambda x: sorted(x) if isinstance(x, set) else str(x),
    )

    # Deserialize and convert list back to set (matches ensure_state_defaults pattern)
    loaded = json.loads(serialized)
    restored = set(loaded["seen_tool_signatures"])

    assert restored == original, f"Expected {original}, got {restored}"


def test_ensure_state_defaults_converts_list_to_set():
    """ensure_state_defaults must convert seen_tool_signatures list (from JSON) to set."""
    state = {"seen_tool_signatures": ["sig1", "sig2"]}
    result = ensure_state_defaults(state)
    assert isinstance(result["seen_tool_signatures"], set), (
        f"Expected set, got {type(result['seen_tool_signatures'])}"
    )
    assert result["seen_tool_signatures"] == {"sig1", "sig2"}


def test_new_run_state_initializes_set():
    """new_run_state must initialize seen_tool_signatures as set()."""
    from agentic_workflows.orchestration.langgraph.state_schema import new_run_state
    state = new_run_state("system", "user")
    assert isinstance(state["seen_tool_signatures"], set), (
        f"Expected set, got {type(state['seen_tool_signatures'])}"
    )
    assert state["seen_tool_signatures"] == set()


# ---------------------------------------------------------------------------
# SQLiteCheckpointStore persistent connection tests (W2-3)
# ---------------------------------------------------------------------------


def test_checkpoint_store_uses_persistent_connection(tmp_path):
    """SQLiteCheckpointStore must have a persistent _conn and _lock (not per-call _connect)."""
    from agentic_workflows.orchestration.langgraph.checkpoint_store import SQLiteCheckpointStore

    db_file = str(tmp_path / "test_wal.db")
    store = SQLiteCheckpointStore(db_file)

    assert hasattr(store, "_conn"), "Store must have a persistent _conn attribute"
    assert hasattr(store, "_lock"), "Store must have a threading._lock attribute"

    # Two saves must succeed without error (proves persistent connection works)
    store.save(run_id="r1", step=0, node_name="init", state={"test": True})
    store.save(run_id="r1", step=1, node_name="plan", state={"test": True, "step": 1})

    # Verify both checkpoints were saved
    checkpoints = store.list_checkpoints("r1")
    assert len(checkpoints) == 2
    store.close()
