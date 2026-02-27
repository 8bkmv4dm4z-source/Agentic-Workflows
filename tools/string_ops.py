# tools/string_ops.py

from typing import Dict, Any
from tools.base import Tool


SUPPORTED_OPS = {
    "uppercase", "lowercase", "reverse", "length",
    "trim", "replace", "split", "count_words",
    "startswith", "endswith", "contains",
}


class StringOpsTool(Tool):
    name = "string_ops"
    description = (
        "Performs string manipulation operations. "
        f"Supported operations: {', '.join(sorted(SUPPORTED_OPS))}."
    )

    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        text: str = args.get("text", "")
        operation: str = args.get("operation", "")

        if not isinstance(text, str):
            return {"error": "text must be a string"}

        if operation not in SUPPORTED_OPS:
            return {
                "error": f"unknown operation '{operation}'",
                "supported_operations": sorted(SUPPORTED_OPS),
            }

        # --- Operations ---

        if operation == "uppercase":
            return {"result": text.upper()}

        if operation == "lowercase":
            return {"result": text.lower()}

        if operation == "reverse":
            return {"result": text[::-1]}

        if operation == "length":
            return {"result": len(text)}

        if operation == "trim":
            return {"result": text.strip()}

        if operation == "count_words":
            return {"result": len(text.split())}

        if operation == "replace":
            old: str = args.get("old", "")
            new: str = args.get("new", "")
            if not isinstance(old, str) or not isinstance(new, str):
                return {"error": "'old' and 'new' must be strings for replace"}
            return {"result": text.replace(old, new)}

        if operation == "split":
            delimiter: str = args.get("delimiter", " ")
            return {"result": text.split(delimiter)}

        if operation == "startswith":
            prefix: str = args.get("prefix", "")
            return {"result": text.startswith(prefix)}

        if operation == "endswith":
            suffix: str = args.get("suffix", "")
            return {"result": text.endswith(suffix)}

        if operation == "contains":
            substring: str = args.get("substring", "")
            return {"result": substring in text}

        return {"error": f"operation '{operation}' not implemented"}
