"""Tests for specialist directive configs and routing integration."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest

from agentic_workflows.orchestration.langgraph import directives
from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore
from agentic_workflows.orchestration.langgraph.tools_registry import build_tool_registry

if importlib.util.find_spec("langgraph") is None:  # pragma: no cover
    LANGGRAPH_AVAILABLE = False
else:
    LANGGRAPH_AVAILABLE = True
    from agentic_workflows.orchestration.langgraph.checkpoint_store import SQLiteCheckpointStore
    from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
    from agentic_workflows.orchestration.langgraph.policy import MemoizationPolicy
    from agentic_workflows.orchestration.langgraph.state_schema import new_run_state


class DummyProvider:
    def generate(self, messages, response_schema=None):  # noqa: ANN001
        return '{"action":"finish","answer":"done"}'


class TestDirectiveConfigs(unittest.TestCase):
    def test_directive_markdown_files_exist(self) -> None:
        for config in directives.DIRECTIVE_BY_SPECIALIST.values():
            self.assertTrue(config.markdown_path.exists())
            self.assertTrue(bool(config.load_markdown().strip()))

    def test_evaluator_scope_excludes_write_tools(self) -> None:
        self.assertIn("retrieve_memo", directives.EVALUATOR_DIRECTIVE.allowed_tools)
        self.assertNotIn("write_file", directives.EVALUATOR_DIRECTIVE.allowed_tools)
        self.assertNotIn("memoize", directives.EVALUATOR_DIRECTIVE.allowed_tools)

    def test_executor_scope_matches_tool_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from agentic_workflows.orchestration.langgraph.checkpoint_store import (
                SQLiteCheckpointStore,
            )

            registry = build_tool_registry(
                SQLiteMemoStore(f"{tmp}/memo.db"),
                checkpoint_store=SQLiteCheckpointStore(f"{tmp}/cp.db"),
            )
            self.assertEqual(set(registry.keys()), set(directives.EXECUTOR_TOOLS))


@unittest.skipUnless(LANGGRAPH_AVAILABLE, "langgraph not installed")
class TestSpecialistRouting(unittest.TestCase):
    def _make_orchestrator(self, tmp: str) -> LangGraphOrchestrator:
        return LangGraphOrchestrator(
            provider=DummyProvider(),
            memo_store=SQLiteMemoStore(f"{tmp}/memo.db"),
            checkpoint_store=SQLiteCheckpointStore(f"{tmp}/cp.db"),
            policy=MemoizationPolicy(max_policy_retries=1),
        )

    def test_route_to_evaluator_for_read_only_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch = self._make_orchestrator(tmp)
            state = new_run_state("sys", "user")
            state["pending_action"] = {
                "action": "tool",
                "tool_name": "text_analysis",
                "args": {"text": "alpha beta", "operation": "word_count"},
            }
            state = orch._route_to_specialist(state)
            self.assertEqual(state["active_specialist"], "evaluator")
            self.assertEqual(len(state["handoff_queue"]), 1)
            self.assertEqual(len(state["handoff_results"]), 1)

    def test_route_to_executor_for_write_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch = self._make_orchestrator(tmp)
            state = new_run_state("sys", "user")
            state["pending_action"] = {
                "action": "tool",
                "tool_name": "write_file",
                "args": {"path": f"{tmp}/out.txt", "content": "hello"},
            }
            state = orch._route_to_specialist(state)
            self.assertEqual(state["active_specialist"], "executor")
            self.assertEqual(len(state["handoff_queue"]), 1)
            self.assertEqual(len(state["handoff_results"]), 1)

    def test_scope_enforcement_blocks_disallowed_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch = self._make_orchestrator(tmp)
            state = new_run_state("sys", "user")
            state["active_specialist"] = "evaluator"
            state["pending_action"] = {
                "action": "tool",
                "tool_name": "write_file",
                "args": {"path": f"{tmp}/blocked.txt", "content": "blocked"},
            }
            state = orch._execute_action(state)
            self.assertEqual(state["tool_history"], [])
            self.assertIsNone(state["pending_action"])
            self.assertIn("not allowed for specialist", state["messages"][-1]["content"])

    def test_normalize_tool_args_shim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch = self._make_orchestrator(tmp)
            normalized = orch._normalize_tool_args(
                "write_file",
                {"file_path": "a.txt", "text": "payload"},
            )
            self.assertEqual(normalized["path"], "a.txt")
            self.assertEqual(normalized["content"], "payload")


if __name__ == "__main__":
    unittest.main()
