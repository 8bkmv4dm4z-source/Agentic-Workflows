from __future__ import annotations

"""Tool for reading file contents from the local filesystem."""

from pathlib import Path
from typing import Any

from ._security import check_content_size, validate_path_within_sandbox
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

        # Security: sandbox path check
        sandbox_err = validate_path_within_sandbox(path_str)
        if sandbox_err is not None:
            return sandbox_err

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
            # Security: truncate output when cap is set
            size_err = check_content_size(content, "P1_READ_FILE_MAX_BYTES", 0)
            if size_err is not None:
                import os as _os
                max_bytes = int(_os.getenv("P1_READ_FILE_MAX_BYTES", "0") or "0")
                content = content[:max_bytes]
            return {
                "path": path_str,
                "content": content,
                "size_bytes": path.stat().st_size,
                "line_count": len(lines),
                "exists": True,
            }
        except OSError as exc:
            return {"error": str(exc), "path": path_str}
