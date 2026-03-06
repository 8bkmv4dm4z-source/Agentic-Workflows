from __future__ import annotations

"""Typed state contract for Phase 1 graph orchestration.

The graph can re-enter nodes with partially populated state snapshots. This file
keeps the canonical schema and provides a defaulting function that hardens state
before each node executes.
"""

import json
import operator
import os
from datetime import UTC, datetime
from hashlib import sha256
from typing import Annotated, Any, Literal, TypedDict, cast
from uuid import uuid4


class AgentMessage(TypedDict):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class ToolRecord(TypedDict):
    call: int
    tool: str
    args: dict[str, Any]
    result: dict[str, Any]


class MemoEvent(TypedDict):
    key: str
    namespace: str
    source_tool: str
    step: int
    value_hash: str
    created_at: str


class MissionReport(TypedDict):
    mission_id: int
    mission: str
    used_tools: list[str]
    tool_results: list[dict[str, Any]]
    result: str
    status: Literal["pending", "in_progress", "completed", "failed"]
    required_tools: list[str]
    required_files: list[str]
    written_files: list[str]
    expected_fibonacci_count: int | None
    contract_checks: list[str]
    subtask_contracts: list[dict[str, Any]]
    subtask_statuses: list[dict[str, Any]]


class RunResult(TypedDict):
    """Typed return contract for LangGraphOrchestrator.run()."""

    answer: str
    tools_used: list[ToolRecord]
    mission_report: list[MissionReport]
    run_id: str | None
    memo_events: list[MemoEvent]
    memo_store_entries: list[dict[str, Any]]
    derived_snapshot: dict[str, Any]
    checkpoints: list[dict[str, Any]]
    audit_report: dict[str, Any] | None
    state: dict[str, Any]


class RunState(TypedDict):
    # Run identity and step position.
    run_id: str
    step: int
    # Full conversation transcript used by the planning model.
    messages: list[AgentMessage]
    # Logical mission tracking used for per-mission reporting.
    completed_tasks: list[str]
    # Tool execution audit trail.
    tool_history: Annotated[list[ToolRecord], operator.add]  # type: ignore[misc]
    memo_events: Annotated[list[MemoEvent], operator.add]  # type: ignore[misc]
    # Retry counters for diagnostics and guardrail enforcement.
    retry_counts: dict[str, int]
    policy_flags: dict[str, Any]
    # Duplicate-call prevention and tool usage telemetry.
    seen_tool_signatures: Annotated[list[str], operator.add]  # type: ignore[misc]
    tool_call_counts: dict[str, int]
    # Human-readable mission-level report data.
    missions: list[str]
    mission_reports: Annotated[list[MissionReport], operator.add]  # type: ignore[misc]
    active_mission_index: int
    active_mission_id: int
    mission_contracts: list[dict[str, Any]]
    # Structured plan from mission parser (serialized StructuredPlan).
    structured_plan: dict[str, Any] | None
    # Explicit rerun scope metadata from reviewer/CLI.
    rerun_context: dict[str, Any]
    # Planned action and terminal answer.
    pending_action: dict[str, Any] | None
    pending_action_queue: list[dict[str, Any]]
    final_answer: str
    # Post-run audit report (set by _finalize).
    audit_report: dict[str, Any] | None
    # Multi-agent handoff state.
    handoff_queue: list[dict[str, Any]]
    handoff_results: list[dict[str, Any]]
    active_specialist: str
    # Token budget tracking.
    token_budget_remaining: int
    token_budget_used: int


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def hash_json(value: Any) -> str:
    normalized = json.dumps(value, sort_keys=True, default=str)
    return sha256(normalized.encode("utf-8")).hexdigest()


def new_run_state(system_prompt: str, user_input: str, run_id: str | None = None) -> RunState:
    """Build the initial state shape for a new run."""
    return {
        "run_id": run_id or str(uuid4()),
        "step": 0,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ],
        "completed_tasks": [],
        "tool_history": [],
        "memo_events": [],
        "retry_counts": {
            "invalid_json": 0,
            "memo_policy": 0,
            "provider_timeout": 0,
            "content_validation": 0,
            "finish_rejected": 0,
            "consecutive_empty": 0,
        },
        "policy_flags": {
            "memo_required": False,
            "memo_required_key": "",
            "memo_required_reason": "",
            "memo_retrieve_hits": 0,
            "memo_retrieve_misses": 0,
            "cache_reuse_hits": 0,
            "cache_reuse_misses": 0,
            "cache_reuse_attempted": [],
            "planner_timeout_mode": False,
        },
        "seen_tool_signatures": [],
        "tool_call_counts": {},
        "missions": [],
        "mission_reports": [],
        "active_mission_index": -1,
        "active_mission_id": 0,
        "mission_contracts": [],
        "structured_plan": None,
        "rerun_context": {},
        "pending_action": None,
        "pending_action_queue": [],
        "final_answer": "",
        "audit_report": None,
        "handoff_queue": [],
        "handoff_results": [],
        "active_specialist": "supervisor",
        "token_budget_remaining": 100_000,
        "token_budget_used": 0,
    }


def ensure_state_defaults(state: RunState | dict[str, Any], *, system_prompt: str = "") -> RunState:
    """Repair missing state keys so node handlers can run safely.

    Accepts either a raw dict or a typed RunState because graph frameworks and
    serializers may hand back partially-typed mapping objects.
    """
    state_dict = cast(dict[str, Any], state)

    if "run_id" not in state_dict:
        state_dict["run_id"] = str(uuid4())
    if "step" not in state_dict:
        state_dict["step"] = 0
    if "messages" not in state_dict:
        state_dict["messages"] = []
    if system_prompt and not state_dict["messages"]:
        state_dict["messages"] = [{"role": "system", "content": system_prompt}]
    if "completed_tasks" not in state_dict:
        state_dict["completed_tasks"] = []
    if "tool_history" not in state_dict:
        state_dict["tool_history"] = []
    if "memo_events" not in state_dict:
        state_dict["memo_events"] = []
    if "retry_counts" not in state_dict:
        state_dict["retry_counts"] = {}
    if "policy_flags" not in state_dict:
        state_dict["policy_flags"] = {}
    if "seen_tool_signatures" not in state_dict:
        state_dict["seen_tool_signatures"] = []
    if "tool_call_counts" not in state_dict:
        state_dict["tool_call_counts"] = {}
    if "missions" not in state_dict:
        state_dict["missions"] = []
    if "mission_reports" not in state_dict:
        state_dict["mission_reports"] = []
    if "active_mission_index" not in state_dict:
        state_dict["active_mission_index"] = -1
    if "active_mission_id" not in state_dict:
        state_dict["active_mission_id"] = 0
    if "mission_contracts" not in state_dict:
        state_dict["mission_contracts"] = []
    if "structured_plan" not in state_dict:
        state_dict["structured_plan"] = None
    if "rerun_context" not in state_dict:
        state_dict["rerun_context"] = {}
    if "pending_action" not in state_dict:
        state_dict["pending_action"] = None
    if "pending_action_queue" not in state_dict:
        state_dict["pending_action_queue"] = []
    if "final_answer" not in state_dict:
        state_dict["final_answer"] = ""
    if "audit_report" not in state_dict:
        state_dict["audit_report"] = None
    if "handoff_queue" not in state_dict:
        state_dict["handoff_queue"] = []
    if "handoff_results" not in state_dict:
        state_dict["handoff_results"] = []
    if "active_specialist" not in state_dict:
        state_dict["active_specialist"] = "supervisor"
    if "token_budget_remaining" not in state_dict:
        state_dict["token_budget_remaining"] = 100_000
    if "token_budget_used" not in state_dict:
        state_dict["token_budget_used"] = 0

    retry_counts = state_dict["retry_counts"]
    retry_counts.setdefault("invalid_json", 0)
    retry_counts.setdefault("memo_policy", 0)
    retry_counts.setdefault("provider_timeout", 0)
    retry_counts.setdefault("duplicate_tool", 0)
    retry_counts.setdefault("content_validation", 0)
    retry_counts.setdefault("finish_rejected", 0)
    retry_counts.setdefault("consecutive_empty", 0)

    policy_flags = state_dict["policy_flags"]
    policy_flags.setdefault("memo_required", False)
    policy_flags.setdefault("memo_required_key", "")
    policy_flags.setdefault("memo_required_reason", "")
    policy_flags.setdefault("memo_retrieve_hits", 0)
    policy_flags.setdefault("memo_retrieve_misses", 0)
    policy_flags.setdefault("cache_reuse_hits", 0)
    policy_flags.setdefault("cache_reuse_misses", 0)
    policy_flags.setdefault("cache_reuse_attempted", [])
    policy_flags.setdefault("planner_timeout_mode", False)

    # Message compaction — sliding window, drop oldest non-system messages
    _threshold = int(os.getenv("P1_MESSAGE_COMPACTION_THRESHOLD", "40"))
    _messages = state_dict.get("messages", [])
    if len(_messages) > _threshold:
        _system_msgs = [m for m in _messages if m.get("role") == "system"]
        _non_system = [m for m in _messages if m.get("role") != "system"]
        _keep_count = max(0, _threshold - len(_system_msgs))
        state_dict["messages"] = _system_msgs + _non_system[-_keep_count:]

    return cast(RunState, state_dict)
