"""Integration tests for multi-mission result preservation via subgraph routing.

These tests verify that after Plan 04-01 subgraph wiring:
- tool_history entries produced by the executor subgraph have via_subgraph=True
- A 3-mission run preserves all tool_history entries and sets via_subgraph=True
- Checkpoint replay restores mission_reports correctly after a 1-mission run
- MissionAuditor chain_integrity passes (audit_report["failed"] == 0)

Plan: 04-02 — MAGT-06 end-to-end proof of copy-back logic correctness.
"""

from __future__ import annotations

import tempfile

from agentic_workflows.orchestration.langgraph.checkpoint_store import SQLiteCheckpointStore
from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore
from tests.conftest import ScriptedProvider


def _make_orch(
    responses: list[dict],
    checkpoint_store: SQLiteCheckpointStore | None = None,
    memo_store: SQLiteMemoStore | None = None,
) -> LangGraphOrchestrator:
    """Build a LangGraphOrchestrator with a scripted provider."""
    provider = ScriptedProvider(responses=responses)
    return LangGraphOrchestrator(
        provider=provider,
        max_steps=20,
        checkpoint_store=checkpoint_store,
        memo_store=memo_store,
    )


def test_via_subgraph_tag_present() -> None:
    """Single-mission run with one tool call must produce tool_history entry with via_subgraph=True."""
    provider_responses = [
        {"action": "tool", "tool_name": "repeat_message", "args": {"message": "hello"}},
        {"action": "finish", "answer": "done"},
    ]
    orch = _make_orch(provider_responses)
    result = orch.run("Task 1: Repeat the message 'hello' using repeat_message.")
    tool_entries = [e for e in result["state"]["tool_history"] if e.get("tool") != "finish"]
    assert any(
        e.get("via_subgraph") for e in tool_entries
    ), f"No via_subgraph=True in tool_history. Entries: {tool_entries}"


def test_multi_mission_preserves_all_tool_history() -> None:
    """3-mission run with one tool call per mission must produce >=3 via_subgraph entries.

    Uses task-prefixed mission text so the parser produces 3 separate missions.
    Scripts one repeat_message + one finish per mission (provider cycles repeating last response).
    Verifies:
    - len(via_subgraph entries) >= 3
    - audit_report is not None
    - audit_report["failed"] == 0
    """
    provider_responses = [
        # Mission 1: call repeat_message, then finish
        {"action": "tool", "tool_name": "repeat_message", "args": {"message": "mission1"}},
        {"action": "finish", "answer": "mission 1 done"},
        # Mission 2: call repeat_message, then finish
        {"action": "tool", "tool_name": "repeat_message", "args": {"message": "mission2"}},
        {"action": "finish", "answer": "mission 2 done"},
        # Mission 3: call repeat_message, then finish
        {"action": "tool", "tool_name": "repeat_message", "args": {"message": "mission3"}},
        {"action": "finish", "answer": "all done"},
    ]
    orch = _make_orch(provider_responses)
    mission_text = (
        "Task 1: Use repeat_message to echo 'mission1'.\n"
        "Task 2: Use repeat_message to echo 'mission2'.\n"
        "Task 3: Use repeat_message to echo 'mission3'."
    )
    result = orch.run(mission_text)

    via_subgraph_entries = [
        e for e in result["state"]["tool_history"] if e.get("via_subgraph")
    ]
    assert len(via_subgraph_entries) >= 3, (
        f"Expected >=3 via_subgraph entries for 3-mission run, got {len(via_subgraph_entries)}. "
        f"All tool_history: {result['state']['tool_history']}"
    )

    audit_report = result.get("audit_report")
    assert audit_report is not None, "audit_report should not be None after a completed run"
    assert audit_report["failed"] == 0, (
        f"audit_report['failed'] == {audit_report['failed']} (expected 0). "
        f"Findings: {audit_report.get('findings', [])}"
    )


def test_checkpoint_replay_restores_mission_reports() -> None:
    """After a 2-mission run with a shared checkpoint_store, load_latest() returns non-None state.

    The key assertions are:
    - The checkpoint was saved (load_latest() != None)
    - The loaded state contains mission_reports
    - mission_reports count >= 1 (at least one report was persisted)
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        checkpoint_store = SQLiteCheckpointStore(db_path=f"{tmp_dir}/checkpoints.db")
        memo_store = SQLiteMemoStore(db_path=f"{tmp_dir}/memo.db")
        provider_responses = [
            # Mission 1
            {"action": "tool", "tool_name": "repeat_message", "args": {"message": "replay1"}},
            {"action": "finish", "answer": "mission 1 done"},
            # Mission 2
            {"action": "tool", "tool_name": "repeat_message", "args": {"message": "replay2"}},
            {"action": "finish", "answer": "all done"},
        ]
        orch = _make_orch(
            provider_responses,
            checkpoint_store=checkpoint_store,
            memo_store=memo_store,
        )
        result = orch.run(
            "Task 1: Use repeat_message to echo 'replay1'.\n"
            "Task 2: Use repeat_message to echo 'replay2'."
        )
        run_id = result["run_id"]
        assert run_id is not None, "run_id must be set after run"

        # Checkpoint must have been saved (at least the init checkpoint)
        loaded_state = checkpoint_store.load_latest(run_id)
        assert loaded_state is not None, (
            f"checkpoint_store.load_latest({run_id!r}) returned None — "
            "checkpoint was not saved during run"
        )
        assert "mission_reports" in loaded_state, (
            f"Loaded checkpoint state missing 'mission_reports' key. Keys: {list(loaded_state.keys())}"
        )
        assert len(loaded_state["mission_reports"]) >= 1, (
            f"Expected >=1 mission_reports in checkpoint, got {len(loaded_state['mission_reports'])}"
        )
