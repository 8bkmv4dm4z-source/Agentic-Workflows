# tools/math_stats.py

import math
import statistics
from typing import Dict, Any, List
from tools.base import Tool


SUPPORTED_OPS = {
    "add", "subtract", "multiply", "divide",
    "power", "sqrt", "abs",
    "mean", "median", "mode", "stdev", "variance",
    "min", "max", "sum",
}


class MathStatsTool(Tool):
    name = "math_stats"
    description = (
        "Performs math calculations and statistics on numbers. "
        "For single-number or two-number ops: add, subtract, multiply, divide, power, sqrt, abs. "
        "For list ops: mean, median, mode, stdev, variance, min, max, sum."
    )

    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        operation: str = args.get("operation", "")

        if operation not in SUPPORTED_OPS:
            return {
                "error": f"unknown operation '{operation}'",
                "supported_operations": sorted(SUPPORTED_OPS),
            }

        # --- Two-number arithmetic ---
        if operation in {"add", "subtract", "multiply", "divide", "power"}:
            a = args.get("a")
            b = args.get("b")
            if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
                return {"error": f"'{operation}' requires numeric args 'a' and 'b'"}

            if operation == "add":
                return {"result": a + b}
            if operation == "subtract":
                return {"result": a - b}
            if operation == "multiply":
                return {"result": a * b}
            if operation == "divide":
                if b == 0:
                    return {"error": "division by zero"}
                return {"result": a / b}
            if operation == "power":
                return {"result": a ** b}

        # --- Single-number ops ---
        if operation in {"sqrt", "abs"}:
            a = args.get("a")
            if not isinstance(a, (int, float)):
                return {"error": f"'{operation}' requires numeric arg 'a'"}
            if operation == "sqrt":
                if a < 0:
                    return {"error": "cannot take sqrt of a negative number"}
                return {"result": math.sqrt(a)}
            if operation == "abs":
                return {"result": abs(a)}

        # --- List/stats ops ---
        if operation in {"mean", "median", "mode", "stdev", "variance", "min", "max", "sum"}:
            numbers: List = args.get("numbers", [])
            if not isinstance(numbers, list) or not numbers:
                return {"error": f"'{operation}' requires a non-empty list arg 'numbers'"}
            if not all(isinstance(n, (int, float)) for n in numbers):
                return {"error": "'numbers' must contain only numeric values"}

            if operation == "sum":
                return {"result": sum(numbers)}
            if operation == "min":
                return {"result": min(numbers)}
            if operation == "max":
                return {"result": max(numbers)}
            if operation == "mean":
                return {"result": statistics.mean(numbers)}
            if operation == "median":
                return {"result": statistics.median(numbers)}
            if operation == "mode":
                try:
                    return {"result": statistics.mode(numbers)}
                except statistics.StatisticsError as e:
                    return {"error": str(e)}
            if operation == "stdev":
                if len(numbers) < 2:
                    return {"error": "stdev requires at least 2 values"}
                return {"result": statistics.stdev(numbers)}
            if operation == "variance":
                if len(numbers) < 2:
                    return {"error": "variance requires at least 2 values"}
                return {"result": statistics.variance(numbers)}

        return {"error": f"operation '{operation}' not implemented"}
