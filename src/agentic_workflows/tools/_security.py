from __future__ import annotations

"""Shared path-traversal guard used by filesystem-touching tools."""

from pathlib import Path
from typing import Any


def validate_path_within_cwd(path_str: str) -> tuple[Path, dict[str, Any] | None]:
    """Resolve *path_str* and verify it sits under the current working directory.

    Returns ``(resolved_path, None)`` on success, or
    ``(Path(), {"error": ...})`` when the path is invalid or escapes cwd.
    """
    if not path_str:
        return Path(), {"error": "path is required"}

    cwd = Path.cwd().resolve()
    try:
        target = Path(path_str).resolve()
    except Exception:
        return Path(), {"error": f"invalid path: {path_str}"}

    try:
        target.relative_to(cwd)
    except ValueError:
        return Path(), {"error": f"path outside working directory: {path_str}"}

    return target, None
