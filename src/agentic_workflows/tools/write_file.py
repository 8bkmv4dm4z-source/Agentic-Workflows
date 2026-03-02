import os
from typing import Any

from agentic_workflows.tools.base import Tool


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
