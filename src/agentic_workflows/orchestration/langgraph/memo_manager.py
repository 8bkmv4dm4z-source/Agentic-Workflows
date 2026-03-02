from __future__ import annotations

"""Memo/cache utility functions extracted from graph.py.

Pure functions for cache key generation, lookup candidate computation,
and memo-hit detection. Side-effect-heavy operations that depend on
tools/memo_store/logger remain on LangGraphOrchestrator.
"""

from typing import Any

from agentic_workflows.orchestration.langgraph.mission_tracker import (
    next_incomplete_mission_index,
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
    """Treat memo hit as completion for the next deterministic write mission."""
    reports = state.get("mission_reports", [])
    if not reports:
        return
    index = next_incomplete_mission_index(state)
    if index < 0:
        return
    state["active_mission_index"] = index
    state["active_mission_id"] = index + 1
    reports[index]["result"] = str(memo_hit)
    reports[index]["status"] = "completed"
    mission_text = str(reports[index].get("mission", "")).strip()
    if mission_text and mission_text not in state.get("completed_tasks", []):
        state["completed_tasks"].append(mission_text)
