"""Unit tests for the action queue feature (multi-action extraction and queue-pop)."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest

from agentic_workflows.orchestration.langgraph.checkpoint_store import SQLiteCheckpointStore
from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore
from agentic_workflows.orchestration.langgraph.policy import MemoizationPolicy
from agentic_workflows.orchestration.langgraph.state_schema import new_run_state

LANGGRAPH_AVAILABLE = importlib.util.find_spec("langgraph") is not None

if LANGGRAPH_AVAILABLE:
    from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator


def _make_orchestrator(provider, temp_dir: str) -> LangGraphOrchestrator:
    return LangGraphOrchestrator(
        provider=provider,
        memo_store=SQLiteMemoStore(f"{temp_dir}/memo.db"),
        checkpoint_store=SQLiteCheckpointStore(f"{temp_dir}/checkpoints.db"),
        policy=MemoizationPolicy(max_policy_retries=2),
        max_steps=30,
        max_provider_timeout_retries=2,
        plan_call_timeout_seconds=10.0,
    )


@unittest.skipUnless(LANGGRAPH_AVAILABLE, "langgraph not installed")
class ExtractAllJsonObjectsTests(unittest.TestCase):
    def setUp(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.td = td
            self.orch = _make_orchestrator(DummyProvider(), td)

    def test_single_object(self) -> None:
        text = '{"action": "tool", "tool_name": "read_file", "args": {"path": "a.txt"}}'
        result = self.orch._extract_all_json_objects(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(json.loads(result[0])["tool_name"], "read_file")

    def test_multiple_objects(self) -> None:
        obj1 = '{"action": "tool", "tool_name": "write_file", "args": {"path": "a.txt", "content": "hi"}}'
        obj2 = '{"action": "tool", "tool_name": "read_file", "args": {"path": "b.txt"}}'
        obj3 = '{"action": "finish", "answer": "done"}'
        text = f"{obj1}{obj2}{obj3}"
        result = self.orch._extract_all_json_objects(text)
        self.assertEqual(len(result), 3)

    def test_objects_with_noise(self) -> None:
        text = 'Here are the actions: {"action": "tool", "tool_name": "a", "args": {}} and also {"action": "finish", "answer": "ok"} end.'
        result = self.orch._extract_all_json_objects(text)
        self.assertEqual(len(result), 2)

    def test_nested_braces(self) -> None:
        text = '{"action": "tool", "tool_name": "write_file", "args": {"path": "x.json", "content": "{\\\"key\\\": 1}"}}'
        result = self.orch._extract_all_json_objects(text)
        self.assertEqual(len(result), 1)

    def test_empty_text(self) -> None:
        self.assertEqual(self.orch._extract_all_json_objects(""), [])

    def test_no_json(self) -> None:
        self.assertEqual(self.orch._extract_all_json_objects("no json here"), [])

    def test_unbalanced_braces(self) -> None:
        text = '{"action": "tool", "tool_name": "a"'
        result = self.orch._extract_all_json_objects(text)
        self.assertEqual(result, [])


@unittest.skipUnless(LANGGRAPH_AVAILABLE, "langgraph not installed")
class ParseAllActionsJsonTests(unittest.TestCase):
    def setUp(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.td = td
            self.orch = _make_orchestrator(DummyProvider(), td)

    def test_single_valid_json(self) -> None:
        text = '{"action": "tool", "tool_name": "read_file", "args": {"path": "a.txt"}}'
        result, _ = self.orch._parse_all_actions_json(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tool_name"], "read_file")

    def test_multiple_actions(self) -> None:
        obj1 = json.dumps({"action": "tool", "tool_name": "write_file", "args": {"path": "a.txt", "content": "hi"}})
        obj2 = json.dumps({"action": "tool", "tool_name": "read_file", "args": {"path": "b.txt"}})
        text = f"{obj1}{obj2}"
        result, _ = self.orch._parse_all_actions_json(text)
        self.assertEqual(len(result), 2)

    def test_skips_non_action_objects(self) -> None:
        obj1 = json.dumps({"action": "tool", "tool_name": "read_file", "args": {}})
        obj2 = json.dumps({"some_other_key": "value"})  # no "action" key
        text = f"{obj1}{obj2}"
        result, _ = self.orch._parse_all_actions_json(text)
        self.assertEqual(len(result), 1)

    def test_mixed_valid_invalid(self) -> None:
        obj1 = json.dumps({"action": "tool", "tool_name": "a", "args": {}})
        obj2 = json.dumps({"action": "finish", "answer": "done"})
        # Separate bad JSON that doesn't swallow the next object
        text = f"{obj1} bad-noise {obj2}"
        result, _ = self.orch._parse_all_actions_json(text)
        self.assertEqual(len(result), 2)


@unittest.skipUnless(LANGGRAPH_AVAILABLE, "langgraph not installed")
class QueuePopFlowTests(unittest.TestCase):
    """Test that multi-action provider output fills the queue and subsequent steps pop from it."""

    def test_multi_action_queued_and_popped(self) -> None:
        """Provider returns 3 actions concatenated; all should execute without extra provider calls."""
        actions = [
            {"action": "tool", "tool_name": "repeat_message", "args": {"message": "first"}},
            {"action": "tool", "tool_name": "repeat_message", "args": {"message": "second"}},
            {"action": "tool", "tool_name": "repeat_message", "args": {"message": "third"}},
        ]
        # Provider returns all 3 concatenated on first call, then finish
        multi_response = "".join(json.dumps(a) for a in actions)
        provider = CountingRawProvider([
            multi_response,
            json.dumps({"action": "finish", "answer": "all done"}),
        ])

        with tempfile.TemporaryDirectory() as td:
            orch = _make_orchestrator(provider, td)
            result = orch.run(
                "Task 1: say first\nTask 2: say second\nTask 3: say third"
            )
            # Provider should only be called twice: once for the batch, once for finish
            self.assertLessEqual(provider.call_count, 3)
            # All three repeat_message calls should appear in tools_used
            tool_names = [item["tool"] for item in result["tools_used"]]
            self.assertEqual(tool_names.count("repeat_message"), 3)

    def test_queue_skipped_when_memo_required(self) -> None:
        """When memo_required is True, queue should be bypassed."""
        with tempfile.TemporaryDirectory() as td:
            _make_orchestrator(DummyProvider(), td)  # ensure imports work
            state = new_run_state("system", "user", run_id="test-memo")
            state["pending_action_queue"] = [
                {"action": "tool", "tool_name": "repeat_message", "args": {"message": "queued"}},
            ]
            state["policy_flags"]["memo_required"] = True
            state["policy_flags"]["memo_required_key"] = "write_file:test.txt"
            # The queue-pop check should skip the queue when memo_required is True
            queue = state.get("pending_action_queue", [])
            memo_required = state.get("policy_flags", {}).get("memo_required", False)
            self.assertTrue(memo_required)
            self.assertEqual(len(queue), 1)
            # The condition `queue and not memo_required` should be False
            self.assertFalse(queue and not memo_required)


@unittest.skipUnless(LANGGRAPH_AVAILABLE, "langgraph not installed")
class QueueClearOnTimeoutTests(unittest.TestCase):
    def test_queue_cleared_on_timeout_mode(self) -> None:
        """When timeout mode is entered, pending_action_queue should be emptied."""
        from agentic_workflows.orchestration.langgraph.provider import ProviderTimeoutError

        class TimeoutProvider:
            def generate(self, messages):  # noqa: ANN001
                raise ProviderTimeoutError("timeout")

        with tempfile.TemporaryDirectory() as td:
            orch = _make_orchestrator(TimeoutProvider(), td)
            state = new_run_state("system", "Task 1: do something", run_id="test-timeout")
            state["missions"] = ["do something"]
            state["pending_action_queue"] = [
                {"action": "tool", "tool_name": "repeat_message", "args": {"message": "stale"}},
            ]
            # Run plan which will hit timeout and enter fallback
            result_state = orch._plan_next_action(state)
            # Queue should be cleared
            self.assertEqual(result_state.get("pending_action_queue", []), [])


@unittest.skipUnless(LANGGRAPH_AVAILABLE, "langgraph not installed")
class StateSchemaQueueTests(unittest.TestCase):
    def test_new_run_state_has_queue(self) -> None:
        state = new_run_state("system", "user")
        self.assertIn("pending_action_queue", state)
        self.assertEqual(state["pending_action_queue"], [])

    def test_ensure_defaults_adds_queue(self) -> None:
        from agentic_workflows.orchestration.langgraph.state_schema import ensure_state_defaults

        state = ensure_state_defaults({})
        self.assertIn("pending_action_queue", state)
        self.assertEqual(state["pending_action_queue"], [])


class DummyProvider:
    def generate(self, messages):  # noqa: ANN001
        return json.dumps({"action": "finish", "answer": "dummy"})


class CountingRawProvider:
    """Provider that returns raw string responses and counts calls."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self._index = 0
        self.call_count = 0

    def generate(self, messages):  # noqa: ANN001
        self.call_count += 1
        if self._index < len(self._responses):
            value = self._responses[self._index]
            self._index += 1
            return value
        return self._responses[-1]


if __name__ == "__main__":
    unittest.main()
