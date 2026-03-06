import re
from typing import Any

from agentic_workflows.tools.base import Tool

_PATTERN_TYPES = [
    "email", "url", "date", "phone", "ip_address", "hex_color",
    "fibonacci_sequence", "arithmetic_sequence", "geometric_sequence",
]

_REGEX_PATTERNS: dict[str, re.Pattern] = {
    "email": re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    "url": re.compile(r"https?://[^\s]+"),
    "date": re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{2}/\d{2}/\d{4}\b"),
    "phone": re.compile(r"\b(?:\+\d{1,3}[\s\-])?\(?\d{3}\)?[\s\-]\d{3}[\s\-]\d{4}\b"),
    "ip_address": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "hex_color": re.compile(r"#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b"),
}

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_EPS = 1e-9


class RecognizePatternTool(Tool):
    name = "recognize_pattern"
    description = (
        "Recognizes patterns in text: email, url, date, phone, ip_address, hex_color, "
        "fibonacci_sequence, arithmetic_sequence, geometric_sequence."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        text: str = args.get("text", "")
        pattern_types = args.get("pattern_types") or list(_PATTERN_TYPES)

        if not isinstance(text, str):
            return {"error": "text must be a string"}
        if not isinstance(pattern_types, list):
            return {"error": "pattern_types must be a list"}

        invalid = [p for p in pattern_types if p not in _PATTERN_TYPES]
        if invalid:
            return {"error": f"unknown pattern types: {invalid}"}

        found: dict[str, list] = {}

        for pt in pattern_types:
            if pt in _REGEX_PATTERNS:
                matches = _REGEX_PATTERNS[pt].findall(text)
                if matches:
                    found[pt] = matches
            else:
                nums = _extract_numbers(text)
                if pt == "fibonacci_sequence":
                    seqs = _find_fibonacci(nums)
                elif pt == "arithmetic_sequence":
                    seqs = _find_arithmetic(nums)
                else:  # geometric_sequence
                    seqs = _find_geometric(nums)
                if seqs:
                    found[pt] = [str(s) for s in seqs]

        return {
            "patterns_found": found,
            "total_matches": sum(len(v) for v in found.values()),
            "checked_types": pattern_types,
        }


def _extract_numbers(text: str) -> list[float]:
    return [float(m) for m in _NUMBER_RE.findall(text)]


def _find_fibonacci(nums: list[float]) -> list[list[float]]:
    if len(nums) < 3:
        return []
    results: list[list[float]] = []
    i = 0
    while i < len(nums) - 2:
        seq = [nums[i], nums[i + 1]]
        j = i + 2
        while j < len(nums) and abs(nums[j] - (seq[-1] + seq[-2])) < _EPS:
            seq.append(nums[j])
            j += 1
        if len(seq) >= 3:
            results.append(seq)
            i = j
        else:
            i += 1
    return results


def _find_arithmetic(nums: list[float]) -> list[list[float]]:
    if len(nums) < 3:
        return []
    results: list[list[float]] = []
    i = 0
    while i < len(nums) - 2:
        diff = nums[i + 1] - nums[i]
        seq = [nums[i], nums[i + 1]]
        j = i + 2
        while j < len(nums) and abs((nums[j] - nums[j - 1]) - diff) < _EPS:
            seq.append(nums[j])
            j += 1
        if len(seq) >= 3:
            results.append(seq)
            i = j
        else:
            i += 1
    return results


def _find_geometric(nums: list[float]) -> list[list[float]]:
    if len(nums) < 3:
        return []
    results: list[list[float]] = []
    i = 0
    while i < len(nums) - 2:
        if abs(nums[i]) < _EPS:
            i += 1
            continue
        ratio = nums[i + 1] / nums[i]
        seq = [nums[i], nums[i + 1]]
        j = i + 2
        while j < len(nums) and abs(nums[j - 1]) > _EPS and abs((nums[j] / nums[j - 1]) - ratio) < _EPS:
            seq.append(nums[j])
            j += 1
        if len(seq) >= 3:
            results.append(seq)
            i = j
        else:
            i += 1
    return results
