from __future__ import annotations

"""Tool wrapper around the structured mission parser."""

from typing import Any

from agentic_workflows.tools.base import Tool


class TaskListParserTool(Tool):
    name = "task_list_parser"
    description = (
        "Parse raw task text into structured task list with sub-tasks and tool suggestions. "
        "Required args: text (string)."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        text = str(args.get("text", "")).strip()
        if not text:
            return {"error": "text is required"}

        from agentic_workflows.orchestration.langgraph.mission_parser import parse_missions

        plan = parse_missions(text, timeout_seconds=5.0)
        return {
            "tasks": [step.to_dict() for step in plan.steps],
            "flat_missions": plan.flat_missions,
            "parsing_method": plan.parsing_method,
        }
