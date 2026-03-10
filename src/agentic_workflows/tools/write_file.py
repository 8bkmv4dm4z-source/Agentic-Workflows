import os
from typing import Any

from agentic_workflows.tools._security import check_content_size, validate_path_within_sandbox
from agentic_workflows.tools.base import Tool


def _check_shebang_guard(path: str, content: str) -> dict[str, Any] | None:
    if path.endswith((".sh", ".bash")) and not content.lstrip().startswith("#!"):
        return {
            "error": "write_file_guardrail: shell scripts (.sh/.bash) must start with a shebang (#!)",
            "hint": "Add '#!/bin/bash' or '#!/bin/sh' as the first line.",
        }
    return None


class WriteFileTool(Tool):
    name = "write_file"
    _args_schema = {
        "path": {"type": "string", "required": "true"},
        "content": {"type": "string", "required": "true"},
    }
    description = "Writes content to a file. Overwrites if exists."

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        path: str = args.get("path", "")
        content: str = args.get("content", "")

        if not path:
            return {"error": "path is required"}
        if not content:
            return {"error": "content is required"}

        # Security: content size cap
        size_err = check_content_size(content, "P1_WRITE_FILE_MAX_BYTES", 0)
        if size_err is not None:
            return size_err

        # Security: sandbox path check
        sandbox_err = validate_path_within_sandbox(path)
        if sandbox_err is not None:
            return sandbox_err

        # Security: shell scripts must have a shebang
        shebang_err = _check_shebang_guard(path, content)
        if shebang_err is not None:
            return shebang_err

        target_path = path
        # Priority: P1_RUN_ARTIFACT_DIR > AGENT_WORKDIR > cwd
        # AGENT_WORKDIR is set by docker-compose to the host-mounted workspace
        # directory so that files written by the agent appear on the host.
        artifact_dir = str(os.getenv("P1_RUN_ARTIFACT_DIR", "")).strip()
        if not artifact_dir:
            artifact_dir = str(os.getenv("AGENT_WORKDIR", "")).strip()
        if artifact_dir:
            container_cwd = os.path.realpath(os.getcwd())
            abs_artifact_dir = os.path.realpath(artifact_dir)
            if not os.path.isabs(path):
                # Relative path (bare or with subdirs): place under workspace
                target_path = os.path.join(artifact_dir, path)
            elif os.path.realpath(path).startswith(abs_artifact_dir + os.sep) or os.path.realpath(path) == abs_artifact_dir:
                # Already inside the workspace — leave as-is to avoid double-nesting
                target_path = path
            elif path.startswith(container_cwd + os.sep) or path == container_cwd:
                # Absolute path under the container cwd (e.g. /app/fib.py):
                # redirect to workspace so files land on the host mount.
                rel = os.path.relpath(path, container_cwd)
                target_path = os.path.join(artifact_dir, rel)
            # else: explicit absolute path outside workspace — leave as-is
            os.makedirs(os.path.dirname(target_path) or artifact_dir, exist_ok=True)
        else:
            parent = os.path.dirname(target_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

        try:
            with open(target_path, "w", encoding="utf-8") as file_handle:
                file_handle.write(content)
            return {
                "result": f"Successfully wrote {len(content)} characters to {path}",
                "path": target_path,
            }
        except OSError as exc:
            return {"error": f"Failed to write file: {str(exc)}"}
