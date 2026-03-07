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
        artifact_dir = str(os.getenv("P1_RUN_ARTIFACT_DIR", "")).strip()
        if artifact_dir and not os.path.isabs(path) and not os.path.dirname(path):
            os.makedirs(artifact_dir, exist_ok=True)
            target_path = os.path.join(artifact_dir, path)
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
