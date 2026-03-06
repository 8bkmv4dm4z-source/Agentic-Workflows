from __future__ import annotations

"""Evaluator specialist subgraph — isolated StateGraph for post-run auditing."""

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from agentic_workflows.orchestration.langgraph.mission_auditor import audit_run


class EvaluatorState(TypedDict):
    """Isolated state for the evaluator specialist subgraph.

    Field names use the ``eval_`` prefix to guarantee zero key-overlap
    with ``RunState``.  The shared fields (task_id, specialist, mission_id,
    tokens_used, status) are absent from RunState so no prefix is needed.
    """

    task_id: str
    specialist: Literal["evaluator"]
    mission_id: int
    eval_mission_reports: list[dict[str, Any]]
    eval_tool_history: list[dict[str, Any]]
    eval_missions: list[str]
    eval_mission_contracts: list[dict[str, Any]]
    eval_audit_report: dict[str, Any] | None
    tokens_used: int
    status: Literal["success", "error", "timeout"]


def _ensure_evaluator_defaults(state: EvaluatorState) -> None:  # type: ignore[type-arg]
    """Repair missing optional fields before evaluate_node logic runs."""
    state.setdefault("eval_mission_reports", [])  # type: ignore[attr-defined]
    state.setdefault("eval_tool_history", [])  # type: ignore[attr-defined]
    state.setdefault("eval_missions", [])  # type: ignore[attr-defined]
    state.setdefault("eval_mission_contracts", [])  # type: ignore[attr-defined]
    state.setdefault("eval_audit_report", None)  # type: ignore[attr-defined]
    state.setdefault("tokens_used", 0)  # type: ignore[attr-defined]
    state.setdefault("status", "success")  # type: ignore[attr-defined]


def build_evaluator_subgraph() -> Any:
    """Build and compile the evaluator specialist subgraph.

    Returns a compiled ``StateGraph`` that can be invoked via ``.invoke(state)``.
    The graph has a single node (``evaluate``) that delegates to ``audit_run()``
    and stores the result in ``eval_audit_report``.
    """

    def evaluate_node(state: EvaluatorState) -> EvaluatorState:  # type: ignore[type-arg]
        """Single evaluate node: calls audit_run() and populates eval_audit_report."""
        _ensure_evaluator_defaults(state)
        try:
            report = audit_run(
                run_id=state.get("task_id", "unknown"),  # type: ignore[attr-defined]
                missions=state.get("eval_missions", []),  # type: ignore[attr-defined]
                mission_reports=state.get("eval_mission_reports", []),  # type: ignore[attr-defined]
                tool_history=state.get("eval_tool_history", []),  # type: ignore[attr-defined]
            )
            state["eval_audit_report"] = report.to_dict()
            state["status"] = "success"
        except Exception as exc:  # noqa: BLE001
            state["eval_audit_report"] = {"error": str(exc)}
            state["status"] = "error"
        return state

    builder: StateGraph = StateGraph(EvaluatorState)
    builder.add_node("evaluate", evaluate_node)
    builder.add_edge(START, "evaluate")
    builder.add_edge("evaluate", END)
    return builder.compile()
