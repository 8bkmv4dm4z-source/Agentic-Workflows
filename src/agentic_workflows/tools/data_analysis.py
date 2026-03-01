from __future__ import annotations

"""Numeric analytics tool: summary stats, outliers, percentiles, z-scores, etc."""

import math
from typing import Any

from agentic_workflows.tools.base import Tool

_VALID_OPERATIONS = {
    "summary_stats",
    "outliers",
    "percentiles",
    "distribution",
    "correlation",
    "normalize",
    "z_scores",
}


class DataAnalysisTool(Tool):
    name = "data_analysis"
    description = (
        "Analyze numeric data for summary statistics, outliers, percentiles, distribution, "
        "correlation, normalization, and z-scores. "
        "Required args: numbers (list of numbers), operation (string). "
        "Operations: summary_stats, outliers, percentiles, distribution, correlation, normalize, z_scores. "
        "Optional: threshold (for outliers, default 1.5), numbers_b (for correlation)."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        numbers = args.get("numbers")
        operation = str(args.get("operation", "")).strip().lower()

        if not isinstance(numbers, list) or not numbers:
            return {"error": "numbers must be a non-empty list of numbers"}
        if not operation:
            return {"error": "operation is required"}
        if operation not in _VALID_OPERATIONS:
            return {"error": f"unknown operation '{operation}'. Valid: {sorted(_VALID_OPERATIONS)}"}

        try:
            nums = [float(n) for n in numbers]
        except (TypeError, ValueError):
            return {"error": "all items in numbers must be numeric"}

        dispatch = {
            "summary_stats": self._summary_stats,
            "outliers": self._outliers,
            "percentiles": self._percentiles,
            "distribution": self._distribution,
            "correlation": self._correlation,
            "normalize": self._normalize,
            "z_scores": self._z_scores,
        }

        if operation == "correlation":
            return dispatch[operation](nums, args)
        if operation == "outliers":
            threshold = float(args.get("threshold", 1.5))
            return dispatch[operation](nums, threshold)
        return dispatch[operation](nums)

    def _summary_stats(self, nums: list[float]) -> dict[str, Any]:
        n = len(nums)
        total = sum(nums)
        mean = total / n
        sorted_nums = sorted(nums)
        median = self._median(sorted_nums)
        variance = sum((x - mean) ** 2 for x in nums) / n
        stdev = math.sqrt(variance)
        return {
            "count": n,
            "sum": round(total, 6),
            "mean": round(mean, 6),
            "median": round(median, 6),
            "stdev": round(stdev, 6),
            "min": min(nums),
            "max": max(nums),
            "range": round(max(nums) - min(nums), 6),
        }

    def _outliers(self, nums: list[float], threshold: float = 1.5) -> dict[str, Any]:
        sorted_nums = sorted(nums)
        q1 = self._percentile_value(sorted_nums, 25)
        q3 = self._percentile_value(sorted_nums, 75)
        iqr = q3 - q1
        lower = q1 - threshold * iqr
        upper = q3 + threshold * iqr
        outliers = [x for x in nums if x < lower or x > upper]
        non_outliers = [x for x in nums if lower <= x <= upper]
        return {
            "outliers": outliers,
            "non_outliers": non_outliers,
            "q1": round(q1, 6),
            "q3": round(q3, 6),
            "iqr": round(iqr, 6),
            "lower_bound": round(lower, 6),
            "upper_bound": round(upper, 6),
            "threshold": threshold,
        }

    def _percentiles(self, nums: list[float]) -> dict[str, Any]:
        sorted_nums = sorted(nums)
        return {
            "p10": round(self._percentile_value(sorted_nums, 10), 6),
            "p25": round(self._percentile_value(sorted_nums, 25), 6),
            "p50": round(self._percentile_value(sorted_nums, 50), 6),
            "p75": round(self._percentile_value(sorted_nums, 75), 6),
            "p90": round(self._percentile_value(sorted_nums, 90), 6),
            "p95": round(self._percentile_value(sorted_nums, 95), 6),
            "p99": round(self._percentile_value(sorted_nums, 99), 6),
        }

    def _distribution(self, nums: list[float], num_bins: int = 10) -> dict[str, Any]:
        min_val = min(nums)
        max_val = max(nums)
        if min_val == max_val:
            return {"bins": [{"range": f"{min_val}-{max_val}", "count": len(nums)}]}
        bin_width = (max_val - min_val) / num_bins
        bins = []
        for i in range(num_bins):
            low = min_val + i * bin_width
            high = low + bin_width
            if i == num_bins - 1:
                count = sum(1 for x in nums if low <= x <= high)
            else:
                count = sum(1 for x in nums if low <= x < high)
            bins.append(
                {
                    "range": f"{round(low, 2)}-{round(high, 2)}",
                    "count": count,
                }
            )
        return {"bins": bins, "bin_width": round(bin_width, 6)}

    def _correlation(self, nums: list[float], args: dict[str, Any]) -> dict[str, Any]:
        nums_b = args.get("numbers_b")
        if not isinstance(nums_b, list) or not nums_b:
            return {"error": "numbers_b is required for correlation operation"}
        try:
            nums_b_float = [float(n) for n in nums_b]
        except (TypeError, ValueError):
            return {"error": "all items in numbers_b must be numeric"}
        if len(nums) != len(nums_b_float):
            return {"error": "numbers and numbers_b must have the same length"}

        n = len(nums)
        mean_a = sum(nums) / n
        mean_b = sum(nums_b_float) / n
        cov = sum((nums[i] - mean_a) * (nums_b_float[i] - mean_b) for i in range(n)) / n
        std_a = math.sqrt(sum((x - mean_a) ** 2 for x in nums) / n)
        std_b = math.sqrt(sum((x - mean_b) ** 2 for x in nums_b_float) / n)
        if std_a == 0 or std_b == 0:
            return {"correlation": 0.0, "note": "one or both series have zero variance"}
        r = cov / (std_a * std_b)
        return {"correlation": round(r, 6)}

    def _normalize(self, nums: list[float]) -> dict[str, Any]:
        min_val = min(nums)
        max_val = max(nums)
        if min_val == max_val:
            return {"normalized": [0.0] * len(nums)}
        normalized = [round((x - min_val) / (max_val - min_val), 6) for x in nums]
        return {"normalized": normalized}

    def _z_scores(self, nums: list[float]) -> dict[str, Any]:
        n = len(nums)
        mean = sum(nums) / n
        variance = sum((x - mean) ** 2 for x in nums) / n
        stdev = math.sqrt(variance)
        if stdev == 0:
            return {"z_scores": [0.0] * n}
        scores = [round((x - mean) / stdev, 6) for x in nums]
        return {"z_scores": scores}

    @staticmethod
    def _median(sorted_nums: list[float]) -> float:
        n = len(sorted_nums)
        mid = n // 2
        if n % 2 == 0:
            return (sorted_nums[mid - 1] + sorted_nums[mid]) / 2
        return sorted_nums[mid]

    @staticmethod
    def _percentile_value(sorted_nums: list[float], pct: float) -> float:
        n = len(sorted_nums)
        if n == 1:
            return sorted_nums[0]
        k = (pct / 100) * (n - 1)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_nums[int(k)]
        return sorted_nums[f] + (k - f) * (sorted_nums[c] - sorted_nums[f])
