# tools/sort_array.py

from typing import Dict, Any, List
from tools.base import Tool


class SortArrayTool(Tool):
    name = "sort_array"
    description = (
        "Sorts a list of numbers or strings. "
        "Returns the sorted list and basic metadata."
    )

    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        items: List = args.get("items", [])
        order: str = args.get("order", "asc")  # "asc" or "desc"

        if not isinstance(items, list):
            return {"error": "items must be a list"}

        if not items:
            return {"sorted": [], "count": 0, "order": order}

        # Validate all items are the same comparable type
        first_type = type(items[0])
        if not all(isinstance(i, (int, float, str)) for i in items):
            return {"error": "items must contain only numbers or strings"}
        if not all(type(i) == first_type for i in items):
            # Allow int/float mixing
            if not all(isinstance(i, (int, float)) for i in items):
                return {"error": "cannot mix strings and numbers in items"}

        reverse = order == "desc"
        try:
            sorted_items = sorted(items, reverse=reverse)
        except TypeError as e:
            return {"error": f"sort_failed: {str(e)}"}

        return {
            "sorted": sorted_items,
            "count": len(sorted_items),
            "order": order,
            "original": items,
        }
