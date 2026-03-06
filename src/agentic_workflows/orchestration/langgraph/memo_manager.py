from __future__ import annotations

"""Memo/cache utility functions extracted from graph.py.

Pure functions for cache key generation, lookup candidate computation,
and memo-hit detection. Side-effect-heavy operations that depend on
tools/memo_store/logger remain on LangGraphOrchestrator.
"""

from typing import Any

from agentic_workflows.orchestration.langgraph.mission_tracker import (
    next_incomplete_mission_index,
    refresh_mission_status,
)


def cache_key_for_path(path: str) -> str:
    """Build cache key for reusable write_file inputs."""
    return f"write_file_input:{path}"


def write_cache_candidates(path: str) -> list[str]:
    """Return exact and basename keys for reusable write inputs."""
    if not path.strip():
        return []
    keys = [cache_key_for_path(path)]
    basename = path.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if basename and basename != path:
        keys.append(cache_key_for_path(basename))
    return keys


def has_attempted_memo_lookup(*, state: dict[str, Any], candidate_keys: list[str]) -> bool:
    """Whether retrieve_memo has already been attempted for any candidate key in this run."""
    if not candidate_keys:
        return True
    for event in state.get("tool_history", []):
        if str(event.get("tool", "")) != "retrieve_memo":
            continue
        args = dict(event.get("args", {}))
        key = str(args.get("key", ""))
        if key in candidate_keys:
            return True
    return False


def mark_next_mission_complete_from_memo_hit(
    *, state: dict[str, Any], memo_hit: dict[str, Any]
) -> None:
    """Apply memo-hit context to the next mission without bypassing sub-task gates."""
    reports = state.get("mission_reports", [])
    if not reports:
        return
    index = next_incomplete_mission_index(state)
    if index < 0:
        return
    state["active_mission_index"] = index
    state["active_mission_id"] = index + 1
    report = reports[index]
    report.setdefault("used_tools", [])
    report.setdefault("tool_results", [])
    report.setdefault("written_files", [])

    path_hint = ""
    pending_action = state.get("pending_action") or {}
    if str(pending_action.get("tool_name", "")) == "write_file":
        path_hint = str(dict(pending_action.get("args", {})).get("path", "")).strip()
    if not path_hint:
        key = str(memo_hit.get("key", "")).strip()
        if key.startswith("write_file:"):
            path_hint = key.split(":", 1)[1].strip()

    synthetic_result: dict[str, Any] = {
        "result": "memo_hit_reused",
        "source": "retrieve_memo",
    }
    if path_hint:
        synthetic_result["path"] = path_hint
    report["used_tools"].append("write_file")
    report["tool_results"].append({"tool": "write_file", "result": synthetic_result})
    report["result"] = str(memo_hit)

    if path_hint:
        basename = path_hint.replace("\\", "/").rsplit("/", 1)[-1]
        if basename and basename not in report["written_files"]:
            report["written_files"].append(basename)

    refresh_mission_status(state, index)
