from __future__ import annotations

"""Last-run context retrieval tool — read-only access to checkpoint store."""

from typing import Any

from .base import Tool


class RetrieveRunContextTool(Tool):
    name = "retrieve_run_context"
    _args_schema = {
        "operation": {"type": "string", "required": "true"},
        "run_id": {"type": "string"},
        "include": {"type": "array"},
        "limit": {"type": "number"},
    }
    description = (
        "Retrieve context from previous agent runs. "
        "Required args: operation ('last_run'|'get_run'|'list_runs'|'get_summary'). "
        "Optional: run_id (required for get_run), include (list of fields), limit (int, for list_runs)."
    )

    def __init__(self, checkpoint_store: Any) -> None:
        self.checkpoint_store = checkpoint_store

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        operation = str(args.get("operation", "")).strip().lower()
        if not operation:
            return {"error": "operation is required"}

        if operation == "last_run":
            return self._last_run(args)
        elif operation == "get_run":
            return self._get_run(args)
        elif operation == "list_runs":
            return self._list_runs(args)
        elif operation == "get_summary":
            return self._get_summary(args)
        else:
            return {"error": f"unknown operation '{operation}'. Valid: last_run, get_run, list_runs, get_summary"}

    def _last_run(self, args: dict[str, Any]) -> dict[str, Any]:
        include = _parse_include(args)
        state = self.checkpoint_store.load_latest_run()
        if state is None:
            return {"error": "no previous runs found"}
        return _extract_run_info(state, include)

    def _get_run(self, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("run_id", "")).strip()
        if not run_id:
            return {"error": "run_id is required for get_run"}
        include = _parse_include(args)
        state = self.checkpoint_store.load_latest(run_id)
        if state is None:
            return {"error": f"run not found: {run_id}"}
        return _extract_run_info(state, include)

    def _list_runs(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = min(int(args.get("limit", 10)), 50)
        runs = self.checkpoint_store.list_runs(limit=limit)
        return {"runs": runs, "count": len(runs)}

    def _get_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        state = self.checkpoint_store.load_latest_run()
        if state is None:
            return {"error": "no previous runs found"}
        return _build_summary(state)


def _parse_include(args: dict[str, Any]) -> set[str]:
    include = args.get("include")
    if isinstance(include, list):
        return set(str(i) for i in include)
    return {"tool_history", "mission_reports", "audit_report", "answer"}


def _extract_run_info(state: dict[str, Any], include: set[str]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "run_id": state.get("run_id", "unknown"),
    }

    if "answer" in include:
        result["answer"] = state.get("final_answer", state.get("answer", ""))

    if "tool_history" in include:
        history = state.get("tool_history", [])
        result["tools_used"] = [
            str(entry.get("tool", entry.get("call", ""))) for entry in history
        ]

    if "mission_reports" in include:
        reports = state.get("mission_reports", [])
        result["missions_completed"] = len([
            r for r in reports if r.get("result") or r.get("used_tools")
        ])
        result["mission_reports"] = reports

    if "audit_report" in include:
        audit = state.get("audit_report")
        if audit:
            result["audit_summary"] = {
                "passed": audit.get("passed", 0),
                "failed": audit.get("failed", 0),
                "score": audit.get("score"),
            }

    return result


def _build_summary(state: dict[str, Any]) -> dict[str, Any]:
    reports = state.get("mission_reports", [])
    missions: list[dict[str, str]] = []
    for r in reports:
        mission = str(r.get("mission", r.get("mission_id", "")))
        status = "completed" if r.get("result") or r.get("used_tools") else "incomplete"
        missions.append({"mission": mission[:100], "status": status})

    audit = state.get("audit_report", {})
    tools = state.get("tool_history", [])
    tool_names = list(dict.fromkeys(
        str(entry.get("tool", entry.get("call", ""))) for entry in tools
    ))

    return {
        "run_id": state.get("run_id", "unknown"),
        "missions": missions,
        "tools_used": tool_names,
        "audit_passed": audit.get("passed", 0) if audit else 0,
        "audit_failed": audit.get("failed", 0) if audit else 0,
    }
