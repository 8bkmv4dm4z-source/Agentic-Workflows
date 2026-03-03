from __future__ import annotations

"""Agent-callable tool that signals a context reset request."""

from typing import Any

from .base import Tool


class ClearContextTool(Tool):
    name = "clear_context"
    description = (
        "Signal that the conversation context should be minimized after this run. "
        "Args: scope='missions'|'full'. Returns a status signal dict."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        scope = str(args.get("scope", "missions")).strip()
        if scope not in {"missions", "full"}:
            scope = "missions"
        return {
            "status": "clear_requested",
            "scope": scope,
            "message": f"Context will be minimized (scope={scope}) after this mission completes.",
        }
