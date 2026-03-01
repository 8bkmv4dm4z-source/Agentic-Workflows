import importlib.util
import json
import os
import tempfile
import time
import unittest

from agentic_workflows.orchestration.langgraph.checkpoint_store import SQLiteCheckpointStore
from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore
from agentic_workflows.orchestration.langgraph.policy import MemoizationPolicy

if importlib.util.find_spec("langgraph") is None:  # pragma: no cover
    LANGGRAPH_AVAILABLE = False
else:
    LANGGRAPH_AVAILABLE = True
    from agentic_workflows.orchestration.langgraph.graph import (
        LangGraphOrchestrator,
        MemoizationPolicyViolation,
    )


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
    def test_hard_timeout_handles_blocking_provider(self) -> None:
        class BlockingProvider:
            def generate(self, messages):  # noqa: ANN001
                time.sleep(0.2)
                return json.dumps({"action": "finish", "answer": "late"})

        with tempfile.TemporaryDirectory() as temp_dir:
            orchestrator = LangGraphOrchestrator(
                provider=BlockingProvider(),
                memo_store=SQLiteMemoStore(f"{temp_dir}/memo.db"),
                checkpoint_store=SQLiteCheckpointStore(f"{temp_dir}/checkpoints.db"),
                policy=MemoizationPolicy(max_policy_retries=1),
                max_steps=20,
                max_provider_timeout_retries=1,
                plan_call_timeout_seconds=0.05,
            )
            started = time.monotonic()
            result = orchestrator.run("Task 1: perform unknown operation now")
            elapsed = time.monotonic() - started
            self.assertIn("provider timeout retries", result["answer"].lower())
            self.assertEqual(result["state"]["retry_counts"]["provider_timeout"], 1)
            self.assertEqual(result["state"]["retry_counts"]["invalid_json"], 0)
            self.assertEqual(result["tools_used"], [])
            self.assertLess(elapsed, 0.18)

    def test_provider_timeout_retry_then_success(self) -> None:
        from agentic_workflows.orchestration.langgraph.provider import ProviderTimeoutError

        class TimeoutThenSuccessProvider:
            def __init__(self) -> None:
                self.calls = 0

            def generate(self, messages):  # noqa: ANN001
                self.calls += 1
                if self.calls == 1:
                    raise ProviderTimeoutError("provider timeout after 1 attempts: read timeout")
                if self.calls == 2:
                    return json.dumps(
                        {
                            "action": "tool",
                            "tool_name": "repeat_message",
                            "args": {"message": "ok"},
                        }
                    )
                return json.dumps({"action": "finish", "answer": "done"})

        with tempfile.TemporaryDirectory() as temp_dir:
            orchestrator = LangGraphOrchestrator(
                provider=TimeoutThenSuccessProvider(),
                memo_store=SQLiteMemoStore(f"{temp_dir}/memo.db"),
                checkpoint_store=SQLiteCheckpointStore(f"{temp_dir}/checkpoints.db"),
                policy=MemoizationPolicy(max_policy_retries=1),
                max_steps=20,
                max_provider_timeout_retries=3,
            )
            result = orchestrator.run("Task 1: repeat this message")
            self.assertEqual(result["answer"], "done")
            self.assertEqual(result["state"]["retry_counts"]["provider_timeout"], 1)
            self.assertEqual(result["state"]["retry_counts"]["invalid_json"], 0)
            self.assertEqual([item["tool"] for item in result["tools_used"]], ["repeat_message"])
            self.assertEqual(result["derived_snapshot"]["provider_timeout_retries"], 1)

    def test_provider_timeout_fail_closed(self) -> None:
        from agentic_workflows.orchestration.langgraph.provider import ProviderTimeoutError

        class AlwaysTimeoutProvider:
            def generate(self, messages):  # noqa: ANN001
                raise ProviderTimeoutError("provider timeout after 1 attempts: read timeout")

        with tempfile.TemporaryDirectory() as temp_dir:
            orchestrator = LangGraphOrchestrator(
                provider=AlwaysTimeoutProvider(),
                memo_store=SQLiteMemoStore(f"{temp_dir}/memo.db"),
                checkpoint_store=SQLiteCheckpointStore(f"{temp_dir}/checkpoints.db"),
                policy=MemoizationPolicy(max_policy_retries=1),
                max_steps=20,
                max_provider_timeout_retries=2,
            )
            result = orchestrator.run("Task 1: perform unknown operation now")
            self.assertIn("provider timeout retries", result["answer"].lower())
            self.assertEqual(result["state"]["retry_counts"]["provider_timeout"], 2)
            self.assertEqual(result["state"]["retry_counts"]["invalid_json"], 0)
            self.assertEqual(result["tools_used"], [])

    def test_provider_timeout_uses_deterministic_fallback_for_fibonacci_write(self) -> None:
        from agentic_workflows.orchestration.langgraph.provider import ProviderTimeoutError

        class AlwaysTimeoutProvider:
            def generate(self, messages):  # noqa: ANN001
                raise ProviderTimeoutError("provider timeout after 1 attempts: read timeout")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = f"{temp_dir}/fib.txt"
            orchestrator = LangGraphOrchestrator(
                provider=AlwaysTimeoutProvider(),
                memo_store=SQLiteMemoStore(f"{temp_dir}/memo.db"),
                checkpoint_store=SQLiteCheckpointStore(f"{temp_dir}/checkpoints.db"),
                policy=MemoizationPolicy(max_policy_retries=2),
                max_steps=20,
                max_provider_timeout_retries=3,
            )
            result = orchestrator.run(
                f"Task 1: Use write_file tool to write the fibonacci sequence until the 100th number to {output_path}"
            )
            self.assertIn("All tasks completed.", result["answer"])
            self.assertEqual(
                [item["tool"] for item in result["tools_used"]],
                ["retrieve_memo", "retrieve_memo", "write_file", "memoize"],
            )
            self.assertEqual(result["state"]["retry_counts"]["provider_timeout"], 1)

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
                        "args": {
                            "path": output_path,
                            "content": ",".join(str(i) for i in range(200)),
                        },
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
            self.assertEqual(
                executed_tools, ["retrieve_memo", "retrieve_memo", "write_file", "memoize"]
            )
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
                        "args": {
                            "path": output_path,
                            "content": ",".join(str(i) for i in range(200)),
                        },
                    },
                    {
                        "action": "tool",
                        "tool_name": "sort_array",
                        "args": {"items": [2, 1], "order": "asc"},
                    },
                    {
                        "action": "tool",
                        "tool_name": "sort_array",
                        "args": {"items": [9, 8], "order": "asc"},
                    },
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
                    {
                        "action": "tool",
                        "tool_name": "sort_array",
                        "args": {"items": [3, 2, 1], "order": "asc"},
                    },
                    {
                        "action": "tool",
                        "tool_name": "sort_array",
                        "args": {"items": [3, 2, 1], "order": "asc"},
                    },
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

    def test_action_alias_direct_tool_name_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = RawScriptedProvider(
                [
                    '{"action":"retrieve_memo","args":{"key":"write_file:fib.txt"}}'
                    '{"action":"retrieve_memo","args":{"key":"write_file:fibonacci"}}',
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
            result = orchestrator.run("Task 1: retrieve fib memo")
            self.assertEqual([item["tool"] for item in result["tools_used"]], ["retrieve_memo"])
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
            self.assertEqual(
                tools, ["retrieve_memo", "retrieve_memo", "write_file", "write_file", "memoize"]
            )
            self.assertIn("error", result["tools_used"][2]["result"])
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

    def test_retrieve_memo_hit_is_logged_in_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memo_store = SQLiteMemoStore(f"{temp_dir}/memo.db")
            checkpoint_store = SQLiteCheckpointStore(f"{temp_dir}/checkpoints.db")
            run_id = "run-retrieve-hit"
            memo_store.put(
                run_id=run_id,
                key="fib:0:10",
                value={"sequence": [0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55]},
            )
            provider = ScriptedProvider(
                [
                    {"action": "tool", "tool_name": "retrieve_memo", "args": {"key": "fib:0:10"}},
                    {"action": "finish", "answer": "done"},
                ]
            )
            orchestrator = LangGraphOrchestrator(
                provider=provider,
                memo_store=memo_store,
                checkpoint_store=checkpoint_store,
                policy=MemoizationPolicy(max_policy_retries=1),
                max_steps=10,
            )
            result = orchestrator.run("Task 1: retrieve memo", run_id=run_id)
            self.assertEqual(result["answer"], "done")
            self.assertEqual(result["derived_snapshot"]["memo_retrieve_hits"], 1)
            self.assertEqual(result["derived_snapshot"]["memo_retrieve_misses"], 0)
            self.assertTrue(
                any(
                    event.get("source_tool") == "retrieve_memo_hit"
                    for event in result["memo_events"]
                )
            )

    def test_write_file_requires_retrieve_memo_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = f"{temp_dir}/fib.txt"
            provider = ScriptedProvider(
                [
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
                            "value": {"path": output_path, "source": "test"},
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
            self.assertEqual(
                [item["tool"] for item in result["tools_used"]],
                ["retrieve_memo", "retrieve_memo", "write_file", "memoize"],
            )

    def test_cross_run_write_cache_reuse_skips_planner_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = f"{temp_dir}/fib.txt"
            memo_store = SQLiteMemoStore(f"{temp_dir}/memo.db")
            checkpoint_store = SQLiteCheckpointStore(f"{temp_dir}/checkpoints.db")

            seed_provider = ScriptedProvider(
                [
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
                            "value": {"path": output_path, "source": "seed"},
                            "source_tool": "write_file",
                        },
                    },
                    {"action": "finish", "answer": "seed complete"},
                ]
            )
            seed_orchestrator = LangGraphOrchestrator(
                provider=seed_provider,
                memo_store=memo_store,
                checkpoint_store=checkpoint_store,
                policy=MemoizationPolicy(max_policy_retries=2),
                max_steps=20,
            )
            seed_orchestrator.run(
                f"Task 1: Use write_file tool to write the fibonacci sequence until the 100th number to {output_path}"
            )

            class CountingProvider:
                def __init__(self) -> None:
                    self.calls = 0

                def generate(self, messages):  # noqa: ANN001
                    self.calls += 1
                    return json.dumps({"action": "finish", "answer": "should not be needed"})

            provider = CountingProvider()
            orchestrator = LangGraphOrchestrator(
                provider=provider,
                memo_store=memo_store,
                checkpoint_store=checkpoint_store,
                policy=MemoizationPolicy(max_policy_retries=2),
                max_steps=20,
            )
            result = orchestrator.run(
                f"Task 1: Use write_file tool to write the fibonacci sequence until the 100th number to {output_path}"
            )

            self.assertEqual(provider.calls, 0)
            self.assertEqual([item["tool"] for item in result["tools_used"]], ["write_file"])
            self.assertEqual(result["derived_snapshot"]["cache_reuse_hits"], 1)
            self.assertIn("All tasks completed.", result["answer"])

    def test_cache_hit_keeps_followup_mission_index_alignment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memo_store = SQLiteMemoStore(f"{temp_dir}/memo.db")
            checkpoint_store = SQLiteCheckpointStore(f"{temp_dir}/checkpoints.db")
            memo_store.put(
                run_id="shared",
                key="write_file_input:fib.txt",
                value={"path": "fib.txt", "content": fibonacci_csv(100)},
                namespace="cache",
                source_tool="test",
                step=0,
            )

            provider = ScriptedProvider(
                [
                    {
                        "action": "tool",
                        "tool_name": "repeat_message",
                        "args": {"message": "Agent loop is working!"},
                    },
                    {
                        "action": "tool",
                        "tool_name": "sort_array",
                        "args": {"items": [5, 2, 8, 1, 9, 3], "order": "asc"},
                    },
                    {
                        "action": "tool",
                        "tool_name": "string_ops",
                        "args": {"text": "the quick brown fox", "operation": "uppercase"},
                    },
                    {
                        "action": "tool",
                        "tool_name": "sort_array",
                        "args": {"items": [28, 104, 16, 32, 24, 28, 20], "order": "asc"},
                    },
                    {"action": "finish", "answer": "done"},
                ]
            )
            orchestrator = LangGraphOrchestrator(
                provider=provider,
                memo_store=memo_store,
                checkpoint_store=checkpoint_store,
                policy=MemoizationPolicy(max_policy_retries=2),
                max_steps=20,
            )
            result = orchestrator.run(
                "\n".join(
                    [
                        'Task 1: repeat this exact message: "Agent loop is working!"',
                        "Task 2: sort these numbers in ascending order: 5, 2, 8, 1, 9, 3",
                        'Task 3: uppercase this text: "the quick brown fox"',
                        "Task 4: write the fibonacci sequence until the 100th number to fib.txt (start with 0 1 as the first numbers).",
                        "Task 5: sort these numbers in ascending order: 28, 104, 16, 32, 24, 28, 20",
                    ]
                )
            )

            self.assertEqual(result["answer"], "done")
            self.assertEqual(result["derived_snapshot"]["cache_reuse_hits"], 1)
            self.assertEqual(
                [item["tool"] for item in result["tools_used"]],
                ["repeat_message", "sort_array", "string_ops", "write_file", "sort_array"],
            )
            mission_4 = result["mission_report"][3]
            mission_5 = result["mission_report"][4]
            self.assertIn("write_file", mission_4["used_tools"])
            self.assertNotIn("write_file", mission_5["used_tools"])
            self.assertIn("sort_array", mission_5["used_tools"])

    def test_structured_plan_populated_in_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = ScriptedProvider(
                [
                    {"action": "tool", "tool_name": "repeat_message", "args": {"message": "ok"}},
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
            result = orchestrator.run("Task 1: repeat hello")
            state = result["state"]
            self.assertIsNotNone(state.get("structured_plan"))
            plan = state["structured_plan"]
            self.assertIn("steps", plan)
            self.assertIn("flat_missions", plan)
            self.assertIn("parsing_method", plan)

    def test_backward_compat_flat_missions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = ScriptedProvider(
                [
                    {"action": "tool", "tool_name": "repeat_message", "args": {"message": "ok"}},
                    {"action": "tool", "tool_name": "sort_array", "args": {"items": [3, 1, 2]}},
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
            result = orchestrator.run("Task 1: repeat hello\nTask 2: sort array")
            self.assertEqual(result["answer"], "done")
            self.assertEqual(len(result["state"]["missions"]), 2)
            self.assertTrue(result["state"]["missions"][0].startswith("Task 1:"))

    def test_text_analysis_tool_in_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = ScriptedProvider(
                [
                    {
                        "action": "tool",
                        "tool_name": "text_analysis",
                        "args": {"text": "Hello world. How are you?", "operation": "word_count"},
                    },
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
            result = orchestrator.run("Task 1: analyze text")
            self.assertEqual([item["tool"] for item in result["tools_used"]], ["text_analysis"])
            self.assertEqual(result["tools_used"][0]["result"]["word_count"], 5)

    def test_data_analysis_then_sort_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = ScriptedProvider(
                [
                    {
                        "action": "tool",
                        "tool_name": "data_analysis",
                        "args": {"numbers": [1, 2, 3, 4, 5], "operation": "summary_stats"},
                    },
                    {
                        "action": "tool",
                        "tool_name": "sort_array",
                        "args": {"items": [5, 4, 3, 2, 1], "order": "asc"},
                    },
                    {
                        "action": "tool",
                        "tool_name": "math_stats",
                        "args": {"operation": "mean", "numbers": [1, 2, 3, 4, 5]},
                    },
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
            result = orchestrator.run("Task 1: analyze data\nTask 2: sort\nTask 3: calculate mean")
            tools = [item["tool"] for item in result["tools_used"]]
            self.assertEqual(tools, ["data_analysis", "sort_array", "math_stats"])
            self.assertEqual(result["tools_used"][0]["result"]["mean"], 3.0)

    def test_shared_plan_md_written(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)
                provider = ScriptedProvider(
                    [
                        {
                            "action": "tool",
                            "tool_name": "repeat_message",
                            "args": {"message": "ok"},
                        },
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
                orchestrator.run("Task 1: repeat hello")
                shared_plan_path = os.path.join(temp_dir, "Shared_plan.md")
                self.assertTrue(os.path.exists(shared_plan_path))
                with open(shared_plan_path) as f:
                    content = f.read()
                self.assertIn("Shared Plan", content)
                self.assertIn("Task 1", content)
                self.assertIn("IMPLEMENTED", content)
            finally:
                os.chdir(original_cwd)

    def test_new_tools_in_system_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            orchestrator = LangGraphOrchestrator(
                provider=ScriptedProvider([{"action": "finish", "answer": "done"}]),
                memo_store=SQLiteMemoStore(f"{temp_dir}/memo.db"),
                checkpoint_store=SQLiteCheckpointStore(f"{temp_dir}/checkpoints.db"),
                policy=MemoizationPolicy(max_policy_retries=1),
                max_steps=20,
            )
            prompt = orchestrator.system_prompt
            expected_tools = [
                "repeat_message",
                "sort_array",
                "string_ops",
                "math_stats",
                "write_file",
                "memoize",
                "retrieve_memo",
                "task_list_parser",
                "text_analysis",
                "data_analysis",
                "json_parser",
                "regex_matcher",
            ]
            for tool_name in expected_tools:
                self.assertIn(tool_name, prompt, f"{tool_name} not found in system prompt")

    def test_arg_normalization_text_analysis_op_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = ScriptedProvider(
                [
                    {
                        "action": "tool",
                        "tool_name": "text_analysis",
                        "args": {"text": "hello world", "op": "word_count"},
                    },
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
            result = orchestrator.run("Task 1: analyze")
            self.assertEqual(result["tools_used"][0]["result"]["word_count"], 2)

    def test_arg_normalization_data_analysis_values_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = ScriptedProvider(
                [
                    {
                        "action": "tool",
                        "tool_name": "data_analysis",
                        "args": {"values": [1, 2, 3], "operation": "summary_stats"},
                    },
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
            result = orchestrator.run("Task 1: analyze data")
            self.assertEqual(result["tools_used"][0]["args"]["numbers"], [1, 2, 3])
            self.assertEqual(result["tools_used"][0]["result"]["count"], 3)

    def test_arg_normalization_regex_matcher_regex_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = ScriptedProvider(
                [
                    {
                        "action": "tool",
                        "tool_name": "regex_matcher",
                        "args": {"text": "abc123", "regex": r"\d+", "operation": "find_all"},
                    },
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
            result = orchestrator.run("Task 1: regex match")
            self.assertEqual(result["tools_used"][0]["args"]["pattern"], r"\d+")
            self.assertEqual(result["tools_used"][0]["result"]["matches"], ["123"])


if __name__ == "__main__":
    unittest.main()
