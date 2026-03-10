import re
from typing import Any


class Tool:
    name: str
    description: str

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Tool must implement the execute method.")

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
