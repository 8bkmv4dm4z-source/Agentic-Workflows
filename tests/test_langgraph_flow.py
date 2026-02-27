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


@unittest.skipUnless(LANGGRAPH_AVAILABLE, "langgraph not installed")
class LangGraphFlowTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
