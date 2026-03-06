"""State isolation acceptance gate — Phase 3 primary ROADMAP check.

These tests assert that ExecutorState and EvaluatorState share zero annotation
keys with RunState.  They act as regression guards: any future field rename that
accidentally re-introduces a collision will fail immediately here.
"""
from __future__ import annotations

from agentic_workflows.orchestration.langgraph.specialist_evaluator import EvaluatorState
from agentic_workflows.orchestration.langgraph.specialist_executor import ExecutorState
from agentic_workflows.orchestration.langgraph.state_schema import RunState

# ---------------------------------------------------------------------------
# Disjointness tests — primary ROADMAP acceptance gate
# ---------------------------------------------------------------------------


def test_executor_state_no_key_overlap_with_run_state() -> None:
    """ExecutorState must share zero annotation keys with RunState.

    LangGraph uses key identity to merge subgraph output back into parent state.
    Any overlap would silently overwrite RunState fields during Phase 4 invocation.
    """
    overlap = set(ExecutorState.__annotations__) & set(RunState.__annotations__)
    assert not overlap, f"ExecutorState keys overlap with RunState: {overlap}"


def test_evaluator_state_no_key_overlap_with_run_state() -> None:
    """EvaluatorState must share zero annotation keys with RunState.

    LangGraph uses key identity to merge subgraph output back into parent state.
    Any overlap would silently overwrite RunState fields during Phase 4 invocation.
    """
    overlap = set(EvaluatorState.__annotations__) & set(RunState.__annotations__)
    assert not overlap, f"EvaluatorState keys overlap with RunState: {overlap}"


# ---------------------------------------------------------------------------
# Required-fields tests — exact field set enforcement
# ---------------------------------------------------------------------------


def test_executor_state_has_required_fields() -> None:
    """ExecutorState must have exactly the 11 specified fields (no more, no less)."""
    expected = {
        "task_id",
        "specialist",
        "mission_id",
        "tool_scope",
        "input_context",
        "token_budget",
        "exec_tool_history",
        "exec_seen_signatures",
        "result",
        "tokens_used",
        "status",
    }
    actual = set(ExecutorState.__annotations__)
    assert actual == expected, (
        f"ExecutorState field mismatch.\n  Expected: {sorted(expected)}\n  Got: {sorted(actual)}"
    )


def test_evaluator_state_has_required_fields() -> None:
    """EvaluatorState must have exactly the 10 specified fields (no more, no less)."""
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
    }
    actual = set(EvaluatorState.__annotations__)
    assert actual == expected, (
        f"EvaluatorState field mismatch.\n  Expected: {sorted(expected)}\n  Got: {sorted(actual)}"
    )
