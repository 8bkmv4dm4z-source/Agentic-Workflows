from __future__ import annotations

"""Tool for reading file contents from the local filesystem."""

from pathlib import Path
from typing import Any

from .base import Tool


class ReadFileTool(Tool):
    name = "read_file"
    description = (
        "Read the contents of a file. "
        "Required args: path (str). "
        "Optional: start_line (int, 1-based), end_line (int, inclusive)."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        path_str = str(args.get("path", "")).strip()
        if not path_str:
            return {"error": "path is required"}
        path = Path(path_str)
        if not path.exists():
            return {"error": f"file not found: {path_str}", "path": path_str, "exists": False}
        if not path.is_file():
            return {"error": f"not a file: {path_str}", "path": path_str}
        try:
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            start = args.get("start_line")
            end = args.get("end_line")
            if start is not None or end is not None:
                # 1-based inclusive slice
                s = max(1, int(start or 1)) - 1
                e = int(end) if end is not None else len(lines)
                lines = lines[s:e]
            content = "".join(lines)
            return {
                "path": path_str,
                "content": content,
                "size_bytes": path.stat().st_size,
                "line_count": len(lines),
                "exists": True,
            }
        except OSError as exc:
            return {"error": str(exc), "path": path_str}
