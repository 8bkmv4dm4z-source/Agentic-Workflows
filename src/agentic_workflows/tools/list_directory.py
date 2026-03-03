from __future__ import annotations

"""Directory listing tool with glob filtering."""

import fnmatch
import os
from pathlib import Path
from typing import Any

from ._security import validate_path_within_cwd
from .base import Tool


class ListDirectoryTool(Tool):
    name = "list_directory"
    description = (
        "List directory contents with optional filtering. "
        "Optional args: path (default '.'), recursive (bool), pattern (glob), "
        "include_hidden (bool), max_depth (int, cap 5), max_results (int, cap 1000)."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        path_str = str(args.get("path", ".")).strip() or "."
        recursive = bool(args.get("recursive", False))
        pattern = str(args.get("pattern", "")).strip()
        include_hidden = bool(args.get("include_hidden", False))
        max_depth = min(int(args.get("max_depth", 5)), 5)
        max_results = min(int(args.get("max_results", 1000)), 1000)

        target, err = validate_path_within_cwd(path_str)
        if err:
            return err

        if not target.is_dir():
            return {"error": f"not a directory: {path_str}"}

        entries: list[dict[str, Any]] = []
        truncated = False

        try:
            if recursive:
                for item in _walk_limited(target, max_depth, include_hidden):
                    if pattern and not fnmatch.fnmatch(item.name, pattern):
                        continue
                    entries.append(_entry_info(item))
                    if len(entries) >= max_results:
                        truncated = True
                        break
            else:
                for item in sorted(target.iterdir(), key=lambda p: p.name):
                    if not include_hidden and item.name.startswith("."):
                        continue
                    if pattern and not fnmatch.fnmatch(item.name, pattern):
                        continue
                    entries.append(_entry_info(item))
                    if len(entries) >= max_results:
                        truncated = True
                        break
        except PermissionError:
            return {"error": f"permission denied: {path_str}"}

        return {
            "entries": entries,
            "total_count": len(entries),
            "truncated": truncated,
        }


def _walk_limited(root: Path, max_depth: int, include_hidden: bool) -> list[Path]:
    """Walk directory tree up to max_depth, returning sorted paths."""
    results: list[Path] = []
    _walk_recursive(root, 0, max_depth, include_hidden, results)
    return results


def _walk_recursive(
    directory: Path, depth: int, max_depth: int, include_hidden: bool, results: list[Path]
) -> None:
    if depth > max_depth:
        return
    try:
        children = sorted(directory.iterdir(), key=lambda p: p.name)
    except PermissionError:
        return
    for item in children:
        if not include_hidden and item.name.startswith("."):
            continue
        results.append(item)
        if item.is_dir():
            _walk_recursive(item, depth + 1, max_depth, include_hidden, results)


def _entry_info(path: Path) -> dict[str, Any]:
    """Build entry metadata dict."""
    try:
        stat = path.stat()
        return {
            "name": path.name,
            "path": str(path),
            "type": "directory" if path.is_dir() else "file",
            "size_bytes": stat.st_size if path.is_file() else 0,
            "modified": os.path.getmtime(path),
        }
    except OSError:
        return {
            "name": path.name,
            "path": str(path),
            "type": "unknown",
            "size_bytes": 0,
            "modified": 0,
        }
