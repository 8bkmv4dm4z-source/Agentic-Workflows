"""Unit tests for mission_auditor.py — each check type covered."""
from __future__ import annotations

import unittest

from agentic_workflows.orchestration.langgraph.mission_auditor import (
    AuditFinding,
    AuditReport,
    _approx_equal,
    _check_chain_integrity,
    _check_fibonacci_file_size,
    _check_list_count,
    _check_mean_reuse,
    _check_missing_required_outputs,
    _check_mission_attribution_consistency,
    _check_pattern_report_content,
    _check_tool_presence,
    _check_write_file_success,
    _estimate_fib_csv_min_chars,
    audit_run,
    estimate_fib_csv_min_chars,
)

# ---------------------------------------------------------------------------
# _check_tool_presence
# ---------------------------------------------------------------------------


class TestToolPresence(unittest.TestCase):
    def test_no_warning_when_tool_used(self) -> None:
        findings = _check_tool_presence(1, "Sort the array", ["sort_array"])
        self.assertFalse(any(f.level == "warn" for f in findings))

    def test_warn_when_tool_missing(self) -> None:
        findings = _check_tool_presence(1, "Sort the array", [])
        self.assertTrue(any(f.check == "tool_presence" and f.level == "warn" for f in findings))

    def test_no_finding_for_irrelevant_mission(self) -> None:
        findings = _check_tool_presence(1, "Say hello", ["repeat_message"])
        self.assertEqual(findings, [])

    def test_multiple_keywords_multiple_tools(self) -> None:
        findings = _check_tool_presence(
            1, "analyze and sort the data", ["data_analysis", "text_analysis"]
        )
        # sort_array missing → warn
        self.assertTrue(any("sort_array" in f.detail for f in findings))

    def test_fibonacci_keyword_implies_write_file(self) -> None:
        findings = _check_tool_presence(1, "Write the first 50 fibonacci numbers", [])
        self.assertTrue(any("write_file" in d for d in [f.detail for f in findings]))

    def test_no_false_positive_when_one_group_tool_used(self) -> None:
        """Bug D: 'analysis' keyword → group [text_analysis, data_analysis].
        Using one of them must NOT warn about the other."""
        findings = _check_tool_presence(
            1, "Text Analysis Pipeline", ["text_analysis"]
        )
        warn_findings = [f for f in findings if f.check == "tool_presence"]
        # No warn for the analysis group since text_analysis was used
        self.assertFalse(
            any("text_analysis" in f.detail or "data_analysis" in f.detail for f in warn_findings)
        )

    def test_group_warn_only_when_all_absent(self) -> None:
        """Conservative mode skips ambiguous "analyze/analysis" keyword warnings."""
        # analysis group: noisy keyword is ignored to avoid false positives
        findings_none = _check_tool_presence(1, "Analyze the text", [])
        self.assertFalse(any(f.check == "tool_presence" for f in findings_none))

        # analysis group with one tool also remains warning-free
        findings_partial = _check_tool_presence(1, "Analyze the text", ["data_analysis"])
        self.assertFalse(any(f.check == "tool_presence" for f in findings_partial))

    def test_group_deduplication(self) -> None:
        """Multiple keywords mapping to the same group produce one finding."""
        # "analyze" and "analysis" both map to [text_analysis, data_analysis]
        findings = _check_tool_presence(1, "analyze the analysis data", [])
        group_findings = [f for f in findings if "text_analysis" in f.detail or "data_analysis" in f.detail]
        # Conservative mode skips noisy analysis-group warnings entirely.
        self.assertEqual(len(group_findings), 0)

    def test_scope_filter_suppresses_unavailable_tool_group(self) -> None:
        findings = _check_tool_presence(
            1,
            "Sort the array",
            [],
            allowed_tools={"math_stats"},
        )
        self.assertEqual(findings, [])


# ---------------------------------------------------------------------------
# _check_list_count
# ---------------------------------------------------------------------------


class TestListCount(unittest.TestCase):
    def _record(self, tool: str, result: dict) -> dict:
        return {"tool": tool, "result": result}

    def test_pass_when_count_matches(self) -> None:
        records = [self._record("sort_array", {"sorted": list(range(50)), "original": list(range(50))})]
        finding = _check_list_count(5, "Write the first 50 fibonacci numbers to fib50.txt", records)
        self.assertIsNone(finding)

    def test_fail_when_count_mismatches(self) -> None:
        records = [self._record("sort_array", {"sorted": list(range(11)), "original": list(range(11))})]
        finding = _check_list_count(2, "Sort the first 12 numbers", records)
        self.assertIsNotNone(finding)
        assert finding is not None
        self.assertEqual(finding.level, "fail")
        self.assertEqual(finding.check, "count_match")
        self.assertIn("12", finding.detail)
        self.assertIn("11", finding.detail)

    def test_no_finding_when_no_n_in_text(self) -> None:
        records = [self._record("sort_array", {"sorted": [1, 2, 3], "original": [1, 2, 3]})]
        finding = _check_list_count(1, "Sort some numbers in ascending order", records)
        self.assertIsNone(finding)

    def test_no_finding_when_no_list_result(self) -> None:
        records = [self._record("math_stats", {"mean": 5.0})]
        finding = _check_list_count(1, "Compute stats for 10 numbers", records)
        self.assertIsNone(finding)

    def test_non_outliers_key(self) -> None:
        records = [self._record("data_analysis", {"non_outliers": [1, 2, 3, 4]})]
        finding = _check_list_count(2, "Analyze 5 numbers", records)
        self.assertIsNotNone(finding)
        assert finding is not None
        self.assertIn("5", finding.detail)
        self.assertIn("4", finding.detail)


# ---------------------------------------------------------------------------
# _check_chain_integrity
# ---------------------------------------------------------------------------


class TestChainIntegrity(unittest.TestCase):
    def _make_records(self, da_non_outliers: list, sort_original: list) -> list[dict]:
        """Build tool_results with sort_array result including original field."""
        return [
            {
                "tool": "data_analysis",
                "result": {"non_outliers": da_non_outliers},
            },
            {
                "tool": "sort_array",
                "result": {
                    "sorted": sorted(sort_original),
                    "count": len(sort_original),
                    "order": "desc",
                    "original": sort_original,
                },
            },
        ]

    def test_pass_when_counts_match(self) -> None:
        records = self._make_records(list(range(12)), list(range(12)))
        finding = _check_chain_integrity(2, "Data Analysis and Sorting", records)
        self.assertIsNone(finding)

    def test_fail_when_sort_receives_fewer_items(self) -> None:
        """Exactly the lastRun bug: 12 non_outliers, sort receives 11."""
        records = self._make_records(list(range(12)), list(range(11)))
        finding = _check_chain_integrity(2, "Data Analysis and Sorting", records)
        self.assertIsNotNone(finding)
        assert finding is not None
        self.assertEqual(finding.level, "fail")
        self.assertEqual(finding.check, "chain_integrity")
        self.assertIn("12", finding.detail)
        self.assertIn("11", finding.detail)
        self.assertIn("1 item(s) dropped", finding.detail)

    def test_no_finding_when_only_data_analysis(self) -> None:
        records = [
            {"tool": "data_analysis", "result": {"non_outliers": [1, 2, 3]}}
        ]
        finding = _check_chain_integrity(2, "Analyze data", records)
        self.assertIsNone(finding)

    def test_no_finding_when_only_sort_array(self) -> None:
        records = [
            {
                "tool": "sort_array",
                "result": {"sorted": [1, 2, 3], "count": 3, "order": "asc", "original": [3, 1, 2]},
            }
        ]
        finding = _check_chain_integrity(2, "Sort numbers", records)
        self.assertIsNone(finding)

    def test_uses_original_field_not_args(self) -> None:
        """Verify chain integrity reads result['original'], not args."""
        records = [
            {"tool": "data_analysis", "result": {"non_outliers": [1, 2, 3]}},
            {
                "tool": "sort_array",
                "result": {
                    "sorted": [1, 2],
                    "count": 2,
                    "order": "asc",
                    "original": [1, 2],  # 2 items — mismatch
                },
            },
        ]
        finding = _check_chain_integrity(2, "Sort data", records)
        self.assertIsNotNone(finding)
        assert finding is not None
        self.assertIn("3", finding.detail)
        self.assertIn("2", finding.detail)


# ---------------------------------------------------------------------------
# _check_fibonacci_file_size
# ---------------------------------------------------------------------------

def _fib_content(n: int) -> str:
    """Generate compact CSV of first n fibonacci numbers."""
    a, b = 0, 1
    nums = []
    for _ in range(n):
        nums.append(a)
        a, b = b, a + b
    return ",".join(str(x) for x in nums)


class TestFibonacciFileSize(unittest.TestCase):
    def _make_tool_history(self, path: str, content: str) -> list[dict]:
        return [
            {
                "call": 1,
                "tool": "write_file",
                "args": {"path": path, "content": content},
                "result": {"result": f"Successfully wrote {len(content)} characters to {path}"},
            }
        ]

    def _make_tool_results(self, path: str, char_count: int) -> list[dict]:
        return [
            {
                "tool": "write_file",
                "result": {"result": f"Successfully wrote {char_count} characters to {path}"},
            }
        ]

    def test_fail_when_file_has_fewer_numbers(self) -> None:
        """Reproduce the lastRun bug: fib50.txt contains only 48 numbers."""
        content = _fib_content(48)  # only 48, not 50
        tool_history = self._make_tool_history("fib50.txt", content)
        tool_results = self._make_tool_results("fib50.txt", len(content))
        finding = _check_fibonacci_file_size(
            5, "Write the first 50 fibonacci numbers to fib50.txt",
            tool_results, tool_history,
        )
        self.assertIsNotNone(finding)
        assert finding is not None
        self.assertEqual(finding.level, "fail")
        self.assertEqual(finding.check, "fibonacci_count")
        self.assertIn("48", finding.detail)

    def test_pass_when_file_has_correct_count(self) -> None:
        content = _fib_content(50)
        tool_history = self._make_tool_history("fib50.txt", content)
        tool_results = self._make_tool_results("fib50.txt", len(content))
        finding = _check_fibonacci_file_size(
            5, "Write the first 50 fibonacci numbers to fib50.txt",
            tool_results, tool_history,
        )
        self.assertIsNone(finding)

    def test_uses_latest_fibonacci_write_when_earlier_attempt_failed(self) -> None:
        wrong = _fib_content(48)
        correct = _fib_content(50)
        tool_history = [
            {
                "call": 1,
                "tool": "write_file",
                "args": {"path": "fib50.txt", "content": wrong},
                "result": {"error": "content_validation_failed"},
            },
            {
                "call": 2,
                "tool": "write_file",
                "args": {"path": "fib50.txt", "content": correct},
                "result": {"result": f"Successfully wrote {len(correct)} characters to fib50.txt"},
            },
        ]
        tool_results = [
            {"tool": "write_file", "result": {"error": "content_validation_failed", "path": "fib50.txt"}},
            {"tool": "write_file", "result": {"result": "Successfully wrote 314 characters to fib50.txt", "path": "fib50.txt"}},
        ]
        finding = _check_fibonacci_file_size(
            5,
            "Write the first 50 fibonacci numbers to fib50.txt",
            tool_results,
            tool_history,
        )
        self.assertIsNone(finding)

    def test_no_finding_when_no_fibonacci_in_mission(self) -> None:
        tool_history = self._make_tool_history("out.txt", "hello")
        tool_results = self._make_tool_results("out.txt", 5)
        finding = _check_fibonacci_file_size(
            1, "Write a text file with results", tool_results, tool_history
        )
        self.assertIsNone(finding)

    def test_no_finding_when_no_write_file(self) -> None:
        records = [{"tool": "math_stats", "result": {"mean": 5.0}}]
        finding = _check_fibonacci_file_size(
            5, "Write the first 50 fibonacci numbers to fib50.txt", records, []
        )
        self.assertIsNone(finding)

    def test_fallback_to_char_count_when_no_tool_history(self) -> None:
        """Without tool_history, falls back to char-count estimation (warn level)."""
        # 339 chars < min_chars_with_spaces for 50 numbers (314 + 49 separators = 363)
        tool_results = [
            {
                "tool": "write_file",
                "result": {"result": "Successfully wrote 339 characters to fib50.txt"},
            }
        ]
        finding = _check_fibonacci_file_size(
            5, "Write the first 50 fibonacci numbers to fib50.txt",
            tool_results, [],  # empty tool_history → fallback
        )
        self.assertIsNotNone(finding)
        assert finding is not None
        self.assertEqual(finding.level, "warn")
        self.assertIn("339", finding.detail)


class TestEstimateFibCsvMinChars(unittest.TestCase):
    def test_small_n(self) -> None:
        # first 5 fibs: 0,1,1,2,3 → 5 digits + 4 commas = 9
        result = estimate_fib_csv_min_chars(5)
        self.assertEqual(result, 9)

    def test_fib50_is_314(self) -> None:
        result = estimate_fib_csv_min_chars(50)
        self.assertEqual(result, 314)

    def test_fib1(self) -> None:
        result = estimate_fib_csv_min_chars(1)
        self.assertEqual(result, 1)

    def test_private_alias(self) -> None:
        self.assertEqual(_estimate_fib_csv_min_chars(10), estimate_fib_csv_min_chars(10))


# ---------------------------------------------------------------------------
# _check_mean_reuse
# ---------------------------------------------------------------------------


class TestMeanReuse(unittest.TestCase):
    def _make_tool_history(self, numbers: list) -> list[dict]:
        return [
            {
                "call": 1,
                "tool": "math_stats",
                "args": {"numbers": numbers},
                "result": {"mean": sum(numbers) / len(numbers) if numbers else 0},
            }
        ]

    def test_warn_when_math_stats_uses_subset(self) -> None:
        tool_results = [
            {
                "tool": "data_analysis",
                "result": {"non_outliers": list(range(12))},
            },
        ]
        tool_history = self._make_tool_history(list(range(11)))  # one item short
        finding = _check_mean_reuse(
            2, "Calculate the mean of non-outlier values", tool_results, tool_history
        )
        self.assertIsNotNone(finding)
        assert finding is not None
        self.assertEqual(finding.level, "warn")
        self.assertIn("11", finding.detail)
        self.assertIn("12", finding.detail)

    def test_no_finding_when_counts_match(self) -> None:
        tool_results = [
            {"tool": "data_analysis", "result": {"non_outliers": list(range(11))}},
        ]
        tool_history = self._make_tool_history(list(range(11)))
        finding = _check_mean_reuse(2, "Calculate the mean", tool_results, tool_history)
        self.assertIsNone(finding)

    def test_no_finding_when_no_mean_in_mission(self) -> None:
        tool_results = [
            {"tool": "data_analysis", "result": {"non_outliers": [1, 2, 3]}},
        ]
        tool_history = self._make_tool_history([1, 2])
        finding = _check_mean_reuse(2, "Calculate the sum only", tool_results, tool_history)
        self.assertIsNone(finding)

    def test_no_finding_when_no_data_analysis(self) -> None:
        finding = _check_mean_reuse(
            2, "Calculate the mean", [], self._make_tool_history([1, 2, 3])
        )
        self.assertIsNone(finding)


# ---------------------------------------------------------------------------
# _check_write_file_success
# ---------------------------------------------------------------------------


class TestWriteFileSuccess(unittest.TestCase):
    def test_fail_on_error_result(self) -> None:
        records = [{"tool": "write_file", "result": {"error": "Permission denied"}}]
        findings = _check_write_file_success(1, "Write results.txt", records)
        self.assertTrue(any(f.level == "fail" and f.check == "write_file_success" for f in findings))

    def test_warn_on_zero_chars(self) -> None:
        records = [{"tool": "write_file", "result": {"result": "Successfully wrote 0 characters to out.txt"}}]
        findings = _check_write_file_success(1, "Write output file", records)
        self.assertTrue(any(f.level == "warn" for f in findings))

    def test_no_finding_on_success(self) -> None:
        records = [{"tool": "write_file", "result": {"result": "Successfully wrote 42 characters to out.txt"}}]
        findings = _check_write_file_success(1, "Write output", records)
        self.assertEqual(findings, [])

    def test_no_finding_when_no_write_file(self) -> None:
        records = [{"tool": "sort_array", "result": {"sorted": [1, 2, 3]}}]
        findings = _check_write_file_success(1, "Sort and write", records)
        self.assertEqual(findings, [])


# ---------------------------------------------------------------------------
# audit_run integration
# ---------------------------------------------------------------------------


class TestAuditRun(unittest.TestCase):
    def test_chain_integrity_bug_detected(self) -> None:
        """Reproduce the exact lastRun mission-2 bug: 12 non_outliers, sort gets 11."""
        reports = [
            {
                "mission_id": 2,
                "mission": "Task 2: Data Analysis and Sorting",
                "used_tools": ["data_analysis", "sort_array", "math_stats"],
                "tool_results": [
                    {
                        "tool": "data_analysis",
                        "result": {"non_outliers": list(range(12))},
                    },
                    {
                        "tool": "sort_array",
                        "result": {
                            "sorted": sorted(range(11), reverse=True),
                            "count": 11,
                            "order": "desc",
                            "original": list(range(11)),  # 150 was dropped
                        },
                    },
                ],
                "result": "Done",
            }
        ]
        tool_history = [
            {
                "call": 5,
                "tool": "math_stats",
                "args": {"numbers": list(range(11))},
                "result": {"mean": 5.0},
            }
        ]
        audit = audit_run("run-xyz", ["Task 2: Data Analysis and Sorting"], reports, tool_history)
        chain_fails = [
            f for f in audit.findings if f.check == "chain_integrity" and f.level == "fail"
        ]
        self.assertEqual(len(chain_fails), 1)
        self.assertIn("12", chain_fails[0].detail)
        self.assertIn("11", chain_fails[0].detail)
        self.assertGreater(audit.failed, 0)

    def test_fibonacci_fail_detected(self) -> None:
        """Reproduce the fib50 bug: file has only 48 fibonacci numbers."""
        content = _fib_content(48)
        reports = [
            {
                "mission_id": 5,
                "mission": "Task 5: Write the first 50 fibonacci numbers to fib50.txt",
                "used_tools": ["write_file"],
                "tool_results": [
                    {
                        "tool": "write_file",
                        "result": {"result": f"Successfully wrote {len(content)} characters to fib50.txt"},
                    }
                ],
                "result": "Done",
            }
        ]
        tool_history = [
            {
                "call": 20,
                "tool": "write_file",
                "args": {"path": "fib50.txt", "content": content},
                "result": {"result": f"Successfully wrote {len(content)} characters to fib50.txt"},
            }
        ]
        audit = audit_run(
            "run-fib",
            ["Task 5: Write the first 50 fibonacci numbers to fib50.txt"],
            reports,
            tool_history,
        )
        fib_fails = [f for f in audit.findings if f.check == "fibonacci_count"]
        self.assertEqual(len(fib_fails), 1)
        self.assertEqual(fib_fails[0].level, "fail")
        self.assertGreater(audit.failed, 0)

    def test_missing_required_output_file_fails(self) -> None:
        reports = [
            {
                "mission_id": 3,
                "mission": "Task 3: JSON Processing",
                "used_tools": ["json_parser", "regex_matcher", "sort_array"],
                "required_tools": ["json_parser", "regex_matcher", "sort_array", "write_file"],
                "required_files": ["users_sorted.txt"],
                "written_files": [],
                "tool_results": [],
                "result": "partial",
            }
        ]
        audit = audit_run("run-missing-file", ["Task 3: JSON Processing"], reports, [])
        missing = [f for f in audit.findings if f.check == "missing_output_file"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].level, "fail")

    def test_pattern_report_content_mismatch_fails(self) -> None:
        bad_content = (
            "Extracted Numbers: 123, 5, 45.99, 229.95, 10\n"
            "Sum: 412.94\n"
            "Mean: 82.588"
        )
        reports = [
            {
                "mission_id": 4,
                "mission": "Task 4: Pattern Matching and Transform",
                "used_tools": ["regex_matcher", "math_stats", "write_file"],
                "required_tools": ["regex_matcher", "math_stats", "write_file"],
                "required_files": ["pattern_report.txt"],
                "written_files": ["pattern_report.txt"],
                "tool_results": [],
                "result": "done",
            }
        ]
        tool_history = [
            {
                "call": 15,
                "tool": "write_file",
                "args": {"path": "pattern_report.txt", "content": bad_content},
                "result": {"result": "Successfully wrote 69 characters to pattern_report.txt"},
            }
        ]
        audit = audit_run("run-pattern-bad", ["Task 4: Pattern Matching and Transform"], reports, tool_history)
        mismatches = [f for f in audit.findings if f.check == "output_content_mismatch"]
        self.assertEqual(len(mismatches), 1)
        self.assertEqual(mismatches[0].level, "fail")

    def test_mission_attribution_mismatch_fails(self) -> None:
        reports = [
            {
                "mission_id": 2,
                "mission": "Task 2: Data Analysis and Sorting",
                "used_tools": ["string_ops"],
                "required_tools": ["data_analysis", "sort_array", "math_stats"],
                "required_files": [],
                "written_files": [],
                "tool_results": [],
                "result": "wrong-attribution",
            }
        ]
        audit = audit_run("run-attrib", ["Task 2: Data Analysis and Sorting"], reports, [])
        mismatches = [f for f in audit.findings if f.check == "mission_attribution_mismatch"]
        self.assertEqual(len(mismatches), 1)
        self.assertEqual(mismatches[0].level, "fail")

    def test_audit_report_to_dict(self) -> None:
        report = AuditReport(run_id="test-run")
        report.findings.append(
            AuditFinding(
                mission_id=1,
                mission="Task 1",
                level="fail",
                check="chain_integrity",
                detail="mismatch",
            )
        )
        report.failed = 1
        d = report.to_dict()
        self.assertEqual(d["run_id"], "test-run")
        self.assertEqual(d["failed"], 1)
        self.assertEqual(len(d["findings"]), 1)
        self.assertEqual(d["findings"][0]["level"], "fail")

    def test_empty_run_produces_report(self) -> None:
        audit = audit_run("empty", [], [], [])
        self.assertIsInstance(audit, AuditReport)
        self.assertEqual(audit.findings, [])


# ---------------------------------------------------------------------------
# _approx_equal
# ---------------------------------------------------------------------------


class TestApproxEqual(unittest.TestCase):
    def test_exact_match(self) -> None:
        self.assertTrue(_approx_equal(413.94, 413.94))

    def test_within_tolerance(self) -> None:
        # 413.9400001 vs 413.94 — well within abs_tol=0.01
        self.assertTrue(_approx_equal(413.9400001, 413.94))

    def test_outside_tolerance(self) -> None:
        self.assertFalse(_approx_equal(413.94, 412.94))

    def test_zero_values(self) -> None:
        self.assertTrue(_approx_equal(0.0, 0.0))
        self.assertTrue(_approx_equal(0.0, 0.005))  # within abs_tol
        self.assertFalse(_approx_equal(0.0, 0.02))  # outside abs_tol


# ---------------------------------------------------------------------------
# _check_missing_required_outputs (direct unit tests)
# ---------------------------------------------------------------------------


class TestMissingRequiredOutputs(unittest.TestCase):
    def test_missing_tool(self) -> None:
        findings = _check_missing_required_outputs(
            mission_id=1,
            mission_text="Task 1",
            mission_report={
                "used_tools": ["sort_array"],
                "required_tools": ["sort_array", "write_file"],
                "required_files": [],
            },
            tool_results=[],
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].check, "required_tools_missing")
        self.assertIn("write_file", findings[0].detail)

    def test_missing_file(self) -> None:
        findings = _check_missing_required_outputs(
            mission_id=2,
            mission_text="Task 2",
            mission_report={
                "used_tools": ["write_file"],
                "required_tools": [],
                "required_files": ["output.txt"],
                "written_files": [],
            },
            tool_results=[],
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].check, "missing_output_file")
        self.assertIn("output.txt", findings[0].detail)

    def test_both_missing(self) -> None:
        findings = _check_missing_required_outputs(
            mission_id=3,
            mission_text="Task 3",
            mission_report={
                "used_tools": [],
                "required_tools": ["data_analysis"],
                "required_files": ["report.txt"],
                "written_files": [],
            },
            tool_results=[],
        )
        self.assertEqual(len(findings), 2)
        checks = {f.check for f in findings}
        self.assertIn("required_tools_missing", checks)
        self.assertIn("missing_output_file", checks)

    def test_none_missing(self) -> None:
        findings = _check_missing_required_outputs(
            mission_id=4,
            mission_text="Task 4",
            mission_report={
                "used_tools": ["write_file"],
                "required_tools": ["write_file"],
                "required_files": ["out.txt"],
                "written_files": ["out.txt"],
            },
            tool_results=[],
        )
        self.assertEqual(findings, [])


# ---------------------------------------------------------------------------
# _check_pattern_report_content (direct unit tests)
# ---------------------------------------------------------------------------


class TestPatternReportContent(unittest.TestCase):
    def _make_history(self, content: str) -> list[dict]:
        return [
            {
                "call": 1,
                "tool": "write_file",
                "args": {"path": "pattern_report.txt", "content": content},
                "result": {"result": f"Successfully wrote {len(content)} characters"},
            }
        ]

    def test_matching_values_pass(self) -> None:
        content = "Extracted Numbers: 10, 20, 30\nSum: 60\nMean: 20.0"
        finding = _check_pattern_report_content(
            mission_id=4, mission_text="Pattern matching task", tool_history=self._make_history(content)
        )
        self.assertIsNone(finding)

    def test_sum_mismatch_fail(self) -> None:
        content = "Extracted Numbers: 10, 20, 30\nSum: 100\nMean: 20.0"
        finding = _check_pattern_report_content(
            mission_id=4, mission_text="Pattern matching task", tool_history=self._make_history(content)
        )
        self.assertIsNotNone(finding)
        assert finding is not None
        self.assertEqual(finding.level, "fail")
        self.assertIn("sum mismatch", finding.detail)

    def test_mean_near_epsilon_pass(self) -> None:
        # 413.94 / 5 = 82.788 — reported as 82.7880001 (within tolerance)
        content = "Extracted Numbers: 123, 5, 45.99, 229.95, 10\nSum: 413.94\nMean: 82.7880001"
        finding = _check_pattern_report_content(
            mission_id=4, mission_text="Pattern matching task", tool_history=self._make_history(content)
        )
        self.assertIsNone(finding)

    def test_missing_fields_fail(self) -> None:
        content = "Extracted Numbers: 10, 20\nTotal: 30"
        finding = _check_pattern_report_content(
            mission_id=4, mission_text="Pattern matching task", tool_history=self._make_history(content)
        )
        self.assertIsNotNone(finding)
        assert finding is not None
        self.assertEqual(finding.level, "fail")
        self.assertIn("missing required lines", finding.detail)

    def test_non_numeric_token_fail(self) -> None:
        content = "Extracted Numbers: 10, abc, 30\nSum: 40\nMean: 20.0"
        finding = _check_pattern_report_content(
            mission_id=4, mission_text="Pattern matching task", tool_history=self._make_history(content)
        )
        self.assertIsNotNone(finding)
        assert finding is not None
        self.assertIn("non-numeric", finding.detail)


# ---------------------------------------------------------------------------
# _check_mission_attribution_consistency (direct unit tests)
# ---------------------------------------------------------------------------


class TestMissionAttributionConsistency(unittest.TestCase):
    def test_no_required_tools_skip(self) -> None:
        finding = _check_mission_attribution_consistency(
            mission_id=1,
            mission_text="Task 1",
            mission_report={"used_tools": ["sort_array"], "required_tools": []},
        )
        self.assertIsNone(finding)

    def test_all_present_pass(self) -> None:
        finding = _check_mission_attribution_consistency(
            mission_id=2,
            mission_text="Task 2",
            mission_report={
                "used_tools": ["data_analysis", "sort_array", "math_stats"],
                "required_tools": ["data_analysis", "sort_array"],
            },
        )
        self.assertIsNone(finding)

    def test_some_missing_fail(self) -> None:
        finding = _check_mission_attribution_consistency(
            mission_id=3,
            mission_text="Task 3",
            mission_report={
                "used_tools": ["string_ops"],
                "required_tools": ["data_analysis", "sort_array"],
            },
        )
        self.assertIsNotNone(finding)
        assert finding is not None
        self.assertEqual(finding.level, "fail")
        self.assertEqual(finding.check, "mission_attribution_mismatch")
        self.assertIn("data_analysis", finding.detail)


# ---------------------------------------------------------------------------
# _check_tool_presence — context-aware keyword tests
# ---------------------------------------------------------------------------


class TestToolPresenceContextAware(unittest.TestCase):
    def test_explicit_data_analysis_warns_when_missing(self) -> None:
        """Mission mentions 'analyze' keyword + explicit 'data_analysis' tool — warns when absent."""
        findings = _check_tool_presence(1, "Analyze the numbers using data_analysis", [])
        tool_findings = [f for f in findings if f.check == "tool_presence"]
        self.assertTrue(
            any("data_analysis" in f.detail for f in tool_findings),
            f"Expected data_analysis warning, got: {tool_findings}",
        )

    def test_ambiguous_analyze_no_explicit_tool_stays_silent(self) -> None:
        """Mission says 'Analyze' without explicit tool name — stays silent."""
        findings = _check_tool_presence(1, "Analyze the text", [])
        analysis_findings = [
            f for f in findings
            if f.check == "tool_presence" and ("data_analysis" in f.detail or "text_analysis" in f.detail)
        ]
        self.assertEqual(len(analysis_findings), 0)

    def test_explicit_text_analysis_warns_when_missing(self) -> None:
        """Mission mentions 'analysis' keyword + explicit 'text_analysis' tool — warns when absent."""
        findings = _check_tool_presence(1, "Text analysis using text_analysis tool", [])
        tool_findings = [f for f in findings if f.check == "tool_presence"]
        self.assertTrue(any("text_analysis" in f.detail for f in tool_findings))


if __name__ == "__main__":
    unittest.main()
