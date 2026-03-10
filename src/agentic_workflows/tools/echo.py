from typing import Any

from agentic_workflows.tools.base import Tool


class EchoTool(Tool):
    name = "repeat_message"
    _args_schema = {
        "message": {"type": "string", "required": "true"},
    }
    description = "Returns the same message that is passed to it. Required args: message (string)."

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        message = args.get("message", "")
        return {"echo": message}
