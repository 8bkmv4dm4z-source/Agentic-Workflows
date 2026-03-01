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

        try:
            with open(path, "w") as f:
                f.write(content)
            return {"result": f"Successfully wrote {len(content)} characters to {path}"}
        except Exception as e:
            return {"error": f"Failed to write file: {str(e)}"}
