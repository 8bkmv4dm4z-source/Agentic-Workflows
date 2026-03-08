from __future__ import annotations

"""Timeout/fallback planning logic extracted from graph.py.

Deterministic action generation when the LLM provider times out or
the token budget is exhausted. Also includes tool argument normalization.
"""

import json
from typing import Any

from agentic_workflows.orchestration.langgraph.mission_tracker import (
    all_missions_completed,
    build_auto_finish_answer,
    next_incomplete_mission,
    next_incomplete_mission_index,
    next_incomplete_mission_requirements,
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

    def _action_signature(action: dict[str, Any]) -> str:
        tool_name = str(action.get("tool_name", ""))
        args = dict(action.get("args", {}))
        return f"{tool_name}:{json.dumps(args, sort_keys=True, default=str)}"

    def _is_duplicate_tool_action(action: dict[str, Any]) -> bool:
        if str(action.get("action", "")) != "tool":
            return False
        seen = {str(sig) for sig in state.get("seen_tool_signatures", [])}
        return _action_signature(action) in seen

    def _choose(action: dict[str, Any] | None) -> dict[str, Any] | None:
        if action is None:
            return None
        if _is_duplicate_tool_action(action):
            return None
        return action

    policy_flags = state.get("policy_flags", {})
    if policy_flags.get("memo_required"):
        key = str(policy_flags.get("memo_required_key", "")).strip()
        if key:
            source_tool = str(policy_flags.get("last_tool_name", "memoize")).strip() or "memoize"
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
    requirements = next_incomplete_mission_requirements(state)
    missing_tools = {str(tool) for tool in requirements.get("missing_tools", [])}
    missing_files = [str(path) for path in requirements.get("missing_files", [])]
    mission_index = int(requirements.get("mission_index", next_incomplete_mission_index(state)))
    reports = state.get("mission_reports", [])
    active_report = reports[mission_index] if 0 <= mission_index < len(reports) else {}

    repeat_text = extract_quoted_text(mission)
    if "repeat_message" in missing_tools and repeat_text and "write_file" not in missing_tools:
        action = {
            "action": "tool",
            "tool_name": "repeat_message",
            "args": {"message": repeat_text},
        }
        chosen = _choose(action)
        if chosen is not None:
            return chosen

    if "sort_array" in missing_tools and "sort" in mission_lower:
        numbers = extract_numbers_from_text(mission)
        if numbers:
            order = "desc" if "desc" in mission_lower else "asc"
            action = {
                "action": "tool",
                "tool_name": "sort_array",
                "args": {"items": numbers, "order": order},
            }
            chosen = _choose(action)
            if chosen is not None:
                return chosen

    if "string_ops" in missing_tools and "uppercase" in mission_lower and repeat_text:
        action = {
            "action": "tool",
            "tool_name": "string_ops",
            "args": {"text": repeat_text, "operation": "uppercase"},
        }
        chosen = _choose(action)
        if chosen is not None:
            return chosen
    if "string_ops" in missing_tools and "lowercase" in mission_lower and repeat_text:
        action = {
            "action": "tool",
            "tool_name": "string_ops",
            "args": {"text": repeat_text, "operation": "lowercase"},
        }
        chosen = _choose(action)
        if chosen is not None:
            return chosen
    if "string_ops" in missing_tools and "reverse" in mission_lower and repeat_text:
        action = {
            "action": "tool",
            "tool_name": "string_ops",
            "args": {"text": repeat_text, "operation": "reverse"},
        }
        chosen = _choose(action)
        if chosen is not None:
            return chosen

    should_try_fib_write = "write_file" in missing_tools or any(
        "fib" in missing.lower() for missing in missing_files
    )
    if (
        should_try_fib_write
        and "fibonacci" in mission_lower
        and ("write" in mission_lower or "write_file" in mission_lower)
    ):
        path = (
            extract_write_path_from_mission(mission)
            or str(active_report.get("required_files", [""])[0] if active_report else "")
            or "fib.txt"
        )
        count = extract_fibonacci_count(mission)
        if 0 <= mission_index < len(reports):
            expected = reports[mission_index].get("expected_fibonacci_count")
            if isinstance(expected, int) and expected > 0:
                count = expected
        action = {
            "action": "tool",
            "tool_name": "write_file",
            "args": {"path": path, "content": fibonacci_csv(count)},
        }
        chosen = _choose(action)
        if chosen is not None:
            return chosen

    if "repeat" in mission_lower and repeat_text:
        return _choose(
            {
                "action": "tool",
                "tool_name": "repeat_message",
                "args": {"message": repeat_text},
            }
        )

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
    elif tool_name == "outline_code":
        if "path" not in normalized and isinstance(normalized.get("file_path"), str):
            normalized["path"] = normalized.pop("file_path")
    elif tool_name in ("list_directory", "search_content", "search_files"):
        if "path" not in normalized and isinstance(normalized.get("directory"), str):
            normalized["path"] = normalized.pop("directory")
        if "pattern" not in normalized and isinstance(normalized.get("glob"), str):
            normalized["pattern"] = normalized.pop("glob")
        if "pattern" not in normalized and isinstance(normalized.get("query"), str):
            normalized["pattern"] = normalized.pop("query")
    elif tool_name == "compare_texts":
        if "text1" not in normalized and isinstance(normalized.get("left"), str):
            normalized["text1"] = normalized.pop("left")
        if "text2" not in normalized and isinstance(normalized.get("right"), str):
            normalized["text2"] = normalized.pop("right")
    elif tool_name == "file_manager":
        if "source" not in normalized and isinstance(normalized.get("src"), str):
            normalized["source"] = normalized.pop("src")
        if "destination" not in normalized and isinstance(normalized.get("dst"), str):
            normalized["destination"] = normalized.pop("dst")
        if "destination" not in normalized and isinstance(normalized.get("dest"), str):
            normalized["destination"] = normalized.pop("dest")
        if "operation" not in normalized and isinstance(normalized.get("op"), str):
            normalized["operation"] = normalized.pop("op")
    elif tool_name == "format_converter":
        if "from_format" not in normalized and isinstance(normalized.get("input_format"), str):
            normalized["from_format"] = normalized.pop("input_format")
        if "to_format" not in normalized and isinstance(normalized.get("output_format"), str):
            normalized["to_format"] = normalized.pop("output_format")
    elif tool_name in ("encode_decode", "classify_intent", "validate_data", "retrieve_run_context"):
        if "operation" not in normalized and isinstance(normalized.get("op"), str):
            normalized["operation"] = normalized.pop("op")
    return normalized
