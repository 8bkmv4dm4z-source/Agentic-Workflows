import re
from typing import Any

from agentic_workflows.tools.base import Tool


class _SafeDict(dict):
    """dict subclass that leaves missing keys unchanged as {key}."""

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


class FillTemplateTool(Tool):
    name = "fill_template"
    description = "Fills a {variable_name} template with provided variables. Missing placeholders are left unchanged."

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        template: str = args.get("template", "")
        variables: dict = args.get("variables") or {}

        if not isinstance(template, str):
            return {"error": "template must be a string"}
        if not isinstance(variables, dict):
            return {"error": "variables must be a dict"}

        placeholders = set(re.findall(r"\{(\w+)\}", template))
        var_keys = set(str(k) for k in variables)

        missing = sorted(placeholders - var_keys)
        extra = sorted(var_keys - placeholders)

        try:
            result = template.format_map(_SafeDict(variables))
        except (ValueError, KeyError) as exc:
            return {"error": f"template fill failed: {str(exc)}"}

        return {
            "result": result,
            "filled_count": len(placeholders) - len(missing),
            "missing": missing,
            "extra": extra,
        }
