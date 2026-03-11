"""retrieve_tool_result — planner-callable cache retrieval with offset/limit chunking."""
from __future__ import annotations

from typing import Any

from .base import Tool

_DEFAULT_LIMIT = 3000


class RetrieveToolResultTool(Tool):
    """Retrieve a stored large tool result by its cache key with offset/limit chunking."""

    name = "retrieve_tool_result"
    _args_schema = {
        "key": {"type": "string", "required": "true"},
        "offset": {"type": "number"},
        "limit": {"type": "number"},
    }
    description = (
        "Retrieve a stored large tool result by its cache key. "
        "Required args: key (str, the hash from the compact pointer). "
        "Optional: offset (int, char offset into the result, default 0), "
        "limit (int, max chars to return, default 3000). "
        "Returns: result (str chunk), offset, limit, total (total chars), has_more (bool). "
        "Use has_more=True to loop: increment offset by limit until has_more is False."
    )

    def __init__(self, tool_result_cache: Any) -> None:
        self._cache = tool_result_cache

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        key = str(args.get("key", "")).strip()
        if not key:
            return {"error": "key is required"}

        try:
            offset = max(0, int(args.get("offset", 0)))
            limit = max(1, int(args.get("limit", _DEFAULT_LIMIT)))
        except (ValueError, TypeError):
            return {"error": "offset and limit must be integers"}

        if self._cache is None:
            return {"error": "cache miss — result expired or not found"}

        full_result = self._cache.get_by_key(args_hash=key)

        if full_result is None:
            return {"error": "cache miss — result expired or not found"}

        total = len(full_result)
        chunk = full_result[offset : offset + limit]
        chars_returned = len(chunk)
        end = offset + chars_returned
        has_more = end < total

        return {
            "result": chunk,
            "offset": offset,
            "limit": limit,
            "total": total,
            "has_more": has_more,
        }
