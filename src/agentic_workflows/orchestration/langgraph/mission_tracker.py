from __future__ import annotations

"""Mission lifecycle tracking extracted from graph.py.

Functions for mission preview, attribution, requirement inference,
contract building, progress tracking, and completion detection.
"""

import re
from typing import Any

from agentic_workflows.logger import get_logger
from agentic_workflows.orchestration.langgraph.mission_parser import StructuredPlan
from agentic_workflows.orchestration.langgraph.text_extractor import (
    extract_fibonacci_count,
    extract_write_path_from_mission,
)

LOGGER = get_logger("langgraph.mission_tracker")
HELPER_TOOLS = {"memoize", "retrieve_memo"}


def mission_preview_from_state(state: dict[str, Any]) -> dict[int, dict[str, set[str]]]:
    """Build mutable mission usage preview for action tagging within one planner turn."""
    preview: dict[int, dict[str, set[str]]] = {}
    for report in state.get("mission_reports", []):
        mission_id = int(report.get("mission_id", 0))
        if mission_id <= 0:
            continue
        preview[mission_id] = {
            "used_tools": {str(tool) for tool in report.get("used_tools", [])},
            "written_files": {
                str(path).replace("\\", "/").rsplit("/", 1)[-1]
                for path in report.get("written_files", [])
            },
        }
    return preview


def resolve_mission_id_for_action(
    state: dict[str, Any],
    action: dict[str, Any],
    *,
    preview: dict[int, dict[str, set[str]]] | None = None,
) -> int:
    """Resolve which mission an action should be attributed to."""
    if str(action.get("action", "")).strip().lower() != "tool":
        LOGGER.info(
            "MISSION ATTRIBUTION skip reason=non_tool_action action=%s",
            action.get("action"),
        )
        return 0
    reports = state.get("mission_reports", [])
    if not reports:
        LOGGER.info("MISSION ATTRIBUTION skip reason=no_reports")
        return 0
    tool_name = str(action.get("tool_name", "")).strip()
    args = dict(action.get("args", {}))
    helper_tools = HELPER_TOOLS

    def _requirements_for_report(report: dict[str, Any]) -> tuple[set[str], set[str]]:
        tools = set(report.get("required_tools", []))
        files = {
            str(path).replace("\\", "/").rsplit("/", 1)[-1]
            for path in report.get("required_files", [])
        }
        if not tools and not files:
            inferred_tools, inferred_files, _ = infer_requirements_from_text(
                str(report.get("mission", ""))
            )
            tools = set(inferred_tools)
            files = {
                str(path).replace("\\", "/").rsplit("/", 1)[-1]
                for path in inferred_files
            }
        return tools, files

    # Path-based mapping for deterministic write-related actions.
    path_hint = ""
    if tool_name == "write_file":
        path_hint = str(args.get("path", "")).strip()
    elif tool_name == "memoize":
        key = str(args.get("key", "")).strip()
        if key.startswith("write_file:"):
            path_hint = key.split(":", 1)[1].strip()
    if path_hint:
        basename = path_hint.replace("\\", "/").rsplit("/", 1)[-1]
        for report in reports:
            required_files = _requirements_for_report(report)[1]
            if basename and basename in required_files:
                mission_id = int(report.get("mission_id", 0))
                LOGGER.info(
                    "MISSION ATTRIBUTION tool=%s mission_id=%s reason=path_hint basename=%s",
                    tool_name,
                    mission_id,
                    basename,
                )
                return mission_id

    # Prefer missions where this required tool has not yet been observed.
    for report in reports:
        if str(report.get("status", "pending")) == "completed":
            continue
        required_tools = _requirements_for_report(report)[0]
        mission_id = int(report.get("mission_id", 0))
        already_used = set(report.get("used_tools", []))
        if preview and mission_id in preview:
            already_used = set(preview[mission_id].get("used_tools", set()))
        if tool_name in required_tools and tool_name not in already_used:
            chosen_id = int(report.get("mission_id", 0))
            LOGGER.info(
                "MISSION ATTRIBUTION tool=%s mission_id=%s reason=required_tool_first_use",
                tool_name,
                chosen_id,
            )
            return chosen_id

    # Fallback: any incomplete mission that expects the tool.
    for report in reports:
        if str(report.get("status", "pending")) == "completed":
            continue
        required_tools = _requirements_for_report(report)[0]
        if tool_name in required_tools:
            chosen_id = int(report.get("mission_id", 0))
            LOGGER.info(
                "MISSION ATTRIBUTION tool=%s mission_id=%s reason=required_tool_incomplete",
                tool_name,
                chosen_id,
            )
            return chosen_id

    # Queue-aware fallback: assign to the next mission still incomplete in preview.
    for report in reports:
        if str(report.get("status", "pending")) == "completed":
            continue
        mission_id = int(report.get("mission_id", 0))
        required_tools, required_files = _requirements_for_report(report)
        already_used = set(report.get("used_tools", []))
        written_files = {
            str(path).replace("\\", "/").rsplit("/", 1)[-1]
            for path in report.get("written_files", [])
        }
        if preview and mission_id in preview:
            already_used = set(preview[mission_id].get("used_tools", set()))
            written_files = set(preview[mission_id].get("written_files", set()))

        observed_tools = set(already_used)
        observed_non_helper_tools = {tool for tool in already_used if tool not in helper_tools}
        if required_tools or required_files:
            missing_tools = required_tools - observed_tools
            missing_files = required_files - written_files
            if missing_tools or missing_files:
                LOGGER.info(
                    (
                        "MISSION ATTRIBUTION tool=%s mission_id=%s "
                        "reason=missing_requirements missing_tools=%s missing_files=%s"
                    ),
                    tool_name,
                    mission_id,
                    sorted(missing_tools),
                    sorted(missing_files),
                )
                return mission_id
            continue

        # Generic mission: one non-helper tool call completes it.
        if not observed_non_helper_tools:
            LOGGER.info(
                "MISSION ATTRIBUTION tool=%s mission_id=%s reason=generic_non_helper",
                tool_name,
                mission_id,
            )
            return mission_id

    next_index = next_incomplete_mission_index(state)
    if 0 <= next_index < len(reports):
        mission_id = int(reports[next_index].get("mission_id", 0))
        LOGGER.info(
            "MISSION ATTRIBUTION tool=%s mission_id=%s reason=next_incomplete",
            tool_name,
            mission_id,
        )
        return mission_id
    LOGGER.info("MISSION ATTRIBUTION tool=%s mission_id=0 reason=no_match", tool_name)
    return 0


def infer_requirements_from_text(
    text: str,
) -> tuple[set[str], set[str], int | None]:
    """Infer required tools/files from mission or sub-task text."""
    lower = text.lower()
    required_tools: set[str] = set()
    required_files: set[str] = set()

    if re.search(r"\b(uppercase|lowercase|reverse)\b", lower):
        required_tools.add("string_ops")
    if re.search(r"\b(repeat|confirmation)\b", lower):
        required_tools.add("repeat_message")
    if re.search(r"\bretrieve\b", lower) and re.search(r"\bmemo(?:ize)?\b", lower):
        required_tools.add("retrieve_memo")
    if re.search(r"\bmemoize\b", lower):
        required_tools.add("memoize")
    if re.search(r"\bjson\b", lower):
        required_tools.add("json_parser")
    if re.search(r"\b(regex|pattern)\b", lower):
        required_tools.add("regex_matcher")
    if re.search(r"\bextract\b", lower) and (
        re.search(r"\bname\b", lower) or re.search(r"\bnumbers?\b", lower)
    ):
        required_tools.add("regex_matcher")
    if (
        re.search(r"\bsort\b", lower)
        or re.search(r"\bascending\b", lower)
        or re.search(r"\bdescending\b", lower)
        or re.search(r"\balphabetic(?:ally)?\b", lower)
    ):
        required_tools.add("sort_array")
    if re.search(r"\b(mean|sum|median|average)\b", lower):
        required_tools.add("math_stats")
    if (
        re.search(r"\boutliers?\b", lower)
        or re.search(r"\bstatistics?\b", lower)
        or (re.search(r"\banaly(?:s|z)e\b", lower) and re.search(r"\bnumbers?\b", lower))
    ):
        required_tools.add("data_analysis")
    if re.search(r"\banaly(?:s|z)e\b", lower) and re.search(r"\btext\b", lower):
        required_tools.add("text_analysis")
    if (
        re.search(r"\bwrite(?:_file)?\b", lower)
        or "save to" in lower
        or "output to" in lower
    ):
        required_tools.add("write_file")
        path = extract_write_path_from_mission(text)
        if path:
            required_files.add(path.replace("\\", "/").rsplit("/", 1)[-1])

    expected_fibonacci_count: int | None = None
    if "fibonacci" in lower:
        required_tools.add("write_file")
        expected_fibonacci_count = extract_fibonacci_count(text)
        path = extract_write_path_from_mission(text)
        if path:
            required_files.add(path.replace("\\", "/").rsplit("/", 1)[-1])

    return required_tools, required_files, expected_fibonacci_count


def build_mission_contracts_from_plan(
    structured_plan: StructuredPlan, missions: list[str]
) -> list[dict[str, Any]]:
    """Derive per-mission completion contracts from structured plan data."""
    LOGGER.info(
        "MISSION CONTRACTS start missions=%s parsing_method=%s",
        len(missions),
        structured_plan.parsing_method,
    )
    contracts: list[dict[str, Any]] = []
    children_by_parent: dict[str, list[Any]] = {}
    for step in structured_plan.steps:
        if step.parent_id is not None:
            children_by_parent.setdefault(step.parent_id, []).append(step)

    top_level = [step for step in structured_plan.steps if step.parent_id is None]
    for idx, mission in enumerate(missions):
        mission_id = idx + 1
        parent = top_level[idx] if idx < len(top_level) else None
        if parent is None:
            parent = next((step for step in top_level if step.id == str(mission_id)), None)

        required_tools: set[str] = set()
        required_files: set[str] = set()
        expected_fibonacci_count: int | None = None
        checks: list[str] = []
        mission_texts: list[str] = [mission]
        subtask_contracts: list[dict[str, Any]] = []

        base_tools, base_files, base_fib = infer_requirements_from_text(mission)
        required_tools.update(base_tools)
        required_files.update(base_files)
        if base_fib is not None:
            expected_fibonacci_count = base_fib
        subtask_contracts.append(
            {
                "id": parent.id if parent is not None else f"{mission_id}",
                "description": mission,
                "required_tools": sorted(base_tools),
                "required_files": sorted(base_files),
                "expected_fibonacci_count": base_fib,
            }
        )

        if parent is not None:
            for child in children_by_parent.get(parent.id, []):
                mission_texts.append(child.description)
                tools, files, fib_count = infer_requirements_from_text(child.description)
                required_tools.update(tools)
                if files:
                    required_tools.add("write_file")
                required_files.update(files)
                if fib_count is not None:
                    required_tools.add("write_file")
                    expected_fibonacci_count = fib_count
                subtask_contracts.append(
                    {
                        "id": child.id,
                        "description": child.description,
                        "required_tools": sorted(tools),
                        "required_files": sorted(files),
                        "expected_fibonacci_count": fib_count,
                    }
                )

        if expected_fibonacci_count is not None:
            checks.append(f"fibonacci_count={expected_fibonacci_count}")
        if required_files:
            checks.append("required_files")
        if required_tools:
            checks.append("required_tools")
        if any(
            "pattern" in text.lower()
            and ("sum" in text.lower() or "mean" in text.lower())
            for text in mission_texts
        ):
            checks.append("pattern_report_consistency")

        contracts.append(
            {
                "mission_id": mission_id,
                "required_tools": sorted(required_tools),
                "required_files": sorted(required_files),
                "expected_fibonacci_count": expected_fibonacci_count,
                "contract_checks": checks,
                "subtask_contracts": subtask_contracts,
            }
        )
        LOGGER.info(
            (
                "MISSION CONTRACT mission_id=%s parent_step_id=%s "
                "required_tools=%s required_files=%s subtasks=%s"
            ),
            mission_id,
            parent.id if parent is not None else "n/a",
            sorted(required_tools),
            sorted(required_files),
            len(subtask_contracts),
        )
    LOGGER.info("MISSION CONTRACTS built count=%s", len(contracts))
    return contracts


def initialize_mission_reports(
    missions: list[str], *, contracts: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Build initial mission report objects before tool execution starts."""
    contracts = contracts or []
    reports: list[dict[str, Any]] = []
    for index, mission in enumerate(missions):
        contract = contracts[index] if index < len(contracts) else {}
        reports.append(
            {
                "mission_id": index + 1,
                "mission": mission,
                "used_tools": [],
                "tool_results": [],
                "result": "",
                "status": "pending",
                "required_tools": list(contract.get("required_tools", [])),
                "required_files": list(contract.get("required_files", [])),
                "written_files": [],
                "expected_fibonacci_count": contract.get("expected_fibonacci_count"),
                "contract_checks": list(contract.get("contract_checks", [])),
                "subtask_contracts": list(contract.get("subtask_contracts", [])),
                "subtask_statuses": [],
            }
        )
    return reports


def next_incomplete_mission_index(state: dict[str, Any]) -> int:
    """Return index of the first mission report that is not completed."""
    reports = state.get("mission_reports", [])
    for index, report in enumerate(reports):
        if str(report.get("status", "pending")) != "completed":
            return index
    return -1


def refresh_mission_status(state: dict[str, Any], mission_index: int) -> None:
    """Recompute mission completion from required tools/files."""
    reports = state.get("mission_reports", [])
    if mission_index < 0 or mission_index >= len(reports):
        return
    report = reports[mission_index]
    previous_status = str(report.get("status", "pending"))
    required_tools = set(report.get("required_tools", []))
    required_files = {
        str(path).replace("\\", "/").rsplit("/", 1)[-1]
        for path in report.get("required_files", [])
    }
    if not required_tools and not required_files:
        inferred_tools, inferred_files, inferred_fib_count = infer_requirements_from_text(
            str(report.get("mission", ""))
        )
        required_tools = set(inferred_tools)
        required_files = {
            str(path).replace("\\", "/").rsplit("/", 1)[-1]
            for path in inferred_files
        }
        if inferred_tools and not report.get("required_tools"):
            report["required_tools"] = sorted(required_tools)
        if inferred_files and not report.get("required_files"):
            report["required_files"] = sorted(required_files)
        if (
            inferred_fib_count is not None
            and not isinstance(report.get("expected_fibonacci_count"), int)
        ):
            report["expected_fibonacci_count"] = inferred_fib_count
    observed_tools = {str(tool) for tool in report.get("used_tools", [])}
    observed_non_helper_tools = {tool for tool in observed_tools if tool not in HELPER_TOOLS}
    written_files = {
        str(path).replace("\\", "/").rsplit("/", 1)[-1]
        for path in report.get("written_files", [])
    }

    if required_tools or required_files:
        missing_tools = sorted(required_tools - observed_tools)
    else:
        missing_tools = [] if observed_non_helper_tools else ["<non_helper_tool>"]
    missing_files = sorted(required_files - written_files)

    subtask_contracts = list(report.get("subtask_contracts", []))
    if not subtask_contracts and (required_tools or required_files):
        subtask_contracts = [
            {
                "id": str(report.get("mission_id", mission_index + 1)),
                "description": str(report.get("mission", "")),
                "required_tools": sorted(required_tools),
                "required_files": sorted(required_files),
                "expected_fibonacci_count": report.get("expected_fibonacci_count"),
            }
        ]
    subtask_statuses: list[dict[str, Any]] = []
    for subtask in subtask_contracts:
        sub_required_tools = {str(tool) for tool in subtask.get("required_tools", [])}
        sub_required_files = {
            str(path).replace("\\", "/").rsplit("/", 1)[-1]
            for path in subtask.get("required_files", [])
        }
        sub_missing_tools = sorted(sub_required_tools - observed_tools)
        sub_missing_files = sorted(sub_required_files - written_files)
        subtask_statuses.append(
            {
                "id": str(subtask.get("id", "")),
                "description": str(subtask.get("description", "")),
                "missing_tools": sub_missing_tools,
                "missing_files": sub_missing_files,
                "satisfied": not sub_missing_tools and not sub_missing_files,
            }
        )
    report["subtask_statuses"] = subtask_statuses
    subtasks_satisfied = all(
        bool(item.get("satisfied", False)) for item in subtask_statuses
    ) if subtask_statuses else not (missing_tools or missing_files)

    latest_result: dict[str, Any] = {}
    tool_results = report.get("tool_results", [])
    if tool_results and isinstance(tool_results[-1], dict):
        candidate = tool_results[-1].get("result")
        if isinstance(candidate, dict):
            latest_result = candidate
    has_latest_error = "error" in latest_result

    if missing_tools or missing_files or not subtasks_satisfied:
        if has_latest_error:
            report["status"] = "failed"
        else:
            report["status"] = "in_progress" if report.get("used_tools") else "pending"
    else:
        report["status"] = "failed" if has_latest_error else "completed"

    completed_tasks = state.get("completed_tasks", [])
    mission_text = str(report.get("mission", "")).strip()
    if report["status"] == "completed":
        if mission_text and mission_text not in completed_tasks:
            completed_tasks.append(mission_text)
    elif mission_text in completed_tasks:
        completed_tasks.remove(mission_text)
    if report["status"] != previous_status:
        LOGGER.info(
            (
                "MISSION STATUS mission_id=%s index=%s status=%s->%s "
                "missing_tools=%s missing_files=%s has_error=%s"
            ),
            report.get("mission_id", mission_index + 1),
            mission_index,
            previous_status,
            report["status"],
            missing_tools,
            missing_files,
            has_latest_error,
        )


def record_mission_tool_event(
    state: dict[str, Any],
    tool_name: str,
    tool_result: dict[str, Any],
    *,
    mission_index: int | None = None,
    tool_args: dict[str, Any] | None = None,
) -> None:
    """Attach tool usage/results to the intended mission report."""
    reports = state.get("mission_reports", [])
    if not reports:
        contracts = state.get("mission_contracts", [])
        reports = initialize_mission_reports(["Primary mission"], contracts=contracts)
        state["mission_reports"] = reports
        state["missions"] = ["Primary mission"]
        state["active_mission_index"] = -1
        state["active_mission_id"] = 0

    pending = state.get("pending_action") or {}
    pending_mission_id = pending.get("__mission_id")
    if mission_index is None and isinstance(pending_mission_id, int):
        mission_index = pending_mission_id - 1
    if mission_index is None:
        active = int(state.get("active_mission_index", -1))
        if tool_name in {"memoize", "retrieve_memo"} and 0 <= active < len(reports):
            mission_index = active
        else:
            mission_index = next_incomplete_mission_index(state)
    index = min(max(mission_index if mission_index is not None else 0, 0), len(reports) - 1)

    state["active_mission_index"] = index
    state["active_mission_id"] = index + 1
    mission = reports[index]
    mission.setdefault("status", "pending")
    mission.setdefault("required_tools", [])
    mission.setdefault("required_files", [])
    mission.setdefault("written_files", [])
    mission.setdefault("expected_fibonacci_count", None)
    mission.setdefault("contract_checks", [])
    mission.setdefault("subtask_contracts", [])
    mission.setdefault("subtask_statuses", [])
    mission["used_tools"].append(tool_name)
    mission["tool_results"].append({"tool": tool_name, "result": tool_result})
    mission["result"] = str(tool_result)
    if (
        tool_name == "write_file"
        and isinstance(tool_args, dict)
        and "error" not in tool_result
    ):
        written_path = str(tool_args.get("path", "")).strip()
        if written_path:
            basename = written_path.replace("\\", "/").rsplit("/", 1)[-1]
            if basename and basename not in mission["written_files"]:
                mission["written_files"].append(basename)
    LOGGER.info(
        (
            "MISSION TOOL EVENT mission_id=%s index=%s tool=%s has_error=%s "
            "used_tools_count=%s"
        ),
        mission.get("mission_id", index + 1),
        index,
        tool_name,
        "error" in tool_result,
        len(mission.get("used_tools", [])),
    )
    refresh_mission_status(state, index)


def next_incomplete_mission(state: dict[str, Any]) -> str:
    """Return next mission text with non-completed status."""
    reports = state.get("mission_reports", [])
    next_index = next_incomplete_mission_index(state)
    if 0 <= next_index < len(reports):
        return str(reports[next_index].get("mission", ""))
    return ""


def next_incomplete_mission_requirements(state: dict[str, Any]) -> dict[str, Any]:
    """Return missing tool/file requirements for the next incomplete mission."""
    reports = state.get("mission_reports", [])
    index = next_incomplete_mission_index(state)
    if index < 0 or index >= len(reports):
        return {"mission_index": -1, "mission_id": 0, "missing_tools": [], "missing_files": []}

    report = reports[index]
    required_tools = {str(tool) for tool in report.get("required_tools", [])}
    required_files = {
        str(path).replace("\\", "/").rsplit("/", 1)[-1]
        for path in report.get("required_files", [])
    }
    used_tools = {str(tool) for tool in report.get("used_tools", [])}
    written_files = {
        str(path).replace("\\", "/").rsplit("/", 1)[-1]
        for path in report.get("written_files", [])
    }
    return {
        "mission_index": index,
        "mission_id": int(report.get("mission_id", index + 1)),
        "missing_tools": sorted(required_tools - used_tools),
        "missing_files": sorted(required_files - written_files),
    }


def all_missions_completed(state: dict[str, Any]) -> bool:
    """Whether every mission report status is completed."""
    reports = state.get("mission_reports", [])
    if not reports:
        return False
    return all(str(report.get("status", "pending")) == "completed" for report in reports)


def progress_hint_message(state: dict[str, Any]) -> str:
    """Create a compact progress hint for the planner."""
    reports = state.get("mission_reports", [])
    if not reports:
        missions = state.get("missions", [])
        if not missions:
            return ""
        completed_count = len(state.get("completed_tasks", []))
        next_mission_text = next_incomplete_mission(state)
        if next_mission_text:
            return (
                f"Progress: completed {completed_count}/{len(missions)} tasks. "
                f"Next task: {next_mission_text}"
            )
        return f"Progress: completed {completed_count}/{len(missions)} tasks. Emit finish now."

    completed_count = sum(
        1 for report in reports if str(report.get("status", "pending")) == "completed"
    )
    next_mission_text = next_incomplete_mission(state)
    if next_mission_text:
        return (
            f"Progress: completed {completed_count}/{len(reports)} tasks. "
            f"Next task: {next_mission_text}"
        )
    return f"Progress: completed {completed_count}/{len(reports)} tasks. Emit finish now."


def build_auto_finish_answer(state: dict[str, Any]) -> str:
    """Build deterministic summary when all missions are complete."""
    mission_reports = state.get("mission_reports", [])
    summary_parts = ["All tasks completed."]
    for report in mission_reports:
        mission = str(report.get("mission", "")).strip()
        result = str(report.get("result", "")).strip()
        status = str(report.get("status", "pending"))
        if mission and result and status == "completed":
            summary_parts.append(f"{mission} -> {result}")
    return " ".join(summary_parts)
