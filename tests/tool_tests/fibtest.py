from __future__ import annotations

"""Manual fib memoization flow test (main-style runnable script).

Run from repo root:
  .venv/bin/python tests/tool_tests/fibtest.py
"""

import json
import sys
from pathlib import Path
import tempfile


if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from execution.langgraph.checkpoint_store import SQLiteCheckpointStore
from execution.langgraph.graph import LangGraphOrchestrator
from execution.langgraph.memo_store import SQLiteMemoStore
from execution.langgraph.policy import MemoizationPolicy


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


def _print_run(label: str, result: dict) -> None:
    print(f"\n=== {label} ===")
    print("RUN ID:", result["run_id"])
    print("TOOLS USED:")
    for item in result["tools_used"]:
        print(f"  #{item['call']} {item['tool']} -> {item['result']}")
    print("MEMO EVENTS:")
    for event in result.get("memo_events", []):
        print(
            "  "
            f"step={event.get('step')} source_tool={event.get('source_tool')} "
            f"key={event.get('key')} namespace={event.get('namespace')} "
            f"value_hash={event.get('value_hash')}"
        )
    print("DERIVED SNAPSHOT:", result.get("derived_snapshot", {}))
    print("ANSWER:", result.get("answer", ""))


def main() -> None:
    sequence_0_10 = "0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55"

    with tempfile.TemporaryDirectory() as temp_dir:
        memo_store = SQLiteMemoStore(f"{temp_dir}/memo.db")
        checkpoint_store = SQLiteCheckpointStore(f"{temp_dir}/checkpoints.db")
        run_id = "fib-0-10-demo"
        output_path = f"{temp_dir}/fib_0_10.txt"
        write_key = f"write_file:{output_path}"

        # Pass 1: retrieve miss -> write -> memoize
        provider_first = ScriptedProvider(
            [
                {"action": "tool", "tool_name": "retrieve_memo", "args": {"key": write_key}},
                {
                    "action": "tool",
                    "tool_name": "write_file",
                    "args": {"path": output_path, "content": sequence_0_10},
                },
                {
                    "action": "tool",
                    "tool_name": "memoize",
                    "args": {
                        "key": write_key,
                        "value": {"sequence": sequence_0_10, "path": output_path},
                        "source_tool": "write_file",
                    },
                },
                {"action": "finish", "answer": "Pass 1 complete"},
            ]
        )

        orchestrator_first = LangGraphOrchestrator(
            provider=provider_first,
            memo_store=memo_store,
            checkpoint_store=checkpoint_store,
            policy=MemoizationPolicy(max_policy_retries=2),
            max_steps=20,
        )
        result_first = orchestrator_first.run(
            "Task 1: retrieve fib memo for 0-10\nTask 2: write fib 0-10\nTask 3: memoize fib 0-10",
            run_id=run_id,
        )
        _print_run("PASS 1 (MISS -> WRITE -> MEMOIZE)", result_first)

        # Pass 2: retrieve hit from DB
        provider_second = ScriptedProvider(
            [
                {"action": "tool", "tool_name": "retrieve_memo", "args": {"key": write_key}},
                {"action": "finish", "answer": "Pass 2 complete (retrieved from memo DB)"},
            ]
        )
        orchestrator_second = LangGraphOrchestrator(
            provider=provider_second,
            memo_store=memo_store,
            checkpoint_store=checkpoint_store,
            policy=MemoizationPolicy(max_policy_retries=2),
            max_steps=10,
        )
        result_second = orchestrator_second.run(
            "Task 1: retrieve fib memo for 0-10 and finish",
            run_id=run_id,
        )
        _print_run("PASS 2 (RETRIEVE HIT)", result_second)


if __name__ == "__main__":
    main()
