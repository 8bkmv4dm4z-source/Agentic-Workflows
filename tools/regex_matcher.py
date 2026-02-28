from __future__ import annotations

"""Regex find/replace/split/extract tool with safety limits."""

import re
from typing import Any, Dict

from tools.base import Tool

_MAX_INPUT_LENGTH = 100 * 1024  # 100KB safety limit

_VALID_OPERATIONS = {
    "find_all", "find_first", "split", "replace",
    "match", "count_matches", "extract_groups",
}


class RegexMatcherTool(Tool):
    name = "regex_matcher"
    description = (
        "Apply regex operations on text: find, replace, split, match, extract groups. "
        "Required args: text (string), pattern (regex string), operation (string). "
        "Operations: find_all, find_first, split, replace, match, count_matches, extract_groups. "
        "Optional: replacement (for replace operation)."
    )

    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        text = str(args.get("text", ""))
        pattern = str(args.get("pattern", ""))
        operation = str(args.get("operation", "")).strip().lower()

        if not text:
            return {"error": "text is required"}
        if not pattern:
            return {"error": "pattern is required"}
        if not operation:
            return {"error": "operation is required"}
        if operation not in _VALID_OPERATIONS:
            return {"error": f"unknown operation '{operation}'. Valid: {sorted(_VALID_OPERATIONS)}"}
        if len(text) > _MAX_INPUT_LENGTH:
            return {"error": f"input text exceeds maximum length of {_MAX_INPUT_LENGTH} bytes"}

        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            return {"error": f"invalid regex pattern: {str(exc)}"}

        dispatch = {
            "find_all": lambda: self._find_all(compiled, text),
            "find_first": lambda: self._find_first(compiled, text),
            "split": lambda: self._split(compiled, text),
            "replace": lambda: self._replace(compiled, text, args),
            "match": lambda: self._match(compiled, text),
            "count_matches": lambda: self._count_matches(compiled, text),
            "extract_groups": lambda: self._extract_groups(compiled, text),
        }
        return dispatch[operation]()

    def _find_all(self, compiled: re.Pattern, text: str) -> Dict[str, Any]:
        matches = compiled.findall(text)
        return {"matches": matches, "count": len(matches)}

    def _find_first(self, compiled: re.Pattern, text: str) -> Dict[str, Any]:
        m = compiled.search(text)
        if not m:
            return {"match": None, "found": False}
        return {
            "match": m.group(),
            "start": m.start(),
            "end": m.end(),
            "found": True,
        }

    def _split(self, compiled: re.Pattern, text: str) -> Dict[str, Any]:
        parts = compiled.split(text)
        return {"parts": parts, "count": len(parts)}

    def _replace(self, compiled: re.Pattern, text: str, args: Dict[str, Any]) -> Dict[str, Any]:
        replacement = str(args.get("replacement", ""))
        result = compiled.sub(replacement, text)
        return {"result": result, "original": text}

    def _match(self, compiled: re.Pattern, text: str) -> Dict[str, Any]:
        m = compiled.search(text)
        return {"matches": m is not None}

    def _count_matches(self, compiled: re.Pattern, text: str) -> Dict[str, Any]:
        matches = compiled.findall(text)
        return {"count": len(matches)}

    def _extract_groups(self, compiled: re.Pattern, text: str) -> Dict[str, Any]:
        all_groups = []
        for m in compiled.finditer(text):
            groups = m.groups()
            if groups:
                all_groups.append(list(groups))
            else:
                all_groups.append([m.group()])
        return {"groups": all_groups, "count": len(all_groups)}
