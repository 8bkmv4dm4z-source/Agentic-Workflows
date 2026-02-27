from typing import Dict,Any
from tools.base import Tool


class EchoTool(Tool):
    name = "repeat_message"
    description = "Returns the same message that is passed to it. Required args: message (string)."
    def execute(self,args:Dict[str,Any])->Dict[str,Any]:
        message=args.get("message", "")
        return {"echo": message}
    