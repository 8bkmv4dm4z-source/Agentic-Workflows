from __future__ import annotations

"""Write-file content validation extracted from graph.py.

Deterministic checks that verify tool output matches mission contracts
(e.g. fibonacci sequence correctness, pattern report numeric consistency).
"""

import re
from typing import Any

from agentic_workflows.orchestration.langgraph.text_extractor import (
    extract_fibonacci_count,
    parse_csv_int_list,
)


def validate_tool_result_for_active_mission(
    *,
    state: dict[str, Any],
    tool_name: str,
    tool_args: dict[str, Any],
    tool_result: dict[str, Any],
    mission_index: int | None = None,
) -> str | None:
    """Apply deterministic content validation for mission-specific write constraints."""
    if tool_name != "write_file":
        return None
    if "error" in tool_result:
        return None

    reports = state.get("mission_reports", [])
    index = mission_index if mission_index is not None else int(state.get("active_mission_index", -1))
    mission_report = reports[index] if 0 <= index < len(reports) else {}
    mission_text = str(mission_report.get("mission", "")).lower()
    contract_checks = {
        str(check).strip().lower() for check in mission_report.get("contract_checks", [])
    }

    # Fibonacci-specific strict validation.
    fib_count = mission_report.get("expected_fibonacci_count")
    fib_contract_expected = isinstance(fib_count, int) and fib_count > 0
    is_fibonacci_mission = fib_contract_expected or ("fibonacci" in mission_text)
    if is_fibonacci_mission:
        expected_count = mission_report.get("expected_fibonacci_count")
        if not isinstance(expected_count, int) or expected_count <= 0:
            expected_count = extract_fibonacci_count(mission_text)

        content = str(tool_args.get("content", ""))
        numbers = parse_csv_int_list(content)
        if numbers is None:
            return "write_file content must be a comma-separated list of integers."
        if len(numbers) != expected_count:
            return (
                f"fibonacci content must contain exactly {expected_count} integers, "
                f"got {len(numbers)}."
            )
        if len(numbers) < 2 or numbers[0] != 0 or numbers[1] != 1:
            return "fibonacci content must start with 0, 1."

        for seq_index in range(2, len(numbers)):
            expected = numbers[seq_index - 1] + numbers[seq_index - 2]
            if numbers[seq_index] != expected:
                return (
                    "fibonacci sequence mismatch at index "
                    f"{seq_index}: got {numbers[seq_index]}, expected {expected}."
                )

    # Pattern report numeric consistency validation.
    should_validate_pattern_report = "pattern_report_consistency" in contract_checks
    # Legacy fallback when contract metadata is unavailable.
    if not contract_checks and "pattern" in mission_text:
        should_validate_pattern_report = (
            "sum" in mission_text or "mean" in mission_text
        )
    if should_validate_pattern_report:
        content = str(tool_args.get("content", ""))
        pattern_error = validate_pattern_report_content(content)
        if pattern_error:
            return pattern_error

    return None


def validate_pattern_report_content(content: str) -> str | None:
    """Ensure pattern report contains numerically consistent sum/mean."""
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if len(lines) < 3:
        return "pattern report must include extracted numbers, sum, and mean lines."

    numbers_line = next((line for line in lines if line.lower().startswith("extracted numbers:")), "")
    sum_line = next((line for line in lines if line.lower().startswith("sum:")), "")
    mean_line = next((line for line in lines if line.lower().startswith("mean:")), "")
    if not numbers_line or not sum_line or not mean_line:
        return "pattern report must contain 'Extracted Numbers', 'Sum', and 'Mean' fields."

    raw_numbers = numbers_line.split(":", 1)[1] if ":" in numbers_line else ""
    number_tokens = [token.strip() for token in raw_numbers.split(",") if token.strip()]
    if not number_tokens:
        return "pattern report numbers list is empty."
    values: list[float] = []
    for token in number_tokens:
        try:
            values.append(float(token))
        except ValueError:
            return f"pattern report contains a non-numeric token: {token!r}."

    sum_match = re.search(r"-?\d+(?:\.\d+)?", sum_line)
    mean_match = re.search(r"-?\d+(?:\.\d+)?", mean_line)
    if not sum_match or not mean_match:
        return "pattern report sum/mean must contain numeric values."
    reported_sum = float(sum_match.group(0))
    reported_mean = float(mean_match.group(0))

    expected_sum = sum(values)
    expected_mean = expected_sum / len(values)
    if round(reported_sum, 2) != round(expected_sum, 2):
        return (
            f"pattern report sum mismatch: got {reported_sum}, "
            f"expected {round(expected_sum, 2)} "
            f"(sum of extracted numbers {values}). "
            "Use the math_stats tool with operation='sum' and numbers=[...] to compute "
            "the correct value before writing — do not compute sum manually."
        )
    if round(reported_mean, 3) != round(expected_mean, 3):
        return (
            f"pattern report mean mismatch: got {reported_mean}, "
            f"expected {round(expected_mean, 3)} "
            f"(mean of {len(values)} numbers). "
            "Use the math_stats tool with operation='mean' and numbers=[...] to compute "
            "the correct value before writing — do not compute mean manually."
        )
    return None
