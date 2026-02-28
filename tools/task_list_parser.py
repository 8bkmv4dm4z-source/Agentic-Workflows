from __future__ import annotations

"""Tool wrapper around the structured mission parser."""

from typing import Any, Dict

from tools.base import Tool


class TaskListParserTool(Tool):
    name = "task_list_parser"
    description = (
        "Parse raw task text into structured task list with sub-tasks and tool suggestions. "
        "Required args: text (string)."
    )

    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        text = str(args.get("text", "")).strip()
        if not text:
            return {"error": "text is required"}

        from execution.langgraph.mission_parser import parse_missions

        plan = parse_missions(text, timeout_seconds=5.0)
        return {
            "tasks": [step.to_dict() for step in plan.steps],
            "flat_missions": plan.flat_missions,
            "parsing_method": plan.parsing_method,
        }
