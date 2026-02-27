import importlib.util
import json
import tempfile
import unittest

from execution.langgraph.checkpoint_store import SQLiteCheckpointStore
from execution.langgraph.memo_store import SQLiteMemoStore
from execution.langgraph.policy import MemoizationPolicy

if importlib.util.find_spec("langgraph") is None:  # pragma: no cover
    LANGGRAPH_AVAILABLE = False
else:
    LANGGRAPH_AVAILABLE = True
    from execution.langgraph.graph import LangGraphOrchestrator, MemoizationPolicyViolation


class ScriptedProvider:
    def __init__(self, responses: list[dict]) -> None:
        self._responses = [json.dumps(item) for item in responses]
        self._index = 0

    def generate(self, messages):  # noqa: ANN001
        if self._index < len(self._responses):
            value = self._responses[self._index]
            self._index += 1
            return value
        return self._responses[-1]


class InvalidJSONProvider:
    def generate(self, messages):  # noqa: ANN001
        return "not-json"


class RawScriptedProvider:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self._index = 0

    def generate(self, messages):  # noqa: ANN001
        if self._index < len(self._responses):
            value = self._responses[self._index]
            self._index += 1
            return value
        return self._responses[-1]


class ModelNotFoundProvider:
    def generate(self, messages):  # noqa: ANN001
        raise RuntimeError(
            "Error code: 404 - {'error': {'message': \"model 'qwen3:8b' not found\"}}"
        )


def fibonacci_csv(count: int = 100) -> str:
    numbers = [0, 1]
    while len(numbers) < count:
        numbers.append(numbers[-1] + numbers[-2])
    return ", ".join(str(n) for n in numbers)


@unittest.skipUnless(LANGGRAPH_AVAILABLE, "langgraph not installed")
class LangGraphFlowTests(unittest.TestCase):
    def test_model_not_found_fails_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            orchestrator = LangGraphOrchestrator(
                provider=ModelNotFoundProvider(),
                memo_store=SQLiteMemoStore(f"{temp_dir}/memo.db"),
                checkpoint_store=SQLiteCheckpointStore(f"{temp_dir}/checkpoints.db"),
                policy=MemoizationPolicy(max_policy_retries=1),
                max_steps=40,
                max_invalid_plan_retries=8,
            )
            result = orchestrator.run("use missing model")
            self.assertIn("unrecoverable provider error", result["answer"].lower())
            self.assertEqual(result["state"]["retry_counts"]["invalid_json"], 1)

    def test_invalid_plan_retries_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            orchestrator = LangGraphOrchestrator(
                provider=InvalidJSONProvider(),
                memo_store=SQLiteMemoStore(f"{temp_dir}/memo.db"),
                checkpoint_store=SQLiteCheckpointStore(f"{temp_dir}/checkpoints.db"),
                policy=MemoizationPolicy(max_policy_retries=1),
                max_steps=40,
                max_invalid_plan_retries=3,
            )
            result = orchestrator.run("return valid actions")
            self.assertIn("failed to produce a valid json action", result["answer"].lower())
            self.assertEqual(result["state"]["retry_counts"]["invalid_json"], 3)

    def test_soft_retry_then_memoize(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = f"{temp_dir}/fib.txt"
            memo_store = SQLiteMemoStore(f"{temp_dir}/memo.db")
            checkpoint_store = SQLiteCheckpointStore(f"{temp_dir}/checkpoints.db")
            provider = ScriptedProvider(
                [
                    {
                        "action": "tool",
                        "tool_name": "write_file",
                        "args": {"path": output_path, "content": ",".join(str(i) for i in range(200))},
                    },
                    {
                        "action": "tool",
                        "tool_name": "sort_array",
                        "args": {"items": [3, 1], "order": "asc"},
                    },
                    {
                        "action": "tool",
                        "tool_name": "memoize",
                        "args": {
                            "key": f"write_file:{output_path}",
                            "value": {"path": output_path, "source": "test"},
                            "source_tool": "write_file",
                        },
                    },
                    {"action": "finish", "answer": "done"},
                ]
            )
            orchestrator = LangGraphOrchestrator(
                provider=provider,
                memo_store=memo_store,
                checkpoint_store=checkpoint_store,
                policy=MemoizationPolicy(max_policy_retries=2),
                max_steps=30,
            )
            result = orchestrator.run("run test")

            executed_tools = [item["tool"] for item in result["tools_used"]]
            self.assertEqual(executed_tools, ["write_file", "memoize"])
            self.assertEqual(result["answer"], "done")
            self.assertEqual(result["derived_snapshot"]["memo_entry_count"], 1)
            self.assertIn("write_file", result["mission_report"][0]["used_tools"])
            self.assertIn("memoize", result["mission_report"][0]["used_tools"])
            lookup = memo_store.get(
                run_id=result["run_id"],
                key=f"write_file:{output_path}",
                namespace="run",
            )
            self.assertTrue(lookup.found)
            self.assertGreater(len(result["checkpoints"]), 0)

    def test_policy_violation_after_retries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = f"{temp_dir}/fib.txt"
            provider = ScriptedProvider(
                [
                    {
                        "action": "tool",
                        "tool_name": "write_file",
                        "args": {"path": output_path, "content": ",".join(str(i) for i in range(200))},
                    },
                    {"action": "tool", "tool_name": "sort_array", "args": {"items": [2, 1], "order": "asc"}},
                    {"action": "tool", "tool_name": "sort_array", "args": {"items": [9, 8], "order": "asc"}},
                ]
            )
            orchestrator = LangGraphOrchestrator(
                provider=provider,
                memo_store=SQLiteMemoStore(f"{temp_dir}/memo.db"),
                checkpoint_store=SQLiteCheckpointStore(f"{temp_dir}/checkpoints.db"),
                policy=MemoizationPolicy(max_policy_retries=1),
                max_steps=20,
            )
            with self.assertRaises(MemoizationPolicyViolation):
                orchestrator.run("run test")

    def test_duplicate_tool_call_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = ScriptedProvider(
                [
                    {"action": "tool", "tool_name": "sort_array", "args": {"items": [3, 2, 1], "order": "asc"}},
                    {"action": "tool", "tool_name": "sort_array", "args": {"items": [3, 2, 1], "order": "asc"}},
                    {"action": "finish", "answer": "done"},
                ]
            )
            orchestrator = LangGraphOrchestrator(
                provider=provider,
                memo_store=SQLiteMemoStore(f"{temp_dir}/memo.db"),
                checkpoint_store=SQLiteCheckpointStore(f"{temp_dir}/checkpoints.db"),
                policy=MemoizationPolicy(max_policy_retries=1),
                max_steps=20,
            )
            result = orchestrator.run("duplicate test")
            executed_tools = [item["tool"] for item in result["tools_used"]]
            self.assertEqual(executed_tools, ["sort_array"])
            self.assertEqual(result["state"]["retry_counts"]["duplicate_tool"], 1)
            self.assertEqual(result["derived_snapshot"]["duplicate_tool_retries"], 1)

    def test_sort_array_alias_array_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = ScriptedProvider(
                [
                    {"action": "tool", "tool_name": "sort_array", "args": {"array": [5, 2, 8, 1]}},
                    {"action": "finish", "answer": "done"},
                ]
            )
            orchestrator = LangGraphOrchestrator(
                provider=provider,
                memo_store=SQLiteMemoStore(f"{temp_dir}/memo.db"),
                checkpoint_store=SQLiteCheckpointStore(f"{temp_dir}/checkpoints.db"),
                policy=MemoizationPolicy(max_policy_retries=1),
                max_steps=20,
            )
            result = orchestrator.run("Task 1: sort these numbers")
            first_call = result["tools_used"][0]
            self.assertEqual(first_call["tool"], "sort_array")
            self.assertEqual(first_call["args"]["items"], [5, 2, 8, 1])
            self.assertEqual(first_call["result"]["sorted"], [1, 2, 5, 8])
            self.assertEqual(result["state"]["completed_tasks"], ["Task 1: sort these numbers"])

    def test_multiple_json_objects_recover_first_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = RawScriptedProvider(
                [
                    '{"action":"tool","tool_name":"repeat_message","args":{"message":"ok"}}'
                    '{"action":"tool","tool_name":"sort_array","args":{"items":[2,1]}}',
                    '{"action":"finish","answer":"done"}',
                ]
            )
            orchestrator = LangGraphOrchestrator(
                provider=provider,
                memo_store=SQLiteMemoStore(f"{temp_dir}/memo.db"),
                checkpoint_store=SQLiteCheckpointStore(f"{temp_dir}/checkpoints.db"),
                policy=MemoizationPolicy(max_policy_retries=1),
                max_steps=20,
            )
            result = orchestrator.run("Task 1: repeat")
            self.assertEqual([item["tool"] for item in result["tools_used"]], ["repeat_message"])
            self.assertEqual(result["state"]["retry_counts"]["invalid_json"], 0)

    def test_duplicate_after_completion_auto_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = ScriptedProvider(
                [
                    {"action": "tool", "tool_name": "repeat_message", "args": {"message": "ok"}},
                    {"action": "tool", "tool_name": "repeat_message", "args": {"message": "ok"}},
                ]
            )
            orchestrator = LangGraphOrchestrator(
                provider=provider,
                memo_store=SQLiteMemoStore(f"{temp_dir}/memo.db"),
                checkpoint_store=SQLiteCheckpointStore(f"{temp_dir}/checkpoints.db"),
                policy=MemoizationPolicy(max_policy_retries=1),
                max_steps=20,
            )
            result = orchestrator.run("Task 1: repeat")
            self.assertEqual([item["tool"] for item in result["tools_used"]], ["repeat_message"])
            self.assertIn("All tasks completed.", result["answer"])

    def test_fibonacci_validation_retry_then_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = f"{temp_dir}/fib.txt"
            provider = ScriptedProvider(
                [
                    {
                        "action": "tool",
                        "tool_name": "write_file",
                        "args": {"path": output_path, "content": "0, 1, 1, 2, 3, 5, 110, 114, 118"},
                    },
                    {
                        "action": "tool",
                        "tool_name": "write_file",
                        "args": {"path": output_path, "content": fibonacci_csv(100)},
                    },
                    {
                        "action": "tool",
                        "tool_name": "memoize",
                        "args": {
                            "key": f"write_file:{output_path}",
                            "value": {"source": "test"},
                            "source_tool": "write_file",
                        },
                    },
                    {"action": "finish", "answer": "done"},
                ]
            )
            orchestrator = LangGraphOrchestrator(
                provider=provider,
                memo_store=SQLiteMemoStore(f"{temp_dir}/memo.db"),
                checkpoint_store=SQLiteCheckpointStore(f"{temp_dir}/checkpoints.db"),
                policy=MemoizationPolicy(max_policy_retries=2),
                max_steps=30,
            )
            result = orchestrator.run(
                "Task 1: Use write_file tool to write the fibonacci sequence until the 100th number to fib.txt"
            )
            self.assertEqual(result["answer"], "done")
            self.assertEqual(result["state"]["retry_counts"]["content_validation"], 1)
            tools = [item["tool"] for item in result["tools_used"]]
            self.assertEqual(tools, ["write_file", "write_file", "memoize"])
            self.assertIn("error", result["tools_used"][0]["result"])
            self.assertEqual(result["derived_snapshot"]["content_validation_retries"], 1)

    def test_fibonacci_validation_fail_closed_after_retries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = f"{temp_dir}/fib.txt"
            provider = ScriptedProvider(
                [
                    {
                        "action": "tool",
                        "tool_name": "write_file",
                        "args": {"path": output_path, "content": "0, 1, 1, 2, 3, 5, 110"},
                    },
                    {
                        "action": "tool",
                        "tool_name": "write_file",
                        "args": {"path": output_path, "content": "0, 1, 1, 2, 3, 5, 114"},
                    },
                ]
            )
            orchestrator = LangGraphOrchestrator(
                provider=provider,
                memo_store=SQLiteMemoStore(f"{temp_dir}/memo.db"),
                checkpoint_store=SQLiteCheckpointStore(f"{temp_dir}/checkpoints.db"),
                policy=MemoizationPolicy(max_policy_retries=1),
                max_steps=20,
                max_content_validation_retries=1,
            )
            result = orchestrator.run(
                "Task 1: Use write_file tool to write the fibonacci sequence until the 100th number to fib.txt"
            )
            self.assertIn("failed closed", result["answer"].lower())
            self.assertEqual(result["state"]["retry_counts"]["content_validation"], 2)


if __name__ == "__main__":
    unittest.main()
