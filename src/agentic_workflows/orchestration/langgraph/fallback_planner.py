from __future__ import annotations

"""Timeout/fallback planning logic extracted from graph.py.

Deterministic action generation when the LLM provider times out or
the token budget is exhausted. Also includes tool argument normalization.
"""

from typing import Any

from agentic_workflows.orchestration.langgraph.mission_tracker import (
    all_missions_completed,
    build_auto_finish_answer,
    next_incomplete_mission,
    next_incomplete_mission_index,
)
from agentic_workflows.orchestration.langgraph.text_extractor import (
    extract_fibonacci_count,
    extract_numbers_from_text,
    extract_quoted_text,
    extract_write_path_from_mission,
    fibonacci_csv,
)


def deterministic_fallback_action(state: dict[str, Any]) -> dict[str, Any] | None:
    """Build a safe tool/finish action from local state when provider times out."""
    policy_flags = state.get("policy_flags", {})
    if policy_flags.get("memo_required"):
        key = str(policy_flags.get("memo_required_key", "")).strip()
        if key:
            source_tool = (
                str(policy_flags.get("last_tool_name", "memoize")).strip() or "memoize"
            )
            last_result = dict(policy_flags.get("last_tool_result", {}))
            value: Any = last_result if last_result else {"status": "memoized_by_fallback"}
            return {
                "action": "tool",
                "tool_name": "memoize",
                "args": {
                    "key": key,
                    "value": value,
                    "run_id": state["run_id"],
                    "source_tool": source_tool,
                },
            }

    if all_missions_completed(state):
        return {"action": "finish", "answer": build_auto_finish_answer(state)}

    mission = next_incomplete_mission(state).strip()
    if not mission:
        return {"action": "finish", "answer": build_auto_finish_answer(state)}
    mission_lower = mission.lower()

    repeat_text = extract_quoted_text(mission)
    if "repeat" in mission_lower and repeat_text:
        return {
            "action": "tool",
            "tool_name": "repeat_message",
            "args": {"message": repeat_text},
        }

    if "sort" in mission_lower:
        numbers = extract_numbers_from_text(mission)
        if numbers:
            order = "desc" if "desc" in mission_lower else "asc"
            return {
                "action": "tool",
                "tool_name": "sort_array",
                "args": {"items": numbers, "order": order},
            }

    if "uppercase" in mission_lower and repeat_text:
        return {
            "action": "tool",
            "tool_name": "string_ops",
            "args": {"text": repeat_text, "operation": "uppercase"},
        }
    if "lowercase" in mission_lower and repeat_text:
        return {
            "action": "tool",
            "tool_name": "string_ops",
            "args": {"text": repeat_text, "operation": "lowercase"},
        }
    if "reverse" in mission_lower and repeat_text:
        return {
            "action": "tool",
            "tool_name": "string_ops",
            "args": {"text": repeat_text, "operation": "reverse"},
        }

    if "fibonacci" in mission_lower and (
        "write" in mission_lower or "write_file" in mission_lower
    ):
        path = extract_write_path_from_mission(mission) or "fib.txt"
        count = extract_fibonacci_count(mission)
        mission_index = next_incomplete_mission_index(state)
        reports = state.get("mission_reports", [])
        if 0 <= mission_index < len(reports):
            expected = reports[mission_index].get("expected_fibonacci_count")
            if isinstance(expected, int) and expected > 0:
                count = expected
        return {
            "action": "tool",
            "tool_name": "write_file",
            "args": {"path": path, "content": fibonacci_csv(count)},
        }

    return None


def normalize_tool_args(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Normalize common argument aliases before tool execution."""
    normalized = dict(args)
    if tool_name == "sort_array":
        if "items" not in normalized and isinstance(normalized.get("array"), list):
            normalized["items"] = normalized.pop("array")
        if "items" not in normalized and isinstance(normalized.get("values"), list):
            normalized["items"] = normalized.pop("values")
    elif tool_name == "repeat_message":
        if "message" not in normalized and isinstance(normalized.get("text"), str):
            normalized["message"] = normalized.pop("text")
    elif tool_name == "string_ops":
        if "operation" not in normalized and isinstance(normalized.get("op"), str):
            normalized["operation"] = normalized.pop("op")
    elif tool_name == "write_file":
        if "path" not in normalized and isinstance(normalized.get("file_path"), str):
            normalized["path"] = normalized.pop("file_path")
        if "path" not in normalized and isinstance(normalized.get("filename"), str):
            normalized["path"] = normalized.pop("filename")
        if "content" not in normalized and isinstance(normalized.get("text"), str):
            normalized["content"] = normalized.pop("text")
        if "content" not in normalized and isinstance(normalized.get("data"), str):
            normalized["content"] = normalized.pop("data")
    elif tool_name == "memoize":
        if "value" not in normalized and "data" in normalized:
            normalized["value"] = normalized.pop("data")
    elif tool_name == "text_analysis":
        if "operation" not in normalized and isinstance(normalized.get("op"), str):
            normalized["operation"] = normalized.pop("op")
    elif tool_name == "data_analysis":
        if "numbers" not in normalized and isinstance(normalized.get("data"), list):
            normalized["numbers"] = normalized.pop("data")
        if "numbers" not in normalized and isinstance(normalized.get("values"), list):
            normalized["numbers"] = normalized.pop("values")
    elif tool_name == "regex_matcher":
        if "pattern" not in normalized and isinstance(normalized.get("regex"), str):
            normalized["pattern"] = normalized.pop("regex")
    return normalized
