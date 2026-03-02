from __future__ import annotations

"""Post-run mission auditor for Phase 1 orchestration.

Deterministic, keyword-driven checks that inspect mission tool history
after a run completes.  No LLM calls.  No per-mission test functions.
Results flag data-loss, chain-integrity, and count-mismatch bugs that
the planner silently introduced during execution.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from agentic_workflows.orchestration.langgraph.mission_parser import _TOOL_KEYWORD_MAP


def _approx_equal(a: float, b: float, *, rel_tol: float = 1e-4, abs_tol: float = 0.01) -> bool:
    """Tolerance-based comparison for heuristic tool outputs."""
    return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class AuditFinding:
    mission_id: int
    mission: str
    level: Literal["pass", "warn", "fail"]
    check: str    # e.g. "count_match", "chain_integrity", "file_size"
    detail: str   # human-readable explanation


@dataclass
class AuditReport:
    run_id: str
    findings: list[AuditFinding] = field(default_factory=list)
    passed: int = 0
    warned: int = 0
    failed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "passed": self.passed,
            "warned": self.warned,
            "failed": self.failed,
            "findings": [
                {
                    "mission_id": f.mission_id,
                    "mission": f.mission,
                    "level": f.level,
                    "check": f.check,
                    "detail": f.detail,
                }
                for f in self.findings
            ],
        }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def audit_run(
    run_id: str,
    missions: list[str],
    mission_reports: list[dict[str, Any]],
    tool_history: list[dict[str, Any]],
) -> AuditReport:
    """Audit a completed run.  Returns an AuditReport with one finding per check."""
    report = AuditReport(run_id=run_id)

    for i, mission_report in enumerate(mission_reports):
        mission_id = mission_report.get("mission_id", i + 1)
        mission_text = mission_report.get("mission", missions[i] if i < len(missions) else "")
        used_tools: list[str] = mission_report.get("used_tools", [])
        tool_results: list[dict[str, Any]] = mission_report.get("tool_results", [])

        findings: list[AuditFinding] = []

        # 1. Tool presence check
        findings.extend(
            _check_tool_presence(mission_id, mission_text, used_tools)
        )

        # 2. List count check
        finding = _check_list_count(mission_id, mission_text, tool_results)
        if finding:
            findings.append(finding)

        # 3. Chain integrity check (data_analysis → sort_array)
        finding = _check_chain_integrity(mission_id, mission_text, tool_results)
        if finding:
            findings.append(finding)

        # 4. Fibonacci file size check — uses tool_history for write content
        finding = _check_fibonacci_file_size(
            mission_id, mission_text, tool_results, tool_history
        )
        if finding:
            findings.append(finding)

        # 5. Mean/sum reuse check — uses tool_history for math_stats args
        finding = _check_mean_reuse(
            mission_id, mission_text, tool_results, tool_history
        )
        if finding:
            findings.append(finding)

        # 6. Write file existence check
        findings.extend(
            _check_write_file_success(mission_id, mission_text, tool_results)
        )
        findings.extend(
            _check_missing_required_outputs(
                mission_id=mission_id,
                mission_text=mission_text,
                mission_report=mission_report,
                tool_results=tool_results,
            )
        )

        # 7. Pattern report arithmetic check
        finding = _check_pattern_report_content(
            mission_id=mission_id,
            mission_text=mission_text,
            tool_history=tool_history,
        )
        if finding:
            findings.append(finding)

        # 8. Mission attribution consistency check
        finding = _check_mission_attribution_consistency(
            mission_id=mission_id,
            mission_text=mission_text,
            mission_report=mission_report,
        )
        if finding:
            findings.append(finding)

        # If no failures/warnings were found, add a single pass finding
        if not any(f.level in ("warn", "fail") for f in findings):
            findings.insert(
                0,
                AuditFinding(
                    mission_id=mission_id,
                    mission=mission_text,
                    level="pass",
                    check="overall",
                    detail="All checks passed.",
                ),
            )

        report.findings.extend(findings)

    # Tally
    for f in report.findings:
        if f.level == "pass":
            report.passed += 1
        elif f.level == "warn":
            report.warned += 1
        else:
            report.failed += 1

    return report


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_tool_presence(
    mission_id: int,
    mission_text: str,
    used_tools: list[str],
) -> list[AuditFinding]:
    """Warn if no tool from a keyword-implied group was called for this mission.

    Each keyword maps to a group of tools (alternatives).  A warning is only
    emitted when the mission used NONE of the tools in the group, not when it
    used one of them but not another.  Groups are deduplicated so the same set
    of tools only produces one finding regardless of how many keywords match.
    """
    lower = mission_text.lower()
    # Genuinely ambiguous keywords — always skip.
    always_noisy = {"order", "stats"}
    # Context-aware keywords: only skip when no explicit tool name appears.
    context_keywords = {"analysis", "analyze"}

    def _keyword_present(keyword: str, text: str) -> bool:
        return re.search(rf"\b{re.escape(keyword)}\b", text) is not None

    def _has_explicit_tool_name(text: str, tool_group: list[str]) -> bool:
        """Return True if the mission text mentions a tool by its exact name."""
        return any(tool in text for tool in tool_group)

    # Collect groups as frozensets to avoid duplicate findings for the same group
    checked_groups: set[frozenset[str]] = set()
    findings: list[AuditFinding] = []

    for keyword, tool_group in _TOOL_KEYWORD_MAP.items():
        if keyword in always_noisy:
            continue
        if keyword in context_keywords and not _has_explicit_tool_name(lower, tool_group):
            continue
        if not _keyword_present(keyword, lower):
            continue
        group_key = frozenset(tool_group)
        if group_key in checked_groups:
            continue
        checked_groups.add(group_key)
        if not any(t in used_tools for t in tool_group):
            findings.append(
                AuditFinding(
                    mission_id=mission_id,
                    mission=mission_text,
                    level="warn",
                    check="tool_presence",
                    detail=(
                        f"Mission implies one of {sorted(tool_group)} but none were used."
                    ),
                )
            )
    return findings


def _check_list_count(
    mission_id: int,
    mission_text: str,
    tool_results: list[dict[str, Any]],
) -> AuditFinding | None:
    """Fail if the mission requests N items but the first list result has != N items."""
    patterns = [
        r"first\s+(\d+)\s+(?:fibonacci|numbers?|items?|terms?)",
        r"(\d+)\s+(?:fibonacci|numbers?|items?)",
    ]
    n: int | None = None
    for pat in patterns:
        m = re.search(pat, mission_text, re.IGNORECASE)
        if m:
            n = int(m.group(1))
            break
    if n is None:
        return None

    # Look for the first result containing a list-type field
    list_keys = ("sorted", "non_outliers", "matches", "numbers", "items", "result")
    for record in tool_results:
        result = record.get("result", {})
        if not isinstance(result, dict):
            continue
        for key in list_keys:
            val = result.get(key)
            if isinstance(val, list):
                actual = len(val)
                if actual != n:
                    return AuditFinding(
                        mission_id=mission_id,
                        mission=mission_text,
                        level="fail",
                        check="count_match",
                        detail=(
                            f"Expected {n} items in '{key}' but got {actual}."
                        ),
                    )
                return None  # found the list and count matches
    return None


def _check_chain_integrity(
    mission_id: int,
    mission_text: str,
    tool_results: list[dict[str, Any]],
) -> AuditFinding | None:
    """Fail when data_analysis non_outliers count != sort_array original count.

    sort_array includes its input as result["original"], so no args access needed.
    """
    da_result: dict[str, Any] | None = None
    sort_result: dict[str, Any] | None = None

    for record in tool_results:
        tool = record.get("tool", "")
        if tool == "data_analysis":
            da_result = record.get("result", {})
        elif tool == "sort_array":
            sort_result = record.get("result", {})

    if da_result is None or sort_result is None:
        return None

    non_outliers = da_result.get("non_outliers")
    if not isinstance(non_outliers, list):
        return None

    # sort_array result always includes "original" — the input the planner passed
    sort_input = sort_result.get("original")
    if not isinstance(sort_input, list):
        return None

    expected = len(non_outliers)
    actual = len(sort_input)
    if expected != actual:
        return AuditFinding(
            mission_id=mission_id,
            mission=mission_text,
            level="fail",
            check="chain_integrity",
            detail=(
                f"data_analysis returned {expected} non_outliers "
                f"but sort_array received {actual} items "
                f"({expected - actual} item(s) dropped by planner)."
            ),
        )
    return None


def estimate_fib_csv_min_chars(n: int) -> int:
    """Estimate minimum character count for first N fibonacci numbers as compact CSV."""
    a, b = 0, 1
    total = 0
    for i in range(n):
        total += len(str(a))
        if i < n - 1:
            total += 1  # comma (no space — compact format)
        a, b = b, a + b
    return total


# Keep a private alias for backward compatibility in tests
_estimate_fib_csv_min_chars = estimate_fib_csv_min_chars


def _count_csv_integers(content: str) -> int:
    """Count how many comma-separated integer tokens are in a content string."""
    tokens = [t.strip() for t in content.split(",") if t.strip()]
    count = 0
    for t in tokens:
        try:
            int(t)
            count += 1
        except ValueError:
            pass
    return count


def _check_fibonacci_file_size(
    mission_id: int,
    mission_text: str,
    tool_results: list[dict[str, Any]],
    tool_history: list[dict[str, Any]],
) -> AuditFinding | None:
    """Warn if a fibonacci write_file result has fewer numbers than expected.

    Uses tool_history for write_file args (content) when available; falls back
    to char-count estimation from the result message.
    """
    lower = mission_text.lower()
    if "fibonacci" not in lower:
        return None

    # Extract N from mission text
    m = re.search(r"first\s+(\d+)|(\d+)\s+fibonacci", mission_text, re.IGNORECASE)
    if not m:
        return None
    n = int(m.group(1) or m.group(2))

    # Find the write_file call for a fibonacci path in tool_history (has args+content)
    fib_paths = {
        str(record.get("result", {}).get("path", ""))
        for record in tool_results
        if record.get("tool") == "write_file"
    }
    # Resolve write_file content from tool_history
    for hist_record in tool_history:
        if hist_record.get("tool") != "write_file":
            continue
        path = str(hist_record.get("args", {}).get("path", ""))
        content = str(hist_record.get("args", {}).get("content", ""))
        if not content:
            continue
        # Match if mission references "fib" or if path is in our tool_results paths
        path_lower = path.lower()
        if "fib" not in path_lower and path not in fib_paths:
            continue
        actual_count = _count_csv_integers(content)
        if actual_count < n:
            return AuditFinding(
                mission_id=mission_id,
                mission=mission_text,
                level="fail",
                check="fibonacci_count",
                detail=(
                    f"fibonacci file has {actual_count} integers, "
                    f"expected {n} (file content appears to contain only "
                    f"~{actual_count} numbers)."
                ),
            )
        return None

    # Fallback: use char count from result message with space-aware estimate
    for record in tool_results:
        if record.get("tool") != "write_file":
            continue
        result = record.get("result", {})
        if not isinstance(result, dict):
            continue
        msg = str(result.get("message", result.get("result", "")))
        char_match = re.search(r"(\d+)\s+char", msg)
        if not char_match:
            continue
        actual_chars = int(char_match.group(1))
        # Use space-aware estimate: each separator is ", " (2 chars) not "," (1 char)
        min_chars_with_spaces = estimate_fib_csv_min_chars(n) + (n - 1)
        if actual_chars < min_chars_with_spaces:
            return AuditFinding(
                mission_id=mission_id,
                mission=mission_text,
                level="warn",
                check="fibonacci_count",
                detail=(
                    f"fibonacci file has {actual_chars} chars, "
                    f"expected ≥ {min_chars_with_spaces} for {n} numbers "
                    f"(file may contain fewer than {n} numbers)."
                ),
            )
        return None
    return None


def _estimate_fib_n_from_chars(char_count: int) -> int:
    """Reverse-estimate how many fibonacci numbers fit in char_count chars."""
    a, b = 0, 1
    total = 0
    i = 0
    while True:
        total += len(str(a))
        if i > 0:
            total += 1  # comma
        if total > char_count:
            return max(0, i)
        i += 1
        a, b = b, a + b
        if i > 10000:
            break
    return i


def _check_mean_reuse(
    mission_id: int,
    mission_text: str,
    tool_results: list[dict[str, Any]],
    tool_history: list[dict[str, Any]],
) -> AuditFinding | None:
    """Warn when math_stats computes mean on a smaller dataset than data_analysis returned."""
    lower = mission_text.lower()
    if "mean" not in lower:
        return None

    # Find data_analysis non_outliers count from tool_results
    da_count: int | None = None
    for record in tool_results:
        if record.get("tool") == "data_analysis":
            result = record.get("result", {})
            non_outliers = result.get("non_outliers")
            if isinstance(non_outliers, list):
                da_count = len(non_outliers)
                break

    if da_count is None:
        return None

    # Find math_stats mean call in tool_history (which has args)
    for hist_record in tool_history:
        if hist_record.get("tool") != "math_stats":
            continue
        args = hist_record.get("args", {})
        stat_input: list[Any] | None = None
        for key in ("numbers", "values", "items", "data"):
            candidate = args.get(key)
            if isinstance(candidate, list):
                stat_input = candidate
                break
        if stat_input is None:
            continue
        if len(stat_input) < da_count:
            return AuditFinding(
                mission_id=mission_id,
                mission=mission_text,
                level="warn",
                check="mean_reuse",
                detail=(
                    f"math_stats mean computed on {len(stat_input)} items "
                    f"but data_analysis returned {da_count} non_outliers "
                    f"(mean was computed on a subset of the data)."
                ),
            )
    return None


def _check_write_file_success(
    mission_id: int,
    mission_text: str,
    tool_results: list[dict[str, Any]],
) -> list[AuditFinding]:
    """Warn for each write_file result that has an error or zero character count."""
    findings: list[AuditFinding] = []
    for record in tool_results:
        if record.get("tool") != "write_file":
            continue
        result = record.get("result", {})
        if not isinstance(result, dict):
            continue
        if "error" in result:
            findings.append(
                AuditFinding(
                    mission_id=mission_id,
                    mission=mission_text,
                    level="fail",
                    check="write_file_success",
                    detail=f"write_file returned error: {result['error']}",
                )
            )
            continue
        msg = str(result.get("message", result.get("result", "")))
        char_match = re.search(r"(\d+)\s+char", msg)
        if char_match and int(char_match.group(1)) == 0:
            findings.append(
                AuditFinding(
                    mission_id=mission_id,
                    mission=mission_text,
                    level="warn",
                    check="write_file_success",
                    detail="write_file wrote 0 characters.",
                )
            )
    return findings


def _check_missing_required_outputs(
    *,
    mission_id: int,
    mission_text: str,
    mission_report: dict[str, Any],
    tool_results: list[dict[str, Any]],
) -> list[AuditFinding]:
    """Fail when mission contract expects files/tools that are missing."""
    findings: list[AuditFinding] = []
    required_files = {
        str(path).replace("\\", "/").rsplit("/", 1)[-1]
        for path in mission_report.get("required_files", [])
    }
    required_tools = {str(tool) for tool in mission_report.get("required_tools", [])}
    used_tools = {str(tool) for tool in mission_report.get("used_tools", [])}

    if required_tools:
        missing_tools = sorted(required_tools - used_tools)
        if missing_tools:
            findings.append(
                AuditFinding(
                    mission_id=mission_id,
                    mission=mission_text,
                    level="fail",
                    check="required_tools_missing",
                    detail=f"Mission missing required tools: {missing_tools}",
                )
            )

    if required_files:
        written_files: set[str] = set()
        for record in tool_results:
            if record.get("tool") != "write_file":
                continue
            result = record.get("result", {})
            if isinstance(result, dict):
                maybe_path = str(result.get("path", "")).strip()
                if maybe_path:
                    written_files.add(maybe_path.replace("\\", "/").rsplit("/", 1)[-1])
        # Fall back to pre-tracked written_files from mission report.
        for path in mission_report.get("written_files", []):
            written_files.add(str(path).replace("\\", "/").rsplit("/", 1)[-1])
        missing_files = sorted(required_files - written_files)
        if missing_files:
            findings.append(
                AuditFinding(
                    mission_id=mission_id,
                    mission=mission_text,
                    level="fail",
                    check="missing_output_file",
                    detail=f"Mission missing required output file(s): {missing_files}",
                )
            )
    return findings


def _check_pattern_report_content(
    *,
    mission_id: int,
    mission_text: str,
    tool_history: list[dict[str, Any]],
) -> AuditFinding | None:
    """Fail when a pattern_report write has inconsistent sum/mean values."""
    lower = mission_text.lower()
    if "pattern" not in lower and "regex" not in lower:
        return None

    for hist_record in tool_history:
        if hist_record.get("tool") != "write_file":
            continue
        args = hist_record.get("args", {})
        path = str(args.get("path", ""))
        if "pattern_report" not in path.lower():
            continue
        content = str(args.get("content", ""))
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if len(lines) < 3:
            return AuditFinding(
                mission_id=mission_id,
                mission=mission_text,
                level="fail",
                check="output_content_mismatch",
                detail="pattern_report.txt missing required lines.",
            )
        numbers_line = next(
            (line for line in lines if line.lower().startswith("extracted numbers:")), ""
        )
        sum_line = next((line for line in lines if line.lower().startswith("sum:")), "")
        mean_line = next((line for line in lines if line.lower().startswith("mean:")), "")
        if not numbers_line or not sum_line or not mean_line:
            return AuditFinding(
                mission_id=mission_id,
                mission=mission_text,
                level="fail",
                check="output_content_mismatch",
                detail="pattern_report.txt must contain numbers/sum/mean fields.",
            )
        tokens = [token.strip() for token in numbers_line.split(":", 1)[1].split(",") if token.strip()]
        values: list[float] = []
        for token in tokens:
            try:
                values.append(float(token))
            except ValueError:
                return AuditFinding(
                    mission_id=mission_id,
                    mission=mission_text,
                    level="fail",
                    check="output_content_mismatch",
                    detail=f"pattern_report.txt contains non-numeric token {token!r}.",
                )
        if not values:
            return AuditFinding(
                mission_id=mission_id,
                mission=mission_text,
                level="fail",
                check="output_content_mismatch",
                detail="pattern_report.txt has no extracted numbers.",
            )
        sum_match = re.search(r"-?\d+(?:\.\d+)?", sum_line)
        mean_match = re.search(r"-?\d+(?:\.\d+)?", mean_line)
        if not sum_match or not mean_match:
            return AuditFinding(
                mission_id=mission_id,
                mission=mission_text,
                level="fail",
                check="output_content_mismatch",
                detail="pattern_report.txt sum/mean fields are not numeric.",
            )
        reported_sum = float(sum_match.group(0))
        reported_mean = float(mean_match.group(0))
        expected_sum = sum(values)
        expected_mean = expected_sum / len(values)
        if not _approx_equal(reported_sum, expected_sum):
            return AuditFinding(
                mission_id=mission_id,
                mission=mission_text,
                level="fail",
                check="output_content_mismatch",
                detail=(
                    f"pattern_report sum mismatch: got {reported_sum}, "
                    f"expected {round(expected_sum, 2)}."
                ),
            )
        if not _approx_equal(reported_mean, expected_mean):
            return AuditFinding(
                mission_id=mission_id,
                mission=mission_text,
                level="fail",
                check="output_content_mismatch",
                detail=(
                    f"pattern_report mean mismatch: got {reported_mean}, "
                    f"expected {round(expected_mean, 3)}."
                ),
            )
    return None


def _check_mission_attribution_consistency(
    *,
    mission_id: int,
    mission_text: str,
    mission_report: dict[str, Any],
) -> AuditFinding | None:
    """Fail when mission report tool attribution misses its own contract."""
    required_tools = {str(tool) for tool in mission_report.get("required_tools", [])}
    if not required_tools:
        return None
    used_tools = {str(tool) for tool in mission_report.get("used_tools", [])}
    missing_tools = sorted(required_tools - used_tools)
    if missing_tools:
        return AuditFinding(
            mission_id=mission_id,
            mission=mission_text,
            level="fail",
            check="mission_attribution_mismatch",
            detail=f"Mission report attribution missing contract tools: {missing_tools}",
        )
    return None
