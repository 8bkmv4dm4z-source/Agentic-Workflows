"""Unit tests for handoff schema and routing logic."""
from __future__ import annotations

import unittest

from agentic_workflows.orchestration.langgraph.handoff import (
    create_handoff,
    create_handoff_result,
)
from agentic_workflows.orchestration.langgraph.state_schema import (
    ensure_state_defaults,
    new_run_state,
)


class TestTaskHandoff(unittest.TestCase):
    def test_create_handoff_defaults(self) -> None:
        h = create_handoff(task_id="t1", specialist="executor", mission_id=1)
        self.assertEqual(h["task_id"], "t1")
        self.assertEqual(h["specialist"], "executor")
        self.assertEqual(h["mission_id"], 1)
        self.assertEqual(h["tool_scope"], [])
        self.assertEqual(h["input_context"], {})
        self.assertEqual(h["token_budget"], 4096)

    def test_create_handoff_custom(self) -> None:
        h = create_handoff(
            task_id="t2",
            specialist="evaluator",
            mission_id=3,
            tool_scope=["text_analysis", "regex_matcher"],
            input_context={"mission_text": "Analyze text"},
            token_budget=2048,
        )
        self.assertEqual(h["specialist"], "evaluator")
        self.assertEqual(h["tool_scope"], ["text_analysis", "regex_matcher"])
        self.assertEqual(h["token_budget"], 2048)

    def test_handoff_is_dict(self) -> None:
        h = create_handoff(task_id="t1", specialist="supervisor", mission_id=1)
        self.assertIsInstance(h, dict)
        self.assertIn("task_id", h)


class TestHandoffResult(unittest.TestCase):
    def test_create_result_defaults(self) -> None:
        r = create_handoff_result(task_id="t1", specialist="executor")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["output"], {})
        self.assertEqual(r["tokens_used"], 0)

    def test_create_result_error(self) -> None:
        r = create_handoff_result(
            task_id="t1",
            specialist="executor",
            status="error",
            output={"error": "tool not found"},
            tokens_used=150,
        )
        self.assertEqual(r["status"], "error")
        self.assertIn("error", r["output"])
        self.assertEqual(r["tokens_used"], 150)

    def test_create_result_timeout(self) -> None:
        r = create_handoff_result(task_id="t1", specialist="supervisor", status="timeout")
        self.assertEqual(r["status"], "timeout")


class TestStateSchemaHandoffFields(unittest.TestCase):
    def test_new_run_state_has_handoff_fields(self) -> None:
        state = new_run_state("sys", "user")
        self.assertEqual(state["handoff_queue"], [])
        self.assertEqual(state["handoff_results"], [])
        self.assertEqual(state["active_specialist"], "supervisor")

    def test_new_run_state_has_token_budget(self) -> None:
        state = new_run_state("sys", "user")
        self.assertEqual(state["token_budget_remaining"], 100_000)
        self.assertEqual(state["token_budget_used"], 0)

    def test_ensure_defaults_backfills_handoff(self) -> None:
        state = {"run_id": "test", "messages": []}
        repaired = ensure_state_defaults(state)
        self.assertEqual(repaired["handoff_queue"], [])
        self.assertEqual(repaired["handoff_results"], [])
        self.assertEqual(repaired["active_specialist"], "supervisor")
        self.assertEqual(repaired["token_budget_remaining"], 100_000)
        self.assertEqual(repaired["token_budget_used"], 0)

    def test_ensure_defaults_preserves_existing(self) -> None:
        state = {
            "run_id": "test",
            "messages": [],
            "handoff_queue": [{"task_id": "t1"}],
            "active_specialist": "evaluator",
            "token_budget_remaining": 5000,
            "token_budget_used": 95000,
        }
        repaired = ensure_state_defaults(state)
        self.assertEqual(len(repaired["handoff_queue"]), 1)
        self.assertEqual(repaired["active_specialist"], "evaluator")
        self.assertEqual(repaired["token_budget_remaining"], 5000)
        self.assertEqual(repaired["token_budget_used"], 95000)


class TestHandoffRouting(unittest.TestCase):
    def test_handoff_queue_serializable(self) -> None:
        """TaskHandoff dicts can be stored in state handoff_queue."""
        state = new_run_state("sys", "user")
        h = create_handoff(task_id="t1", specialist="executor", mission_id=1)
        state["handoff_queue"].append(h)
        self.assertEqual(len(state["handoff_queue"]), 1)
        self.assertEqual(state["handoff_queue"][0]["specialist"], "executor")

    def test_handoff_result_stored(self) -> None:
        state = new_run_state("sys", "user")
        r = create_handoff_result(
            task_id="t1", specialist="executor", output={"sorted": [1, 2, 3]}
        )
        state["handoff_results"].append(r)
        self.assertEqual(len(state["handoff_results"]), 1)
        self.assertEqual(state["handoff_results"][0]["status"], "success")


if __name__ == "__main__":
    unittest.main()
