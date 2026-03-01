from typing import Any


class Tool:
    name: str
    description: str

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Tool must implement the execute method.")
