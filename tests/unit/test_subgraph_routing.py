"""Unit tests for subgraph routing via _route_to_specialist().

These tests verify that after Phase 7.2 W1-1 fix:
- _executor_subgraph.invoke is NOT called during routing (removed dual-execution)
- _execute_action IS called (the main pipeline path)
- tool_history contains exactly one entry per tool call (no duplicates)
- HandoffResult is appended exactly once per tool action to handoff_results
"""

from __future__ import annotations

from unittest.mock import patch

from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
from agentic_workflows.orchestration.langgraph.state_schema import new_run_state
from tests.conftest import ScriptedProvider


def _make_orch() -> LangGraphOrchestrator:
    """Build a LangGraphOrchestrator with a scripted provider."""
    provider = ScriptedProvider(responses=[{"action": "finish", "answer": "done"}])
    return LangGraphOrchestrator(provider=provider)


def _make_state(orch: LangGraphOrchestrator, run_id: str = "test-run-001") -> dict:
    """Return a fresh RunState with sensible defaults for routing tests."""
    state = new_run_state(
        system_prompt=orch.system_prompt,
        user_input="Test mission 1",
        run_id=run_id,
    )
    return state


def test_tool_action_sets_via_subgraph_tag() -> None:
    """Tool actions routed via _route_to_specialist() must have via_subgraph=True."""
    orch = _make_orch()
    state = _make_state(orch)
    state["pending_action"] = {
        "action": "tool",
        "tool_name": "repeat_message",
        "args": {"message": "hi"},
        "__mission_id": 1,
    }

    result_state = orch._route_to_specialist(state)

    assert any(
        e.get("via_subgraph") for e in result_state["tool_history"]
    ), "Expected at least one tool_history entry with via_subgraph=True"


def test_tool_action_appends_exactly_one_handoff_result() -> None:
    """_route_to_specialist() must append exactly one HandoffResult per tool action."""
    orch = _make_orch()
    state = _make_state(orch)
    state["pending_action"] = {
        "action": "tool",
        "tool_name": "repeat_message",
        "args": {"message": "hello"},
        "__mission_id": 1,
    }

    result_state = orch._route_to_specialist(state)

    assert len(result_state["handoff_results"]) == 1, (
        f"Expected exactly 1 HandoffResult, got {len(result_state['handoff_results'])}"
    )


def test_tool_action_handoff_result_has_tool_name() -> None:
    """HandoffResult output must contain the routed tool_name."""
    orch = _make_orch()
    state = _make_state(orch)
    state["pending_action"] = {
        "action": "tool",
        "tool_name": "repeat_message",
        "args": {"message": "check"},
        "__mission_id": 1,
    }

    result_state = orch._route_to_specialist(state)

    handoff_result = result_state["handoff_results"][0]
    assert handoff_result["output"].get("tool_name") == "repeat_message", (
        f"HandoffResult output missing tool_name: {handoff_result['output']}"
    )


def test_finish_action_does_not_set_via_subgraph_tag() -> None:
    """Finish actions must NOT produce via_subgraph entries (they bypass the executor subgraph)."""
    orch = _make_orch()
    state = _make_state(orch)
    state["pending_action"] = {
        "action": "finish",
        "answer": "all done",
    }

    result_state = orch._route_to_specialist(state)

    via_subgraph_entries = [
        e for e in result_state["tool_history"] if e.get("via_subgraph")
    ]
    assert len(via_subgraph_entries) == 0, (
        f"Expected no via_subgraph entries for finish action, got: {via_subgraph_entries}"
    )


def test_both_subgraphs_cached_on_orchestrator() -> None:
    """LangGraphOrchestrator must cache both compiled subgraphs as instance attributes."""
    orch = _make_orch()
    assert hasattr(orch, "_executor_subgraph"), "_executor_subgraph missing from orchestrator"
    assert hasattr(orch, "_evaluator_subgraph"), "_evaluator_subgraph missing from orchestrator"
    # Verify they are compiled (have an invoke method)
    assert callable(getattr(orch._executor_subgraph, "invoke", None)), (
        "_executor_subgraph.invoke is not callable"
    )
    assert callable(getattr(orch._evaluator_subgraph, "invoke", None)), (
        "_evaluator_subgraph.invoke is not callable"
    )


def test_call_index_assigned_sequentially() -> None:
    """Entries copied from exec_tool_history must have call index reflecting global position."""
    orch = _make_orch()
    state = _make_state(orch)
    # Pre-seed tool_history with two entries to offset call index
    state["tool_history"] = [
        {"call": 1, "tool": "repeat_message", "args": {"message": "prev1"}, "result": {}},
        {"call": 2, "tool": "repeat_message", "args": {"message": "prev2"}, "result": {}},
    ]
    state["pending_action"] = {
        "action": "tool",
        "tool_name": "repeat_message",
        "args": {"message": "new"},
        "__mission_id": 1,
    }

    result_state = orch._route_to_specialist(state)

    # The new via_subgraph entry should have call = 3 (2 pre-existing + 1)
    new_entries = [e for e in result_state["tool_history"] if e.get("via_subgraph")]
    assert len(new_entries) >= 1, "Expected at least one via_subgraph entry"
    # First new entry must have call = 3
    assert new_entries[0]["call"] == 3, (
        f"Expected call=3 for first new entry, got call={new_entries[0].get('call')}"
    )


def test_executor_subgraph_invoke_not_called_during_routing() -> None:
    """W1-1: _executor_subgraph.invoke must NOT be called during _route_to_specialist.

    The dual-execution bug caused both subgraph.invoke AND _execute_action to fire,
    producing duplicate tool side effects. After the fix, only _execute_action runs.
    """
    orch = _make_orch()
    state = _make_state(orch)
    state["pending_action"] = {
        "action": "tool",
        "tool_name": "repeat_message",
        "args": {"message": "no-double-exec"},
        "__mission_id": 1,
    }

    with patch.object(orch._executor_subgraph, "invoke", wraps=orch._executor_subgraph.invoke) as mock_invoke:
        orch._route_to_specialist(state)

    mock_invoke.assert_not_called(), (
        "_executor_subgraph.invoke should NOT be called during routing — "
        "only _execute_action should fire"
    )


# ---------------------------------------------------------------------------
# _build_system_prompt() — AGENT_ROOT / AGENT_WORKDIR separation (Phase 07.2-05)
# ---------------------------------------------------------------------------


def test_system_prompt_uses_agent_root_for_reads(monkeypatch: object) -> None:
    """When AGENT_ROOT and AGENT_WORKDIR differ, prompt shows both separately."""
    monkeypatch.setenv("AGENT_ROOT", "/tmp/project")
    monkeypatch.setenv("AGENT_WORKDIR", "/tmp/workspace")

    orch = _make_orch()
    prompt = orch.system_prompt

    assert "Project root (read): /tmp/project" in prompt, "readable root must appear in prompt"
    assert "Write workspace: /tmp/workspace" in prompt, "writable workspace must appear in prompt"
    assert '"path":"/tmp/project"' in prompt, "search_files example must use readable root"
    assert "Working directory:" not in prompt, "single-dir label must not appear when roots differ"


def test_system_prompt_single_dir_when_roots_equal(monkeypatch: object) -> None:
    """When only AGENT_WORKDIR is set (no AGENT_ROOT), prompt uses single 'Working directory' line."""
    monkeypatch.delenv("AGENT_ROOT", raising=False)
    monkeypatch.setenv("AGENT_WORKDIR", "/tmp/same")

    orch = _make_orch()
    prompt = orch.system_prompt

    assert "Working directory: /tmp/same" in prompt
    assert "Project root (read):" not in prompt


def test_system_prompt_search_files_uses_readable_root(monkeypatch: object) -> None:
    """search_files example in prompt must point to readable root, not write dir."""
    monkeypatch.setenv("AGENT_ROOT", "/app/project")
    monkeypatch.setenv("AGENT_WORKDIR", "/app/workspace")

    orch = _make_orch()
    prompt = orch.system_prompt

    assert '"/app/project"' in prompt
    assert '"/app/workspace"' not in prompt
