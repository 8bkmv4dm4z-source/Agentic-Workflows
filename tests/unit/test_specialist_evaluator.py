from __future__ import annotations

"""Unit tests for specialist_evaluator.py — isolation and invocation."""

from agentic_workflows.orchestration.langgraph.specialist_evaluator import (
    EvaluatorState,
    build_evaluator_subgraph,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_evaluator_state(**overrides: object) -> dict:
    """Return a fully-populated EvaluatorState dict with sensible defaults."""
    base: dict = {
        "task_id": "test-t2",
        "specialist": "evaluator",
        "mission_id": 1,
        "eval_mission_reports": [],
        "eval_tool_history": [],
        "eval_missions": [],
        "eval_mission_contracts": [],
        "eval_audit_report": None,
        "tokens_used": 0,
        "status": "success",
    }
    base.update(overrides)
    return base


def _make_mission_report(**overrides: object) -> dict:
    """Return a dict matching MissionReport TypedDict shape with defaults."""
    base: dict = {
        "mission_id": 1,
        "mission": "Task 1: Sort the array",
        "used_tools": ["sort_array"],
        "tool_results": [
            {
                "tool": "sort_array",
                "result": {
                    "sorted": [1, 2, 3, 4, 5],
                    "count": 5,
                    "order": "asc",
                    "original": [3, 1, 4, 1, 5],
                },
            }
        ],
        "result": "Sorted array successfully.",
        "status": "completed",
        "required_tools": ["sort_array"],
        "required_files": [],
        "written_files": [],
        "expected_fibonacci_count": None,
        "contract_checks": [],
        "subtask_contracts": [],
        "subtask_statuses": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_evaluator_subgraph_basic() -> None:
    """Invoking with a populated state returns status=='success' and a dict report."""
    graph = build_evaluator_subgraph()
    mission_report = _make_mission_report()
    state = _make_evaluator_state(
        task_id="run-basic",
        eval_missions=["Task 1: Sort the array"],
        eval_mission_reports=[mission_report],
        eval_tool_history=[
            {
                "call": 1,
                "tool": "sort_array",
                "args": {"array": [3, 1, 4, 1, 5], "order": "asc"},
                "result": {
                    "sorted": [1, 1, 3, 4, 5],
                    "count": 5,
                    "order": "asc",
                    "original": [3, 1, 4, 1, 5],
                },
            }
        ],
    )
    result = graph.invoke(state)
    assert result["status"] == "success", f"Expected success, got: {result['status']}"
    assert result["eval_audit_report"] is not None, "eval_audit_report should be populated"
    assert isinstance(result["eval_audit_report"], dict), (
        f"eval_audit_report must be dict, got: {type(result['eval_audit_report'])}"
    )


def test_evaluator_subgraph_audit_report_has_fields() -> None:
    """eval_audit_report dict contains the standard AuditReport keys."""
    graph = build_evaluator_subgraph()
    mission_report = _make_mission_report()
    state = _make_evaluator_state(
        task_id="run-fields",
        eval_missions=["Task 1: Sort the array"],
        eval_mission_reports=[mission_report],
    )
    result = graph.invoke(state)
    assert result["status"] == "success"
    report = result["eval_audit_report"]
    assert isinstance(report, dict), f"Expected dict, got {type(report)}"
    for key in ("passed", "warned", "failed", "findings"):
        assert key in report, f"AuditReport.to_dict() key '{key}' missing from eval_audit_report"


def test_evaluator_subgraph_empty_state() -> None:
    """Invoking with all list fields empty returns status=='success' (audit_run handles empty)."""
    graph = build_evaluator_subgraph()
    state = _make_evaluator_state(
        task_id="run-empty",
        eval_missions=[],
        eval_mission_reports=[],
        eval_tool_history=[],
    )
    result = graph.invoke(state)
    assert result["status"] == "success", (
        f"Empty state should succeed gracefully; got status={result['status']}"
    )
    assert result["eval_audit_report"] is not None, (
        "eval_audit_report must not be None even for empty input"
    )
    assert isinstance(result["eval_audit_report"], dict)


def test_evaluator_state_fields() -> None:
    """EvaluatorState has exactly the 10 expected fields."""
    expected = {
        "task_id",
        "specialist",
        "mission_id",
        "eval_mission_reports",
        "eval_tool_history",
        "eval_missions",
        "eval_mission_contracts",
        "eval_audit_report",
        "tokens_used",
        "status",
        "mission_goal",
        "prior_results_summary",
    }
    actual = set(EvaluatorState.__annotations__)
    assert actual == expected, (
        f"EvaluatorState field mismatch.\n  Expected: {sorted(expected)}\n  Got: {sorted(actual)}"
    )
