from __future__ import annotations

"""Content search (grep-like) tool."""

import fnmatch
import re
import time
from pathlib import Path
from typing import Any

from ._security import validate_path_within_cwd
from .base import Tool

_MAX_FILE_SIZE = 1_048_576  # 1MB per file
_SOFT_TIMEOUT = 10.0  # seconds


class SearchContentTool(Tool):
    name = "search_content"
    _args_schema = {
        "pattern": {"type": "string", "required": "true"},
        "path": {"type": "string"},
        "file_pattern": {"type": "string"},
        "max_results": {"type": "number"},
        "context_lines": {"type": "number"},
        "case_sensitive": {"type": "boolean"},
        "is_regex": {"type": "boolean"},
    }
    description = (
        "Search file contents for a pattern (grep-like). "
        "Required args: pattern (str). "
        "Optional: path (default '.'), file_pattern (glob filter), "
        "max_results (int, cap 200), context_lines (int, cap 5), "
        "case_sensitive (bool, default True), is_regex (bool, default False)."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        pattern = str(args.get("pattern", "")).strip()
        if not pattern:
            return {"error": "pattern is required"}

        path_str = str(args.get("path", ".")).strip() or "."
        file_pattern = str(args.get("file_pattern", "")).strip()
        max_results = min(int(args.get("max_results", 200)), 200)
        context_lines = min(int(args.get("context_lines", 0)), 5)
        case_sensitive = bool(args.get("case_sensitive", True))
        is_regex = bool(args.get("is_regex", False))

        target, err = validate_path_within_cwd(path_str)
        if err:
            return err

        if not target.is_dir() and not target.is_file():
            return {"error": f"path not found: {path_str}"}

        # Compile search pattern
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            if is_regex:
                regex = re.compile(pattern, flags)
            else:
                regex = re.compile(re.escape(pattern), flags)
        except re.error as exc:
            return {"error": f"invalid pattern: {exc}"}

        matches: list[dict[str, Any]] = []
        files_searched = 0
        files_with_matches: set[str] = set()
        start = time.monotonic()

        files = [target] if target.is_file() else list(_iter_files(target, file_pattern))

        for fpath in files:
            if time.monotonic() - start > _SOFT_TIMEOUT:
                break
            if len(matches) >= max_results:
                break
            files_searched += 1
            found = _search_file(fpath, regex, context_lines, max_results - len(matches))
            if found:
                files_with_matches.add(str(fpath))
                matches.extend(found)

        return {
            "matches": matches[:max_results],
            "files_searched": files_searched,
            "files_with_matches": len(files_with_matches),
        }


def _iter_files(root: Path, file_pattern: str) -> list[Path]:
    """Iterate text files under root, filtered by optional glob."""
    results: list[Path] = []
    try:
        for item in sorted(root.rglob("*")):
            if not item.is_file():
                continue
            if item.name.startswith("."):
                continue
            if file_pattern and not fnmatch.fnmatch(item.name, file_pattern):
                continue
            # Skip likely binary files
            if item.suffix.lower() in (".pyc", ".pyo", ".so", ".o", ".a", ".dll", ".exe",
                                        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico",
                                        ".zip", ".gz", ".tar", ".db", ".sqlite", ".sqlite3",
                                        ".whl", ".egg"):
                continue
            if item.stat().st_size > _MAX_FILE_SIZE:
                continue
            results.append(item)
    except PermissionError:
        pass
    return results


def _search_file(
    fpath: Path, regex: re.Pattern[str], context_lines: int, remaining: int
) -> list[dict[str, Any]]:
    """Search a single file and return match dicts."""
    try:
        text = fpath.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    lines = text.splitlines()
    results: list[dict[str, Any]] = []

    for i, line in enumerate(lines):
        if regex.search(line):
            match: dict[str, Any] = {
                "file": str(fpath),
                "line_number": i + 1,
                "line": line,
            }
            if context_lines > 0:
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)
                match["context_before"] = lines[start:i]
                match["context_after"] = lines[i + 1:end]
            results.append(match)
            if len(results) >= remaining:
                break

    return results
