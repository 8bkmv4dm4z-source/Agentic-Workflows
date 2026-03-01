from __future__ import annotations

"""Typed state contract for Phase 1 graph orchestration.

The graph can re-enter nodes with partially populated state snapshots. This file
keeps the canonical schema and provides a defaulting function that hardens state
before each node executes.
"""

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal, TypedDict, cast
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


class RunState(TypedDict):
    # Run identity and step position.
    run_id: str
    step: int
    # Full conversation transcript used by the planning model.
    messages: list[AgentMessage]
    # Logical mission tracking used for per-mission reporting.
    completed_tasks: list[str]
    # Tool execution audit trail.
    tool_history: list[ToolRecord]
    memo_events: list[MemoEvent]
    # Retry counters for diagnostics and guardrail enforcement.
    retry_counts: dict[str, int]
    policy_flags: dict[str, Any]
    # Duplicate-call prevention and tool usage telemetry.
    seen_tool_signatures: list[str]
    tool_call_counts: dict[str, int]
    # Human-readable mission-level report data.
    missions: list[str]
    mission_reports: list[MissionReport]
    active_mission_index: int
    # Structured plan from mission parser (serialized StructuredPlan).
    structured_plan: dict[str, Any] | None
    # Planned action and terminal answer.
    pending_action: dict[str, Any] | None
    final_answer: str


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
        },
        "policy_flags": {
            "memo_required": False,
            "memo_required_key": "",
            "memo_required_reason": "",
            "memo_retrieve_hits": 0,
            "memo_retrieve_misses": 0,
            "cache_reuse_hits": 0,
            "cache_reuse_misses": 0,
            "planner_timeout_mode": False,
        },
        "seen_tool_signatures": [],
        "tool_call_counts": {},
        "missions": [],
        "mission_reports": [],
        "active_mission_index": -1,
        "structured_plan": None,
        "pending_action": None,
        "final_answer": "",
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
    if "structured_plan" not in state_dict:
        state_dict["structured_plan"] = None
    if "pending_action" not in state_dict:
        state_dict["pending_action"] = None
    if "final_answer" not in state_dict:
        state_dict["final_answer"] = ""

    retry_counts = state_dict["retry_counts"]
    retry_counts.setdefault("invalid_json", 0)
    retry_counts.setdefault("memo_policy", 0)
    retry_counts.setdefault("provider_timeout", 0)
    retry_counts.setdefault("duplicate_tool", 0)
    retry_counts.setdefault("content_validation", 0)

    policy_flags = state_dict["policy_flags"]
    policy_flags.setdefault("memo_required", False)
    policy_flags.setdefault("memo_required_key", "")
    policy_flags.setdefault("memo_required_reason", "")
    policy_flags.setdefault("memo_retrieve_hits", 0)
    policy_flags.setdefault("memo_retrieve_misses", 0)
    policy_flags.setdefault("cache_reuse_hits", 0)
    policy_flags.setdefault("cache_reuse_misses", 0)
    policy_flags.setdefault("planner_timeout_mode", False)

    return cast(RunState, state_dict)
