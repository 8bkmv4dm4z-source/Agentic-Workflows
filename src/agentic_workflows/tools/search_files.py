from __future__ import annotations

"""File search tool using glob patterns."""

import os
from typing import Any

from ._security import validate_path_within_cwd
from .base import Tool


class SearchFilesTool(Tool):
    name = "search_files"
    _args_schema = {
        "pattern": {"type": "string", "required": "true"},
        "path": {"type": "string"},
        "max_results": {"type": "number"},
    }
    description = (
        "Search for files matching a glob pattern. "
        "Required args: pattern (str, glob). "
        "Optional: path (default '.'), max_results (int, cap 500)."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        pattern = str(args.get("pattern", "")).strip()
        if not pattern:
            return {"error": "pattern is required"}

        path_str = str(args.get("path", ".")).strip() or "."
        max_results = min(int(args.get("max_results", 500)), 500)

        target, err = validate_path_within_cwd(path_str)
        if err:
            return err

        if not target.is_dir():
            return {"error": f"not a directory: {path_str}"}

        matches: list[dict[str, Any]] = []
        truncated = False

        try:
            # Use rglob for recursive matching
            for item in target.rglob(pattern):
                if item.name.startswith("."):
                    continue
                try:
                    stat = item.stat()
                    matches.append({
                        "path": str(item),
                        "name": item.name,
                        "size_bytes": stat.st_size if item.is_file() else 0,
                        "modified": os.path.getmtime(item),
                    })
                except OSError:
                    matches.append({
                        "path": str(item),
                        "name": item.name,
                        "size_bytes": 0,
                        "modified": 0,
                    })
                if len(matches) >= max_results:
                    truncated = True
                    break
        except PermissionError:
            return {"error": f"permission denied: {path_str}"}

        return {
            "matches": matches,
            "count": len(matches),
            "truncated": truncated,
        }
