from __future__ import annotations

"""JSON action parsing and validation extracted from graph.py.

All functions accept ``tool_registry`` (a ``dict[str, Tool]``) as an
explicit parameter instead of accessing ``self.tool_registry``.
"""

import json
import re
from typing import Any

from pydantic import ValidationError

from agentic_workflows.schemas import FinishAction, ToolAction

_THINKING_RE = re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)


def _strip_thinking(text: str) -> str:
    """Strip <thinking>...</thinking> scratchpad blocks before JSON extraction."""
    return _THINKING_RE.sub("", text).strip()


def validate_action(
    model_output: str, tool_registry: dict[str, Any]
) -> dict[str, Any]:
    """Validate model output against strict ToolAction/FinishAction schema."""
    data = parse_action_json(model_output)
    action_alias = str(data.get("action", "")).strip().lower()
    if (
        "tool_name" not in data
        and isinstance(data.get("action"), str)
        and action_alias in tool_registry
    ):
        _reserved = {"action", "tool_name", "args", "arguments", "name", "__mission_id"}
        flat_args = {k: v for k, v in data.items() if k not in _reserved}
        # Prefer "args", then "arguments" (OpenAI-style), then flat remaining keys
        resolved_args = data.get("args") or data.get("arguments") or flat_args
        data = {
            "action": "tool",
            "tool_name": action_alias,
            "args": dict(resolved_args) if isinstance(resolved_args, dict) else {},
        }
    if (
        data.get("action") == "tool"
        and "tool_name" not in data
        and isinstance(data.get("name"), str)
    ):
        data["tool_name"] = data["name"]
    # Normalize "arguments" → "args" for models using OpenAI-style format
    if "arguments" in data and "args" not in data:
        args_val = data.pop("arguments")
        data["args"] = dict(args_val) if isinstance(args_val, dict) else {}
    action = str(data.get("action", "")).strip().lower()
    if action in {"tool", "finish"}:
        data["action"] = action
    if action == "tool":
        try:
            parsed = ToolAction(**data)
            return parsed.model_dump()
        except ValidationError as exc:
            raise ValueError(f"tool schema error: {str(exc)}") from exc
    if action == "finish":
        try:
            parsed_finish = FinishAction(**data)
            return parsed_finish.model_dump()
        except ValidationError as exc:
            raise ValueError(f"finish schema error: {str(exc)}") from exc
    if action == "clarify":
        return {
            "action": "clarify",
            "question": str(data.get("question", "I need more information to proceed.")),
        }
    raise ValueError("action must be 'tool' or 'finish'")


def parse_action_json(model_output: str) -> dict[str, Any]:
    """Parse planner output, recovering first JSON object when extra data is emitted."""
    cleaned = _strip_thinking(model_output)
    try:
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError("action payload must be a JSON object")
        return data
    except json.JSONDecodeError as exc:
        candidate = extract_first_json_object(cleaned)
        if not candidate:
            raise ValueError(f"invalid json: {str(exc)}") from exc
        try:
            recovered = json.loads(candidate)
        except json.JSONDecodeError as recover_exc:
            raise ValueError(f"invalid json: {str(recover_exc)}") from recover_exc
        if not isinstance(recovered, dict):
            raise ValueError("action payload must be a JSON object") from None
        return recovered


def extract_first_json_object(text: str) -> str | None:
    """Return first balanced JSON object from text, ignoring surrounding noise."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def extract_all_json_objects(text: str) -> list[str]:
    """Extract all top-level balanced JSON objects from text."""
    objects: list[str] = []
    pos = 0
    while pos < len(text):
        start = text.find("{", pos)
        if start < 0:
            break
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == "{":
                depth += 1
                continue
            if char == "}":
                depth -= 1
                if depth == 0:
                    objects.append(text[start : index + 1])
                    pos = index + 1
                    break
        else:
            break  # unbalanced — stop
    return objects


def parse_all_actions_json(model_output: str) -> list[dict[str, Any]]:
    """Parse all JSON action objects from planner output."""
    cleaned = _strip_thinking(model_output)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return [data]
    except json.JSONDecodeError:
        pass

    candidates = extract_all_json_objects(cleaned)
    actions = []
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict) and "action" in parsed:
                actions.append(parsed)
        except (json.JSONDecodeError, ValueError):
            continue
    return actions


def validate_action_from_dict(
    action_dict: dict[str, Any], tool_registry: dict[str, Any]
) -> dict[str, Any]:
    """Validate a pre-parsed action dict against Pydantic schemas."""
    raw = dict(action_dict)
    mission_id = raw.get("__mission_id")
    sanitized = {key: value for key, value in raw.items() if not key.startswith("__")}
    validated = validate_action(json.dumps(sanitized), tool_registry)
    if isinstance(mission_id, int) and mission_id > 0:
        validated["__mission_id"] = mission_id
    return validated
