from __future__ import annotations

"""File management tool: copy, move, rename, delete, mkdir, stat."""

import shutil
from pathlib import Path
from typing import Any

from ._security import validate_path_within_cwd
from .base import Tool

_VALID_OPERATIONS = {"copy", "move", "rename", "delete", "mkdir", "stat"}


class FileManagerTool(Tool):
    name = "file_manager"
    _args_schema = {
        "operation": {"type": "string", "required": "true"},
        "source": {"type": "string", "required": "true"},
        "destination": {"type": "string"},
        "force": {"type": "boolean"},
    }
    description = (
        "Manage files and directories. "
        "Required args: operation ('copy'|'move'|'rename'|'delete'|'mkdir'|'stat'), source (str). "
        "Optional: destination (str, required for copy/move/rename), force (bool, default False)."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        operation = str(args.get("operation", "")).strip().lower()
        if not operation:
            return {"error": "operation is required"}
        if operation not in _VALID_OPERATIONS:
            return {"error": f"unknown operation '{operation}'. Valid: {sorted(_VALID_OPERATIONS)}"}

        source_str = str(args.get("source", "")).strip()
        if not source_str:
            return {"error": "source is required"}

        force = bool(args.get("force", False))

        source, err = validate_path_within_cwd(source_str)
        if err:
            return err

        if operation == "stat":
            return _stat(source)
        elif operation == "mkdir":
            return _mkdir(source)
        elif operation == "delete":
            return _delete(source, force)
        else:
            dest_str = str(args.get("destination", "")).strip()
            if not dest_str:
                return {"error": "destination is required for " + operation}
            dest, err = validate_path_within_cwd(dest_str)
            if err:
                return err
            if operation == "copy":
                return _copy(source, dest)
            elif operation == "move":
                return _move(source, dest)
            elif operation == "rename":
                return _rename(source, dest)

        return {"error": "unexpected state"}


def _stat(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"error": f"not found: {path}"}
    try:
        st = path.stat()
        return {
            "path": str(path),
            "type": "directory" if path.is_dir() else "file",
            "size_bytes": st.st_size,
            "modified": st.st_mtime,
            "created": st.st_ctime,
            "permissions": oct(st.st_mode)[-3:],
        }
    except OSError as exc:
        return {"error": f"stat failed: {exc}"}


def _mkdir(path: Path) -> dict[str, Any]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return {"result": f"directory created: {path}"}
    except OSError as exc:
        return {"error": f"mkdir failed: {exc}"}


def _delete(path: Path, force: bool) -> dict[str, Any]:
    if not path.exists():
        return {"error": f"not found: {path}"}

    # Prevent deleting cwd
    cwd = Path.cwd().resolve()
    if path == cwd:
        return {"error": "cannot delete the current working directory"}

    try:
        if path.is_file() or path.is_symlink():
            path.unlink()
            return {"result": f"deleted file: {path}"}
        elif path.is_dir():
            if force:
                shutil.rmtree(path)
                return {"result": f"deleted directory: {path}"}
            else:
                # Only delete empty dirs without force
                try:
                    path.rmdir()
                    return {"result": f"deleted empty directory: {path}"}
                except OSError:
                    return {"error": f"directory not empty (use force=True): {path}"}
    except OSError as exc:
        return {"error": f"delete failed: {exc}"}
    return {"error": "unexpected state"}


def _copy(source: Path, dest: Path) -> dict[str, Any]:
    if not source.exists():
        return {"error": f"source not found: {source}"}
    try:
        if source.is_dir():
            shutil.copytree(source, dest)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
        return {"result": f"copied {source} -> {dest}"}
    except OSError as exc:
        return {"error": f"copy failed: {exc}"}


def _move(source: Path, dest: Path) -> dict[str, Any]:
    if not source.exists():
        return {"error": f"source not found: {source}"}
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(dest))
        return {"result": f"moved {source} -> {dest}"}
    except OSError as exc:
        return {"error": f"move failed: {exc}"}


def _rename(source: Path, dest: Path) -> dict[str, Any]:
    if not source.exists():
        return {"error": f"source not found: {source}"}
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        source.rename(dest)
        return {"result": f"renamed {source} -> {dest}"}
    except OSError as exc:
        return {"error": f"rename failed: {exc}"}
