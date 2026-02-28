from __future__ import annotations

"""JSON parse/validate/flatten/path-extract tool."""

import json
from typing import Any, Dict

from tools.base import Tool

_VALID_OPERATIONS = {
    "parse", "validate", "extract_keys", "flatten",
    "get_path", "pretty_print", "count_elements",
}


class JsonParserTool(Tool):
    name = "json_parser"
    description = (
        "Parse, validate, flatten, and extract data from JSON strings. "
        "Required args: text (JSON string), operation (string). "
        "Operations: parse, validate, extract_keys, flatten, get_path, pretty_print, count_elements. "
        "Optional: path (for get_path, dot-notation e.g. 'users.0.name'), schema (for validate)."
    )

    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        text = args.get("text")
        operation = str(args.get("operation", "")).strip().lower()

        if text is None:
            return {"error": "text is required"}
        if not operation:
            return {"error": "operation is required"}
        if operation not in _VALID_OPERATIONS:
            return {"error": f"unknown operation '{operation}'. Valid: {sorted(_VALID_OPERATIONS)}"}

        # Parse JSON first
        text_str = str(text)
        try:
            parsed = json.loads(text_str)
        except json.JSONDecodeError as exc:
            if operation == "validate":
                return {"valid": False, "error": str(exc)}
            return {"error": f"invalid JSON: {str(exc)}"}

        dispatch = {
            "parse": lambda: {"parsed": parsed},
            "validate": lambda: self._validate(parsed, args.get("schema")),
            "extract_keys": lambda: self._extract_keys(parsed),
            "flatten": lambda: self._flatten(parsed),
            "get_path": lambda: self._get_path(parsed, str(args.get("path", ""))),
            "pretty_print": lambda: {"pretty": json.dumps(parsed, indent=2, default=str)},
            "count_elements": lambda: self._count_elements(parsed),
        }
        return dispatch[operation]()

    def _validate(self, parsed: Any, schema: Any) -> Dict[str, Any]:
        if schema is None:
            return {"valid": True, "type": type(parsed).__name__}
        # Simple type-based schema validation
        if isinstance(schema, dict):
            if not isinstance(parsed, dict):
                return {"valid": False, "error": f"expected object, got {type(parsed).__name__}"}
            missing = [k for k in schema if k not in parsed]
            if missing:
                return {"valid": False, "error": f"missing keys: {missing}"}
            return {"valid": True, "type": "object", "keys": list(parsed.keys())}
        return {"valid": True, "type": type(parsed).__name__}

    def _extract_keys(self, parsed: Any) -> Dict[str, Any]:
        if isinstance(parsed, dict):
            return {"keys": list(parsed.keys()), "count": len(parsed)}
        if isinstance(parsed, list):
            all_keys: list[str] = []
            for item in parsed:
                if isinstance(item, dict):
                    for k in item:
                        if k not in all_keys:
                            all_keys.append(k)
            return {"keys": all_keys, "count": len(all_keys)}
        return {"keys": [], "count": 0}

    def _flatten(self, parsed: Any, prefix: str = "") -> Dict[str, Any]:
        flat: Dict[str, Any] = {}
        self._flatten_recursive(parsed, prefix, flat)
        return {"flattened": flat}

    def _flatten_recursive(self, obj: Any, prefix: str, flat: Dict[str, Any]) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                new_key = f"{prefix}.{k}" if prefix else k
                self._flatten_recursive(v, new_key, flat)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                new_key = f"{prefix}.{i}" if prefix else str(i)
                self._flatten_recursive(v, new_key, flat)
        else:
            flat[prefix] = obj

    def _get_path(self, parsed: Any, path: str) -> Dict[str, Any]:
        if not path:
            return {"error": "path is required for get_path operation"}
        parts = path.split(".")
        current = parsed
        for part in parts:
            if isinstance(current, dict):
                if part not in current:
                    return {"error": f"key '{part}' not found at path '{path}'", "found": False}
                current = current[part]
            elif isinstance(current, list):
                try:
                    idx = int(part)
                except ValueError:
                    return {"error": f"invalid index '{part}' for list at path '{path}'", "found": False}
                if idx < 0 or idx >= len(current):
                    return {"error": f"index {idx} out of range at path '{path}'", "found": False}
                current = current[idx]
            else:
                return {"error": f"cannot traverse into {type(current).__name__} at '{part}'", "found": False}
        return {"value": current, "found": True, "path": path}

    def _count_elements(self, parsed: Any) -> Dict[str, Any]:
        if isinstance(parsed, dict):
            return {"count": len(parsed), "type": "object"}
        if isinstance(parsed, list):
            return {"count": len(parsed), "type": "array"}
        return {"count": 1, "type": type(parsed).__name__}
