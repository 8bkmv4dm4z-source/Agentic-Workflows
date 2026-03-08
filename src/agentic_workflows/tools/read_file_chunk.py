from __future__ import annotations

"""Tool for reading large files in chunks to avoid context overflow."""

from pathlib import Path
from typing import Any

from ._security import validate_path_within_sandbox
from .base import Tool

DEFAULT_CHUNK_LINES = 150


class ReadFileChunkTool(Tool):
    name = "read_file_chunk"
    description = (
        "Read a large file in chunks to avoid filling the context window. "
        "Required args: path (str). "
        "Optional: offset (int, 0-based line number to start from, default 0), "
        "limit (int, max lines to return, default 150). "
        "Returns: content, offset, lines_returned, total_lines, has_more, next_offset. "
        "Use next_offset as the next offset value to read the following chunk."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        path_str = str(args.get("path", "")).strip()
        if not path_str:
            return {"error": "path is required"}

        sandbox_err = validate_path_within_sandbox(path_str)
        if sandbox_err is not None:
            return sandbox_err

        path = Path(path_str)
        if not path.exists():
            return {"error": f"file not found: {path_str}", "path": path_str}
        if not path.is_file():
            return {"error": f"not a file: {path_str}", "path": path_str}

        try:
            offset = max(0, int(args.get("offset", 0)))
            limit = max(1, int(args.get("limit", DEFAULT_CHUNK_LINES)))
        except (ValueError, TypeError):
            return {"error": "offset and limit must be integers"}

        try:
            all_lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        except OSError as exc:
            return {"error": str(exc), "path": path_str}

        total_lines = len(all_lines)
        chunk = all_lines[offset : offset + limit]
        content = "".join(chunk)
        lines_returned = len(chunk)
        end = offset + lines_returned
        has_more = end < total_lines

        return {
            "path": path_str,
            "content": content,
            "offset": offset,
            "lines_returned": lines_returned,
            "total_lines": total_lines,
            "has_more": has_more,
            "next_offset": end if has_more else None,
        }
