from __future__ import annotations

"""JSON action parsing and validation extracted from graph.py.

All functions accept ``tool_registry`` (a ``dict[str, Tool]``) as an
explicit parameter instead of accessing ``self.tool_registry``.
"""

import json
import re
from typing import Any

from pydantic import ValidationError

from agentic_workflows.logger import get_logger
from agentic_workflows.schemas import FinishAction, ToolAction

_THINKING_RE = re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)
_LOG = get_logger("langgraph.action_parser")


def _strip_thinking(text: str) -> str:
    """Strip <thinking>...</thinking> scratchpad blocks before JSON extraction."""
    return _THINKING_RE.sub("", text).strip()


def validate_action(
    model_output: str, tool_registry: dict[str, Any], step: int = 0
) -> tuple[dict[str, Any], bool]:
    """Validate model output against strict ToolAction/FinishAction schema.

    Returns a ``(validated_dict, used_fallback)`` tuple where ``used_fallback``
    is ``True`` when ``parse_action_json`` used the extract-first-object fallback.
    """
    data, used_fallback = parse_action_json(model_output, step=step)
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
    # Normalize {"tool": "finish"/"clarify", args/params/result...} — these aren't in the
    # tool registry so the tool-alias normalizer below won't catch them.
    _tool_key_val = str(data.get("tool", "")).strip().lower()
    if "action" not in data and _tool_key_val in {"finish", "clarify"}:
        _nested = data.get("args") or data.get("arguments") or data.get("params") or {}
        if _tool_key_val == "finish":
            _answer = (
                _nested.get("answer") or _nested.get("result") or _nested.get("content")
                if isinstance(_nested, dict) else str(_nested)
            ) or ""
            data = {"action": "finish", "answer": str(_answer)}
        else:
            _question = _nested.get("question", "") if isinstance(_nested, dict) else str(_nested)
            data = {"action": "clarify", "question": str(_question)}
        used_fallback = True
    # Normalize {"tool": "X", flat_args...} emitted by models that skip "action"+"tool_name"
    if (
        "action" not in data
        and "tool_name" not in data
        and isinstance(data.get("tool"), str)
        and str(data["tool"]).strip().lower() in tool_registry
    ):
        tool_name = str(data.pop("tool")).strip().lower()
        # "params" is treated as an arg-container alias alongside "args"/"arguments"
        _reserved2 = {"tool", "tool_name", "action", "args", "arguments", "params", "__mission_id"}
        flat_args = {k: v for k, v in data.items() if k not in _reserved2}
        resolved_args = data.get("args") or data.get("arguments") or data.get("params") or flat_args
        data = {
            "action": "tool",
            "tool_name": tool_name,
            "args": dict(resolved_args) if isinstance(resolved_args, dict) else {},
        }
        used_fallback = True
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
            return parsed.model_dump(), used_fallback
        except ValidationError as exc:
            raise ValueError(f"tool schema error: {str(exc)}") from exc
    if action == "finish":
        try:
            parsed_finish = FinishAction(**data)
            return parsed_finish.model_dump(), used_fallback
        except ValidationError as exc:
            raise ValueError(f"finish schema error: {str(exc)}") from exc
    if action == "clarify":
        return {
            "action": "clarify",
            "question": str(data.get("question", "I need more information to proceed.")),
        }, used_fallback
    raise ValueError("action must be 'tool' or 'finish'")


def parse_action_json(model_output: str, step: int = 0) -> tuple[dict[str, Any], bool]:
    """Parse planner output, recovering first JSON object when extra data is emitted.

    Returns a ``(data, used_fallback)`` tuple where ``used_fallback`` is ``True``
    when the extract-first-object fallback path was needed.
    """
    cleaned = _strip_thinking(model_output)
    try:
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError("action payload must be a JSON object")
        return data, False
    except json.JSONDecodeError as exc:
        candidate = extract_first_json_object(cleaned)
        if not candidate:
            raise ValueError(f"invalid json: {str(exc)}") from exc
        prefix = cleaned[: cleaned.find("{")] if "{" in cleaned else ""
        _LOG.warning(
            "PARSER FALLBACK used=extract_first_json step=%d model_output=%.200s",
            step,
            model_output,
        )
        if prefix.strip():
            _LOG.warning("PARSER FALLBACK prose_prefix=%.200s", prefix.strip())
        try:
            recovered = json.loads(candidate)
        except json.JSONDecodeError as recover_exc:
            raise ValueError(f"invalid json: {str(recover_exc)}") from recover_exc
        if not isinstance(recovered, dict):
            raise ValueError("action payload must be a JSON object") from None
        return recovered, True


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


def parse_all_actions_json(model_output: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse all JSON action objects from planner output.

    Returns a ``(actions, used_fallback)`` tuple where ``used_fallback`` is
    ``True`` when ``json.loads`` failed on the full output and the extract-all
    fallback path was used instead.
    """
    cleaned = _strip_thinking(model_output)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return [data], False
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
    return actions, bool(actions)


def validate_action_from_dict(
    action_dict: dict[str, Any], tool_registry: dict[str, Any]
) -> tuple[dict[str, Any], bool]:
    """Validate a pre-parsed action dict against Pydantic schemas.

    Returns a ``(validated_dict, used_fallback)`` tuple; ``used_fallback`` is
    propagated from ``validate_action``.
    """
    raw = dict(action_dict)
    mission_id = raw.get("__mission_id")
    sanitized = {key: value for key, value in raw.items() if not key.startswith("__")}
    validated, used_fallback = validate_action(json.dumps(sanitized), tool_registry)
    if isinstance(mission_id, int) and mission_id > 0:
        validated["__mission_id"] = mission_id
    return validated, used_fallback
