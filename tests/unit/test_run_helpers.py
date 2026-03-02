"""Unit tests for run.py helper functions."""
from __future__ import annotations

import unittest

from agentic_workflows.orchestration.langgraph.run import (
    _build_rerun_input,
    _get_failed_missions,
)

_SAMPLE_INPUT = """Return exactly one JSON object per turn.

Please complete these tasks:

Task 1: Text Analysis Pipeline
  1a. Analyze this text: "The quick brown fox"
  1b. Write results to analysis_results.txt

Task 2: Data Analysis and Sorting
  2a. Analyze these numbers: [45, 23, 67]
  2b. Sort in descending order

Task 3: JSON Processing
  3a. Parse this JSON: '{"users":[]}'
"""


class TestGetFailedMissions(unittest.TestCase):
    def _make_report(self, level: str, mission_id: int = 1) -> dict:
        return {
            "run_id": "test",
            "findings": [{"mission_id": mission_id, "level": level, "check": "test", "detail": "x"}],
        }

    def test_returns_fail_missions(self) -> None:
        audit = self._make_report("fail", 1)
        reports = [{"mission_id": 1, "mission": "Task 1"}]
        result = _get_failed_missions(audit, reports)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["mission_id"], 1)

    def test_skips_warn_missions(self) -> None:
        """Bug A: warn-level findings must NOT trigger re-run."""
        audit = self._make_report("warn", 1)
        reports = [{"mission_id": 1, "mission": "Task 1"}]
        result = _get_failed_missions(audit, reports)
        self.assertEqual(result, [])

    def test_skips_pass_missions(self) -> None:
        audit = self._make_report("pass", 1)
        reports = [{"mission_id": 1, "mission": "Task 1"}]
        result = _get_failed_missions(audit, reports)
        self.assertEqual(result, [])

    def test_empty_audit(self) -> None:
        result = _get_failed_missions(None, [{"mission_id": 1}])
        self.assertEqual(result, [])

    def test_multiple_missions_only_failed_returned(self) -> None:
        audit = {
            "run_id": "x",
            "findings": [
                {"mission_id": 1, "level": "pass", "check": "overall", "detail": "ok"},
                {"mission_id": 2, "level": "fail", "check": "chain", "detail": "bad"},
                {"mission_id": 3, "level": "warn", "check": "presence", "detail": "maybe"},
            ],
        }
        reports = [
            {"mission_id": 1, "mission": "Task 1"},
            {"mission_id": 2, "mission": "Task 2"},
            {"mission_id": 3, "mission": "Task 3"},
        ]
        result = _get_failed_missions(audit, reports)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["mission_id"], 2)


class TestBuildRerunInput(unittest.TestCase):
    def test_extracts_full_block_from_original_input(self) -> None:
        """Bug B: full task block (including sub-tasks) must be preserved."""
        reports = [{"mission_id": 1, "mission": "Task 1: Text Analysis Pipeline"}]
        result = _build_rerun_input(reports, _SAMPLE_INPUT)
        self.assertIn("1a.", result)
        self.assertIn("quick brown fox", result)
        self.assertIn("analysis_results.txt", result)

    def test_no_double_task_prefix(self) -> None:
        """Bug C: must not produce 'Task 1: Task 1:' double prefix."""
        reports = [{"mission_id": 1, "mission": "Task 1: Text Analysis Pipeline"}]
        result = _build_rerun_input(reports, _SAMPLE_INPUT)
        self.assertNotIn("Task 1: Task 1:", result)

    def test_fallback_without_original_input(self) -> None:
        """Fallback to mission title when no original_input provided."""
        reports = [{"mission_id": 2, "mission": "Data Sorting"}]
        result = _build_rerun_input(reports)
        self.assertIn("Task 2: Data Sorting", result)

    def test_fallback_avoids_double_prefix(self) -> None:
        """Bug C fallback: if mission already starts with 'Task N:', don't add another."""
        reports = [{"mission_id": 1, "mission": "Task 1: Text Analysis"}]
        result = _build_rerun_input(reports)
        self.assertNotIn("Task 1: Task 1:", result)

    def test_multiple_missions_extracted(self) -> None:
        """Multiple failed missions are all included with their full blocks."""
        reports = [
            {"mission_id": 1, "mission": "Task 1: Text Analysis Pipeline"},
            {"mission_id": 2, "mission": "Task 2: Data Analysis and Sorting"},
        ]
        result = _build_rerun_input(reports, _SAMPLE_INPUT)
        self.assertIn("quick brown fox", result)
        self.assertIn("[45, 23, 67]", result)

    def test_finish_instruction_present(self) -> None:
        reports = [{"mission_id": 1, "mission": "Task 1"}]
        result = _build_rerun_input(reports, _SAMPLE_INPUT)
        self.assertIn("finish", result)


if __name__ == "__main__":
    unittest.main()
