from __future__ import annotations

import logging

from agentic_workflows.orchestration.langgraph import mission_tracker
from agentic_workflows.orchestration.langgraph.mission_parser import MissionStep, StructuredPlan


def test_non_contiguous_task_ids_map_by_position_and_propagate_child_tools() -> None:
    plan = StructuredPlan(
        steps=[
            MissionStep(id="3", description="Task 3: JSON Processing"),
            MissionStep(id="3a", description="Write sorted names to users_sorted.txt", parent_id="3"),
            MissionStep(id="4", description="Task 4: Pattern Matching"),
            MissionStep(id="4a", description="Write summary to pattern_report.txt", parent_id="4"),
            MissionStep(id="5", description="Task 5: Fibonacci with Analysis"),
            MissionStep(id="5a", description="Write the first 50 fibonacci numbers to fib50.txt", parent_id="5"),
            MissionStep(
                id="5b",
                description='Repeat the final summary as confirmation: "All 5 tasks completed successfully"',
                parent_id="5",
            ),
        ],
        flat_missions=[
            "Task 3: JSON Processing",
            "Task 4: Pattern Matching",
            "Task 5: Fibonacci with Analysis",
        ],
        parsing_method="structured",
    )
    contracts = mission_tracker.build_mission_contracts_from_plan(plan, plan.flat_missions)

    assert len(contracts) == 3
    mission3 = contracts[0]
    mission5 = contracts[2]
    assert "users_sorted.txt" in mission3["required_files"]
    assert "users_sorted.txt" not in mission5["required_files"]
    assert "fib50.txt" in mission5["required_files"]
    assert "write_file" in mission5["required_tools"]
    assert "repeat_message" in mission5["required_tools"]


def test_subtask_validator_gates_completion_until_all_subtasks_succeed() -> None:
    state: dict = {
        "mission_reports": [
            {
                "mission_id": 1,
                "mission": "Task 5: Fibonacci with Analysis",
                "used_tools": [],
                "tool_results": [],
                "result": "",
                "status": "pending",
                "required_tools": ["repeat_message", "write_file"],
                "required_files": ["fib50.txt"],
                "written_files": [],
                "expected_fibonacci_count": 50,
                "contract_checks": ["required_tools", "required_files", "fibonacci_count=50"],
                "subtask_contracts": [
                    {
                        "id": "5a",
                        "description": "Write the first 50 fibonacci numbers to fib50.txt",
                        "required_tools": ["write_file"],
                        "required_files": ["fib50.txt"],
                        "expected_fibonacci_count": 50,
                    },
                    {
                        "id": "5b",
                        "description": "Repeat final confirmation",
                        "required_tools": ["repeat_message"],
                        "required_files": [],
                        "expected_fibonacci_count": None,
                    },
                ],
                "subtask_statuses": [],
            }
        ],
        "missions": ["Task 5: Fibonacci with Analysis"],
        "completed_tasks": [],
        "active_mission_index": 0,
        "active_mission_id": 1,
        "pending_action": None,
    }

    mission_tracker.record_mission_tool_event(
        state=state,
        tool_name="write_file",
        tool_result={"result": "ok", "path": "fib50.txt"},
        mission_index=0,
        tool_args={"path": "fib50.txt", "content": "0,1,1"},
    )

    report = state["mission_reports"][0]
    assert report["status"] == "in_progress"
    assert state["completed_tasks"] == []
    assert any(
        item.get("id") == "5a" and item.get("satisfied") is True
        for item in report["subtask_statuses"]
    )
    assert any(
        item.get("id") == "5b" and item.get("satisfied") is False
        for item in report["subtask_statuses"]
    )

    mission_tracker.record_mission_tool_event(
        state=state,
        tool_name="repeat_message",
        tool_result={"echo": "All 5 tasks completed successfully"},
        mission_index=0,
        tool_args={"message": "All 5 tasks completed successfully"},
    )

    report = state["mission_reports"][0]
    assert report["status"] == "completed"
    assert state["completed_tasks"] == ["Task 5: Fibonacci with Analysis"]
    assert all(item.get("satisfied") is True for item in report["subtask_statuses"])


# ── refresh_mission_status direct tests ──────────────────────────────


def _make_state_with_subtasks(
    used_tools: list[str] | None = None,
    written_files: list[str] | None = None,
    subtask_statuses: list[dict] | None = None,
) -> dict:
    """Helper to build a minimal state for refresh_mission_status tests."""
    return {
        "mission_reports": [
            {
                "mission_id": 1,
                "mission": "Task: multi-step processing",
                "used_tools": used_tools or [],
                "tool_results": [],
                "result": "",
                "status": "pending",
                "required_tools": ["write_file", "sort_array", "data_analysis"],
                "required_files": ["output.txt"],
                "written_files": written_files or [],
                "subtask_contracts": [
                    {
                        "id": "1a",
                        "description": "Sort the data",
                        "required_tools": ["sort_array"],
                        "required_files": [],
                    },
                    {
                        "id": "1b",
                        "description": "Analyze sorted data",
                        "required_tools": ["data_analysis"],
                        "required_files": [],
                    },
                    {
                        "id": "1c",
                        "description": "Write results to output.txt",
                        "required_tools": ["write_file"],
                        "required_files": ["output.txt"],
                    },
                ],
                "subtask_statuses": subtask_statuses or [],
            }
        ],
        "missions": ["Task: multi-step processing"],
        "completed_tasks": [],
    }


def test_refresh_mission_status_computes_subtask_satisfaction() -> None:
    """Direct test: refresh_mission_status correctly marks satisfied subtasks."""
    state = _make_state_with_subtasks(used_tools=["sort_array"])
    mission_tracker.refresh_mission_status(state, 0)
    report = state["mission_reports"][0]
    statuses = report["subtask_statuses"]

    assert len(statuses) == 3
    assert statuses[0]["id"] == "1a"
    assert statuses[0]["satisfied"] is True
    assert statuses[1]["id"] == "1b"
    assert statuses[1]["satisfied"] is False
    assert statuses[2]["id"] == "1c"
    assert statuses[2]["satisfied"] is False
    assert report["status"] == "in_progress"


def test_refresh_mission_status_all_satisfied_completes() -> None:
    """When all subtasks are satisfied, mission status becomes completed."""
    state = _make_state_with_subtasks(
        used_tools=["sort_array", "data_analysis", "write_file"],
        written_files=["output.txt"],
    )
    mission_tracker.refresh_mission_status(state, 0)
    report = state["mission_reports"][0]
    assert report["status"] == "completed"
    assert all(s["satisfied"] for s in report["subtask_statuses"])


def test_refresh_mission_status_emits_subtask_tick_on_transition(caplog) -> None:
    """SUBTASK TICK log emitted when subtask transitions False -> True."""
    initial_statuses = [
        {"id": "1a", "description": "Sort the data", "missing_tools": ["sort_array"],
         "missing_files": [], "satisfied": False},
        {"id": "1b", "description": "Analyze sorted data", "missing_tools": ["data_analysis"],
         "missing_files": [], "satisfied": False},
        {"id": "1c", "description": "Write results to output.txt", "missing_tools": ["write_file"],
         "missing_files": ["output.txt"], "satisfied": False},
    ]
    state = _make_state_with_subtasks(
        used_tools=["sort_array"],
        subtask_statuses=initial_statuses,
    )
    with caplog.at_level(logging.INFO, logger="langgraph.mission_tracker"):
        mission_tracker.refresh_mission_status(state, 0)

    tick_messages = [r.message for r in caplog.records if "SUBTASK TICK" in r.message]
    assert len(tick_messages) == 1
    assert "subtask_id=1a" in tick_messages[0]


def test_refresh_no_tick_when_already_satisfied(caplog) -> None:
    """No SUBTASK TICK when subtask was already satisfied before refresh."""
    initial_statuses = [
        {"id": "1a", "description": "Sort the data", "missing_tools": [],
         "missing_files": [], "satisfied": True},
        {"id": "1b", "description": "Analyze sorted data", "missing_tools": ["data_analysis"],
         "missing_files": [], "satisfied": False},
        {"id": "1c", "description": "Write results to output.txt", "missing_tools": ["write_file"],
         "missing_files": ["output.txt"], "satisfied": False},
    ]
    state = _make_state_with_subtasks(
        used_tools=["sort_array"],
        subtask_statuses=initial_statuses,
    )
    with caplog.at_level(logging.INFO, logger="langgraph.mission_tracker"):
        mission_tracker.refresh_mission_status(state, 0)

    tick_messages = [r.message for r in caplog.records if "SUBTASK TICK" in r.message]
    assert len(tick_messages) == 0


def test_refresh_multiple_ticks_at_once(caplog) -> None:
    """Multiple SUBTASK TICKs when several subtasks transition simultaneously."""
    initial_statuses = [
        {"id": "1a", "description": "Sort", "missing_tools": ["sort_array"],
         "missing_files": [], "satisfied": False},
        {"id": "1b", "description": "Analyze", "missing_tools": ["data_analysis"],
         "missing_files": [], "satisfied": False},
        {"id": "1c", "description": "Write", "missing_tools": ["write_file"],
         "missing_files": ["output.txt"], "satisfied": False},
    ]
    state = _make_state_with_subtasks(
        used_tools=["sort_array", "data_analysis", "write_file"],
        written_files=["output.txt"],
        subtask_statuses=initial_statuses,
    )
    with caplog.at_level(logging.INFO, logger="langgraph.mission_tracker"):
        mission_tracker.refresh_mission_status(state, 0)

    tick_messages = [r.message for r in caplog.records if "SUBTASK TICK" in r.message]
    assert len(tick_messages) == 3
