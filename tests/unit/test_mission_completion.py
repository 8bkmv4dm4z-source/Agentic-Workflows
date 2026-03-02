"""Tests for premature mission completion guards (Option A + C)."""

import importlib.util
import json
import tempfile
import unittest

if importlib.util.find_spec("langgraph") is None:  # pragma: no cover
    LANGGRAPH_AVAILABLE = False
else:
    LANGGRAPH_AVAILABLE = True
    from agentic_workflows.orchestration.langgraph.checkpoint_store import (
        SQLiteCheckpointStore,
    )
    from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
    from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore
    from agentic_workflows.orchestration.langgraph.policy import MemoizationPolicy
    from agentic_workflows.orchestration.langgraph.state_schema import new_run_state


class DummyProvider:
    def generate(self, messages):  # noqa: ANN001
        return json.dumps({"action": "finish", "answer": "done"})


def _make_orchestrator(tmp: str) -> "LangGraphOrchestrator":
    return LangGraphOrchestrator(
        provider=DummyProvider(),
        memo_store=SQLiteMemoStore(f"{tmp}/memo.db"),
        checkpoint_store=SQLiteCheckpointStore(f"{tmp}/cp.db"),
        policy=MemoizationPolicy(max_policy_retries=1),
    )


def _base_state(missions: list[str], structured_plan: dict | None = None) -> dict:
    reports = [
        {
            "mission": m,
            "used_tools": [],
            "tool_results": [],
            "result": "",
        }
        for m in missions
    ]
    state: dict = {
        "missions": missions,
        "mission_reports": reports,
        "completed_tasks": [],
        "active_mission_index": -1,
    }
    if structured_plan is not None:
        state["structured_plan"] = structured_plan
    return state


@unittest.skipUnless(LANGGRAPH_AVAILABLE, "langgraph not installed")
class TestMissionCompletionGates(unittest.TestCase):
    def test_prerequisite_tool_does_not_complete_write_mission(self) -> None:
        """math_stats should NOT complete a mission whose text implies a write.
        Only write_file may mark write-keyword missions complete."""
        with tempfile.TemporaryDirectory() as tmp:
            orch = _make_orchestrator(tmp)
            state = _base_state(["Compute stats and write results to file"])

            # Prerequisite tool runs first — mission should NOT be complete yet
            orch._record_mission_tool_event(state, "math_stats", {"mean": 5.0})
            self.assertEqual(state["completed_tasks"], [])

            # write_file runs second — mission IS complete ("write" in mission text)
            orch._record_mission_tool_event(state, "write_file", {"path": "out.txt"})
            self.assertEqual(len(state["completed_tasks"]), 1)

    def test_single_tool_mission_completes_immediately(self) -> None:
        """Regression guard: a simple single-tool mission with no structured plan
        should still complete on the first non-helper tool call."""
        with tempfile.TemporaryDirectory() as tmp:
            orch = _make_orchestrator(tmp)
            state = _base_state(["Repeat the message hello"])

            orch._record_mission_tool_event(
                state, "repeat_message", {"repeated": "hello"}
            )
            self.assertEqual(len(state["completed_tasks"]), 1)
            self.assertEqual(
                state["completed_tasks"][0], "Repeat the message hello"
            )

    def test_write_file_on_generic_mission_completes(self) -> None:
        """write_file may mark any mission complete — the inverse-A guard only
        blocks OTHER tools from claiming write-keyword missions."""
        with tempfile.TemporaryDirectory() as tmp:
            orch = _make_orchestrator(tmp)
            state = _base_state(["run test"])

            orch._record_mission_tool_event(
                state, "write_file", {"path": "out.txt"}
            )
            self.assertEqual(len(state["completed_tasks"]), 1)

    def test_non_write_tool_blocked_on_write_keyword_mission(self) -> None:
        """sort_array should NOT mark a 'write results' mission complete
        — only write_file may advance write-keyword missions."""
        with tempfile.TemporaryDirectory() as tmp:
            orch = _make_orchestrator(tmp)
            state = _base_state(["Sort and save to file"])

            orch._record_mission_tool_event(
                state, "sort_array", {"sorted": [1, 2]}
            )
            self.assertEqual(state["completed_tasks"], [])

    def test_cache_reuse_skipped_for_complex_write_mission(self) -> None:
        """Cache reuse should not short-circuit missions that require additional tools."""
        with tempfile.TemporaryDirectory() as tmp:
            memo_store = SQLiteMemoStore(f"{tmp}/memo.db")
            memo_store.put(
                run_id="shared",
                key="write_file_input:analysis_results.txt",
                value={"path": "analysis_results.txt", "content": "CACHED"},
                namespace="cache",
                source_tool="test",
                step=0,
            )
            orch = LangGraphOrchestrator(
                provider=DummyProvider(),
                memo_store=memo_store,
                checkpoint_store=SQLiteCheckpointStore(f"{tmp}/cp.db"),
                policy=MemoizationPolicy(max_policy_retries=1),
            )
            state = new_run_state("system", "user", run_id="cache-complex")
            state["missions"] = ["Task 1: Analyze text and write results to analysis_results.txt"]
            state["mission_reports"] = [
                {
                    "mission_id": 1,
                    "mission": state["missions"][0],
                    "used_tools": [],
                    "tool_results": [],
                    "result": "",
                    "status": "pending",
                    "required_tools": ["text_analysis", "write_file"],
                    "required_files": ["analysis_results.txt"],
                    "written_files": [],
                    "expected_fibonacci_count": None,
                    "contract_checks": ["required_tools", "required_files"],
                }
            ]

            reused = orch._maybe_complete_next_write_from_cache(state)
            self.assertFalse(reused)
            self.assertEqual(state["tool_history"], [])

    def test_cache_reuse_not_reapplied_for_same_mission(self) -> None:
        """A cache-reuse write should be attempted at most once per mission/path in a run."""
        with tempfile.TemporaryDirectory() as tmp:
            memo_store = SQLiteMemoStore(f"{tmp}/memo.db")
            memo_store.put(
                run_id="shared",
                key="write_file_input:analysis_results.txt",
                value={"path": "analysis_results.txt", "content": "CACHED"},
                namespace="cache",
                source_tool="test",
                step=0,
            )
            orch = LangGraphOrchestrator(
                provider=DummyProvider(),
                memo_store=memo_store,
                checkpoint_store=SQLiteCheckpointStore(f"{tmp}/cp.db"),
                policy=MemoizationPolicy(max_policy_retries=1),
            )
            state = new_run_state("system", "user", run_id="cache-once")
            state["missions"] = ["Task 1: Write output to analysis_results.txt"]
            state["mission_reports"] = [
                {
                    "mission_id": 1,
                    "mission": state["missions"][0],
                    "used_tools": [],
                    "tool_results": [],
                    "result": "",
                    "status": "pending",
                    "required_tools": ["write_file"],
                    "required_files": ["other_output.txt"],
                    "written_files": [],
                    "expected_fibonacci_count": None,
                    "contract_checks": ["required_tools", "required_files"],
                }
            ]

            first = orch._maybe_complete_next_write_from_cache(state)
            second = orch._maybe_complete_next_write_from_cache(state)
            self.assertTrue(first)
            self.assertFalse(second)
            self.assertEqual(len(state["tool_history"]), 1)

    def test_mean_substring_does_not_infer_math_stats(self) -> None:
        """'Meanwhile' should not trigger a false math_stats requirement."""
        with tempfile.TemporaryDirectory() as tmp:
            orch = _make_orchestrator(tmp)
            tools, _files, _fib = orch._infer_requirements_from_text(
                "Meanwhile, the brown cat watched from the fence."
            )
            self.assertNotIn("math_stats", tools)

    def test_memo_hit_does_not_bypass_repeat_subtask_requirement(self) -> None:
        """Memoized write context should not complete a mission that still needs repeat_message."""
        with tempfile.TemporaryDirectory() as tmp:
            orch = _make_orchestrator(tmp)
            state = _base_state(["Task 5: Fibonacci with Analysis"])
            state["mission_reports"] = [
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
            ]
            state["pending_action"] = {
                "action": "tool",
                "tool_name": "write_file",
                "args": {"path": "fib50.txt", "content": "cached"},
            }

            orch._mark_next_mission_complete_from_memo_hit(
                state=state,
                memo_hit={"found": True, "key": "write_file:fib50.txt", "namespace": "run"},
            )
            self.assertEqual(state["mission_reports"][0]["status"], "in_progress")
            self.assertEqual(state["completed_tasks"], [])
            self.assertIn("write_file", state["mission_reports"][0]["used_tools"])
            self.assertIn("fib50.txt", state["mission_reports"][0]["written_files"])

            orch._record_mission_tool_event(
                state,
                "repeat_message",
                {"echo": "All 5 tasks completed successfully"},
                mission_index=0,
                tool_args={"message": "All 5 tasks completed successfully"},
            )
            self.assertEqual(state["mission_reports"][0]["status"], "completed")
            self.assertEqual(state["completed_tasks"], ["Task 5: Fibonacci with Analysis"])


if __name__ == "__main__":
    unittest.main()
