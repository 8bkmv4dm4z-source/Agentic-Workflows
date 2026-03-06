"""Unit tests for reviewer policies."""

from __future__ import annotations

import unittest

from agentic_workflows.orchestration.langgraph.reviewer import FailOnlyReviewer, WeightedReviewer


class TestFailOnlyReviewer(unittest.TestCase):
    def test_reruns_on_fail(self) -> None:
        decision = FailOnlyReviewer().decide(
            audit_report={
                "findings": [
                    {"mission_id": 2, "level": "fail", "check": "x", "detail": "y"},
                    {"mission_id": 1, "level": "warn", "check": "x", "detail": "y"},
                ]
            },
            mission_reports=[],
            derived_snapshot=None,
            changed_files=["fib50.txt"],
        )
        self.assertEqual(decision.action, "rerun")
        self.assertEqual(decision.rerun_mission_ids, [2])
        self.assertEqual(decision.changed_files, ["fib50.txt"])

    def test_ends_when_no_fail(self) -> None:
        decision = FailOnlyReviewer().decide(
            audit_report={"findings": [{"mission_id": 1, "level": "warn"}]},
            mission_reports=[],
            derived_snapshot=None,
            changed_files=[],
        )
        self.assertEqual(decision.action, "end")
        self.assertEqual(decision.rerun_mission_ids, [])


class TestWeightedReviewer(unittest.TestCase):
    def test_hard_fail_override(self) -> None:
        decision = WeightedReviewer().decide(
            audit_report={"findings": [{"mission_id": 1, "level": "fail"}]},
            mission_reports=[{"mission_id": 1, "status": "completed"}],
            derived_snapshot={},
            changed_files=["out.txt"],
        )
        self.assertEqual(decision.action, "rerun")
        self.assertEqual(decision.rerun_mission_ids, [1])
        self.assertEqual(decision.weighted_score, 1.0)

    def test_below_threshold_ends(self) -> None:
        decision = WeightedReviewer(threshold=0.35).decide(
            audit_report={"findings": []},
            mission_reports=[
                {
                    "mission_id": 1,
                    "status": "completed",
                    "subtask_statuses": [{"satisfied": True}],
                    "required_files": ["out.txt"],
                }
            ],
            derived_snapshot={},
            changed_files=["out.txt"],
        )
        self.assertEqual(decision.action, "end")
        assert decision.weighted_score is not None
        self.assertLess(decision.weighted_score, 0.35)

    def test_warn_can_trigger_threshold(self) -> None:
        decision = WeightedReviewer(threshold=0.35).decide(
            audit_report={"findings": [{"mission_id": 1, "level": "warn"}]},
            mission_reports=[
                {
                    "mission_id": 1,
                    "status": "completed",
                    "subtask_statuses": [{"satisfied": True}],
                    "required_files": ["out.txt"],
                }
            ],
            derived_snapshot={},
            changed_files=["out.txt"],
        )
        self.assertEqual(decision.action, "rerun")
        self.assertIn(1, decision.rerun_mission_ids)


if __name__ == "__main__":
    unittest.main()
