import re
from typing import Any


class Tool:
    name: str
    description: str
    _args_schema: dict[str, dict[str, str]] | None = None

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Tool must implement the execute method.")

    @property
    def args_schema(self) -> dict[str, dict[str, str]]:
        """Return typed argument schema for this tool.

        Subclasses set ``_args_schema`` class variable. Falls back to
        ``required_args()`` regex parsing for backward compatibility.
        """
        if self._args_schema is not None:
            return self._args_schema
        return {arg: {"type": "string"} for arg in self.required_args()}

    def required_args(self) -> list[str]:
        """Extract required arg names from the description string.

        Parses segments like 'Required args: path (str), content (str). Optional: ...'
        Returns arg names in order, or [] when no Required args section exists.
        """
        desc = getattr(self, "description", "")
        m = re.search(r"Required args?:\s*(.+?)(?:\.|Optional|$)", desc, re.IGNORECASE)
        if not m:
            return []
        segment = m.group(1)
        return [
            re.split(r"\s*[\(,]", a.strip())[0]
            for a in segment.split(",")
            if a.strip()
        ]
