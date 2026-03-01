from typing import Any

from agentic_workflows.tools.base import Tool


class MemoizeTool(Tool):
    name = "memoize"
    description = "Memoizes the result of a tool call by writing a key-value pair to a file."

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        key: str = args.get("key", "")
        value: Any = args.get("value")

        if not key:
            return {"error": "key is required"}
        if value is None:
            return {"error": "value is required"}

        try:
            with open(key, "w") as f:
                f.write(str(value))
            return {"result": f"Successfully memoized {len(str(value))} characters to {key}"}
        except Exception as e:
            return {"error": f"Failed to memoize: {str(e)}"}
