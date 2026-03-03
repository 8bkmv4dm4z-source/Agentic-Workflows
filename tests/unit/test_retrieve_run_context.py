"""Tests for retrieve_run_context tool and checkpoint store enhancements."""

import tempfile
import unittest

from agentic_workflows.orchestration.langgraph.checkpoint_store import SQLiteCheckpointStore
from agentic_workflows.tools.retrieve_run_context import RetrieveRunContextTool


def _make_state(run_id: str = "run-1", answer: str = "done") -> dict:
    return {
        "run_id": run_id,
        "final_answer": answer,
        "tool_history": [
            {"tool": "sort_array", "args": {"items": [3, 1, 2]}, "result": {"sorted": [1, 2, 3]}},
            {"tool": "write_file", "args": {"path": "out.txt"}, "result": {"result": "ok"}},
        ],
        "mission_reports": [
            {"mission_id": 1, "mission": "Sort numbers", "used_tools": ["sort_array"], "result": "sorted"},
        ],
        "audit_report": {"passed": 3, "failed": 1, "score": 75},
    }


class TestCheckpointStoreEnhancements(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self.store = SQLiteCheckpointStore(f"{self._tmp}/cp.db")

    def test_list_runs_empty(self) -> None:
        runs = self.store.list_runs()
        self.assertEqual(runs, [])

    def test_list_runs(self) -> None:
        self.store.save(run_id="run-1", step=0, node_name="plan", state=_make_state("run-1"))
        self.store.save(run_id="run-2", step=0, node_name="plan", state=_make_state("run-2"))
        runs = self.store.list_runs()
        self.assertEqual(len(runs), 2)
        # Most recent first
        self.assertEqual(runs[0]["run_id"], "run-2")

    def test_load_latest_run_empty(self) -> None:
        result = self.store.load_latest_run()
        self.assertIsNone(result)

    def test_load_latest_run(self) -> None:
        self.store.save(run_id="run-1", step=0, node_name="plan", state=_make_state("run-1"))
        self.store.save(run_id="run-2", step=0, node_name="plan", state=_make_state("run-2"))
        state = self.store.load_latest_run()
        self.assertIsNotNone(state)
        self.assertEqual(state["run_id"], "run-2")

    def test_list_runs_limit(self) -> None:
        for i in range(5):
            self.store.save(run_id=f"run-{i}", step=0, node_name="plan", state=_make_state(f"run-{i}"))
        runs = self.store.list_runs(limit=3)
        self.assertEqual(len(runs), 3)


class TestRetrieveRunContextTool(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self.store = SQLiteCheckpointStore(f"{self._tmp}/cp.db")
        self.tool = RetrieveRunContextTool(self.store)

    def test_last_run_empty(self) -> None:
        result = self.tool.execute({"operation": "last_run"})
        self.assertIn("error", result)

    def test_last_run(self) -> None:
        self.store.save(run_id="run-1", step=0, node_name="finalize", state=_make_state())
        result = self.tool.execute({"operation": "last_run"})
        self.assertEqual(result["run_id"], "run-1")
        self.assertEqual(result["answer"], "done")
        self.assertIn("tools_used", result)
        self.assertIn("missions_completed", result)

    def test_get_run(self) -> None:
        self.store.save(run_id="run-1", step=0, node_name="plan", state=_make_state())
        result = self.tool.execute({"operation": "get_run", "run_id": "run-1"})
        self.assertEqual(result["run_id"], "run-1")

    def test_get_run_missing(self) -> None:
        result = self.tool.execute({"operation": "get_run", "run_id": "nonexistent"})
        self.assertIn("error", result)

    def test_get_run_requires_id(self) -> None:
        result = self.tool.execute({"operation": "get_run"})
        self.assertIn("error", result)

    def test_list_runs(self) -> None:
        for i in range(3):
            self.store.save(run_id=f"run-{i}", step=0, node_name="plan", state=_make_state(f"run-{i}"))
        result = self.tool.execute({"operation": "list_runs"})
        self.assertEqual(result["count"], 3)

    def test_get_summary(self) -> None:
        self.store.save(run_id="run-1", step=0, node_name="finalize", state=_make_state())
        result = self.tool.execute({"operation": "get_summary"})
        self.assertEqual(result["run_id"], "run-1")
        self.assertIn("missions", result)
        self.assertIn("tools_used", result)

    def test_include_filter(self) -> None:
        self.store.save(run_id="run-1", step=0, node_name="finalize", state=_make_state())
        result = self.tool.execute({"operation": "last_run", "include": ["answer"]})
        self.assertIn("answer", result)
        self.assertNotIn("tools_used", result)

    def test_missing_operation(self) -> None:
        result = self.tool.execute({})
        self.assertIn("error", result)

    def test_invalid_operation(self) -> None:
        result = self.tool.execute({"operation": "unknown_op"})
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
