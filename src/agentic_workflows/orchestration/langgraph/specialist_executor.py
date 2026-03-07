"""Executor specialist subgraph — isolated StateGraph for tool dispatch."""
from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore
from agentic_workflows.orchestration.langgraph.tools_registry import build_tool_registry


class ExecutorState(TypedDict):
    """Isolated state for the executor specialist subgraph.

    Field names are prefixed with ``exec_`` (where needed) to guarantee zero
    overlap with ``RunState``.  Neither inherits from any other TypedDict.
    """

    task_id: str
    specialist: Literal["executor"]
    mission_id: int
    tool_scope: list[str]
    input_context: dict[str, Any]
    token_budget: int
    exec_tool_history: list[dict[str, Any]]
    exec_seen_signatures: list[str]
    result: dict[str, Any]
    tokens_used: int
    status: Literal["success", "error", "timeout"]
    mission_goal: str
    prior_results_summary: str


def _ensure_executor_defaults(state: ExecutorState) -> None:  # type: ignore[type-arg]
    """Repair optional fields in-place before execute_node logic runs."""
    state.setdefault("exec_tool_history", [])  # type: ignore[arg-type]
    state.setdefault("exec_seen_signatures", [])  # type: ignore[arg-type]
    state.setdefault("result", {})  # type: ignore[arg-type]
    state.setdefault("tokens_used", 0)  # type: ignore[arg-type]
    state.setdefault("status", "success")  # type: ignore[arg-type]


def build_executor_subgraph(
    tool_scope: list[str] | None = None,
    memo_store: SQLiteMemoStore | None = None,
) -> Any:
    """Build and compile an executor specialist StateGraph.

    Parameters
    ----------
    tool_scope:
        Whitelist of tool names available to this subgraph.  When *None* the
        full registry is used.
    memo_store:
        Optional pre-built ``SQLiteMemoStore``.  Defaults to a fresh
        in-memory/on-disk store when *None*.

    Returns
    -------
    CompiledStateGraph (typed as ``Any`` to avoid langgraph version coupling).
    """
    store = memo_store or SQLiteMemoStore()
    full_registry = build_tool_registry(store)

    if tool_scope is not None:
        registry = {k: v for k, v in full_registry.items() if k in tool_scope}
    else:
        registry = full_registry

    def execute_node(state: ExecutorState) -> ExecutorState:  # type: ignore[type-arg]
        """Single execution node — dispatches one tool call from input_context."""
        _ensure_executor_defaults(state)

        context: dict[str, Any] = state.get("input_context", {})  # type: ignore[call-overload]
        tool_name: str = context.get("tool_name", "")
        args: dict[str, Any] = context.get("args", {})

        tool = registry.get(tool_name)

        if tool is None:
            state["result"] = {"error": f"tool_not_found: {tool_name}"}
            state["status"] = "error"
            return state

        try:
            tool_result = tool.execute(args)
            state["result"] = tool_result
            state["status"] = "success"
            history_entry: dict[str, Any] = {
                "tool": tool_name,
                "args": args,
                "result": tool_result,
            }
            state["exec_tool_history"].append(history_entry)
        except Exception as exc:  # noqa: BLE001
            state["result"] = {"error": str(exc)}
            state["status"] = "error"

        return state

    builder: StateGraph = StateGraph(ExecutorState)
    builder.add_node("execute", execute_node)
    builder.add_edge(START, "execute")
    builder.add_edge("execute", END)

    return builder.compile()
