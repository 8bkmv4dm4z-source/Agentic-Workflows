"""Tests for _evict_tool_result_messages in LangGraphOrchestrator."""

from __future__ import annotations

import os
from unittest.mock import patch

from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
from tests.conftest import ScriptedProvider


def _make_orch() -> LangGraphOrchestrator:
    """Build a LangGraphOrchestrator with a scripted provider."""
    provider = ScriptedProvider(responses=[{"action": "finish", "answer": "done"}])
    return LangGraphOrchestrator(provider=provider, max_steps=5)


def _state_with_messages(messages: list[dict]) -> dict:
    """Build minimal RunState with given messages."""
    return {
        "messages": messages,
        "run_id": "test-evict",
        "step": 0,
        "tool_history": [],
        "mission_reports": [],
        "pending_action": None,
        "pending_action_queue": [],
        "retry_counts": {},
        "policy_flags": {},
        "token_budget_remaining": 100000,
        "token_budget_used": 0,
        "missions": [],
        "structured_plan": None,
        "mission_contracts": [],
        "active_mission_index": -1,
        "active_mission_id": 0,
        "final_answer": "",
        "mission_ledger": [],
        "memo_events": [],
        "seen_tool_signatures": [],
        "truncated_actions": [],
        "handoff_queue": [],
        "handoff_results": [],
        "active_specialist": "supervisor",
        "rerun_context": {},
        "audit_report": None,
        "mission_tracker": {},
    }


def test_eviction_not_triggered_without_ollama_num_ctx():
    """When OLLAMA_NUM_CTX=0, no eviction occurs regardless of message size."""
    orch = _make_orch()
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "TOOL RESULT (read_file):\n" + "x" * 40000},
    ]
    state = _state_with_messages(messages)
    with patch.dict(os.environ, {"OLLAMA_NUM_CTX": "0"}):
        orch._evict_tool_result_messages(state)
    assert state["messages"][1]["content"].startswith("TOOL RESULT")  # not evicted


def test_eviction_not_triggered_under_threshold():
    """With OLLAMA_NUM_CTX=8000 and small content, no eviction occurs."""
    orch = _make_orch()
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "TOOL RESULT (read_file):\n" + "x" * 100},
    ]
    state = _state_with_messages(messages)
    # ~25 tokens total; threshold is 0.75 * 8000 = 6000
    with patch.dict(os.environ, {"OLLAMA_NUM_CTX": "8000", "CTX_EVICTION_RATIO": "0.75"}):
        orch._evict_tool_result_messages(state)
    assert state["messages"][1]["content"].startswith("TOOL RESULT")  # not evicted


def test_eviction_removes_large_tool_results():
    """Large tool result message is replaced by placeholder when over threshold."""
    orch = _make_orch()
    large_content = "TOOL RESULT (read_file):\n" + "x" * 30000  # ~7500 tokens
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": large_content},
        {"role": "assistant", "content": '{"action": "finish", "answer": "done"}'},
    ]
    state = _state_with_messages(messages)
    with patch.dict(os.environ, {"OLLAMA_NUM_CTX": "8000", "CTX_EVICTION_RATIO": "0.75"}):
        orch._evict_tool_result_messages(state)
    evicted_msg = state["messages"][1]
    assert evicted_msg["content"].startswith("[tool_result: read_file,")
    assert "bytes, stored in run_store" in evicted_msg["content"]


def test_eviction_preserves_system_prompt():
    """System prompt (messages[0]) is never evicted."""
    orch = _make_orch()
    sys_content = "You are an orchestrator."
    messages = [
        {"role": "system", "content": sys_content},
        {"role": "user", "content": "TOOL RESULT (write_file):\n" + "x" * 30000},
    ]
    state = _state_with_messages(messages)
    with patch.dict(os.environ, {"OLLAMA_NUM_CTX": "8000", "CTX_EVICTION_RATIO": "0.75"}):
        orch._evict_tool_result_messages(state)
    assert state["messages"][0]["content"] == sys_content  # system prompt unchanged


def test_eviction_placeholder_content():
    """Evicted message content follows the placeholder format."""
    orch = _make_orch()
    large_content = "TOOL RESULT (my_tool):\n" + "x" * 30000
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": large_content},
    ]
    state = _state_with_messages(messages)
    with patch.dict(os.environ, {"OLLAMA_NUM_CTX": "8000", "CTX_EVICTION_RATIO": "0.75"}):
        orch._evict_tool_result_messages(state)
    placeholder = state["messages"][1]["content"]
    # Format: "[tool_result: {tool_name}, {N} bytes, stored in run_store]"
    assert placeholder.startswith("[tool_result: my_tool,")
    assert "bytes, stored in run_store]" in placeholder


def test_eviction_stops_when_under_threshold():
    """With two large messages, only the first is evicted if that brings under threshold."""
    orch = _make_orch()
    large_content_1 = "TOOL RESULT (file1):\n" + "x" * 20000
    large_content_2 = "TOOL RESULT (file2):\n" + "x" * 20000
    # total ~10000 tokens, threshold 0.75*8000=6000; evicting one (~5000t) brings to ~5000 < 6000
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": large_content_1},
        {"role": "user", "content": large_content_2},
    ]
    state = _state_with_messages(messages)
    with patch.dict(os.environ, {"OLLAMA_NUM_CTX": "8000", "CTX_EVICTION_RATIO": "0.75"}):
        orch._evict_tool_result_messages(state)
    # First message should be evicted (placeholder)
    assert state["messages"][1]["content"].startswith("[tool_result:")
