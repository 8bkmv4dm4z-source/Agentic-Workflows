from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Literal, TypedDict
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


class RunState(TypedDict):
    run_id: str
    step: int
    messages: list[AgentMessage]
    completed_tasks: list[str]
    tool_history: list[ToolRecord]
    memo_events: list[MemoEvent]
    retry_counts: dict[str, int]
    policy_flags: dict[str, Any]
    seen_tool_signatures: list[str]
    tool_call_counts: dict[str, int]
    pending_action: dict[str, Any] | None
    final_answer: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_json(value: Any) -> str:
    normalized = json.dumps(value, sort_keys=True, default=str)
    return sha256(normalized.encode("utf-8")).hexdigest()


def new_run_state(system_prompt: str, user_input: str, run_id: str | None = None) -> RunState:
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
        "retry_counts": {"invalid_json": 0, "memo_policy": 0},
        "policy_flags": {
            "memo_required": False,
            "memo_required_key": "",
            "memo_required_reason": "",
        },
        "seen_tool_signatures": [],
        "tool_call_counts": {},
        "pending_action": None,
        "final_answer": "",
    }


def ensure_state_defaults(state: dict[str, Any], *, system_prompt: str = "") -> RunState:
    if "run_id" not in state:
        state["run_id"] = str(uuid4())
    if "step" not in state:
        state["step"] = 0
    if "messages" not in state:
        state["messages"] = []
    if system_prompt and not state["messages"]:
        state["messages"] = [{"role": "system", "content": system_prompt}]
    if "completed_tasks" not in state:
        state["completed_tasks"] = []
    if "tool_history" not in state:
        state["tool_history"] = []
    if "memo_events" not in state:
        state["memo_events"] = []
    if "retry_counts" not in state:
        state["retry_counts"] = {}
    if "policy_flags" not in state:
        state["policy_flags"] = {}
    if "seen_tool_signatures" not in state:
        state["seen_tool_signatures"] = []
    if "tool_call_counts" not in state:
        state["tool_call_counts"] = {}
    if "pending_action" not in state:
        state["pending_action"] = None
    if "final_answer" not in state:
        state["final_answer"] = ""

    retry_counts = state["retry_counts"]
    retry_counts.setdefault("invalid_json", 0)
    retry_counts.setdefault("memo_policy", 0)
    retry_counts.setdefault("duplicate_tool", 0)

    policy_flags = state["policy_flags"]
    policy_flags.setdefault("memo_required", False)
    policy_flags.setdefault("memo_required_key", "")
    policy_flags.setdefault("memo_required_reason", "")

    return state  # type: ignore[return-value]
