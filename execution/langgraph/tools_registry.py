from __future__ import annotations

"""Tool registry and memo-specific tool adapters for Phase 1."""

from typing import Any

from tools.base import Tool
from tools.data_analysis import DataAnalysisTool
from tools.echo import EchoTool
from tools.json_parser import JsonParserTool
from tools.math_stats import MathStatsTool
from tools.regex_matcher import RegexMatcherTool
from tools.sort_array import SortArrayTool
from tools.string_ops import StringOpsTool
from tools.task_list_parser import TaskListParserTool
from tools.text_analysis import TextAnalysisTool
from tools.write_file import WriteFileTool

from execution.langgraph.memo_store import SQLiteMemoStore


class MemoizeStoreTool(Tool):
    """Tool wrapper that writes memo entries through the SQLiteMemoStore."""

    name = "memoize"
    description = "Memoize key/value in run-scoped store. Required args: key, value, run_id."

    def __init__(self, store: SQLiteMemoStore) -> None:
        self.store = store

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        key = str(args.get("key", "")).strip()
        namespace = str(args.get("namespace", "run")).strip() or "run"
        run_id = str(args.get("run_id", "")).strip()
        source_tool = str(args.get("source_tool", "memoize")).strip() or "memoize"
        step = int(args.get("step", 0))
        value = args.get("value")

        if not key:
            return {"error": "key is required"}
        if value is None:
            return {"error": "value is required"}
        if not run_id:
            return {"error": "run_id is required"}

        put_result = self.store.put(
            run_id=run_id,
            key=key,
            value=value,
            namespace=namespace,
            source_tool=source_tool,
            step=step,
        )
        return {
            "result": "memoized",
            "key": put_result.key,
            "namespace": put_result.namespace,
            "value_hash": put_result.value_hash,
            "run_id": put_result.run_id,
        }


class RetrieveMemoTool(Tool):
    """Tool wrapper that retrieves memo entries by run/key."""

    name = "retrieve_memo"
    description = "Retrieve memoized value by key. Required args: key, run_id."

    def __init__(self, store: SQLiteMemoStore) -> None:
        self.store = store

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        key = str(args.get("key", "")).strip()
        namespace = str(args.get("namespace", "run")).strip() or "run"
        run_id = str(args.get("run_id", "")).strip()

        if not key:
            return {"error": "key is required"}
        if not run_id:
            return {"error": "run_id is required"}

        lookup = self.store.get(run_id=run_id, key=key, namespace=namespace)
        if not lookup.found:
            return {"found": False, "key": key, "namespace": namespace}

        return {
            "found": True,
            "key": key,
            "namespace": namespace,
            "value": lookup.value,
            "value_hash": lookup.value_hash,
            "run_id": lookup.run_id,
        }


def build_tool_registry(store: SQLiteMemoStore) -> dict[str, Tool]:
    """Build the full tool map used by graph execution nodes."""
    return {
        "repeat_message": EchoTool(),
        "sort_array": SortArrayTool(),
        "string_ops": StringOpsTool(),
        "math_stats": MathStatsTool(),
        "write_file": WriteFileTool(),
        "memoize": MemoizeStoreTool(store),
        "retrieve_memo": RetrieveMemoTool(store),
        "task_list_parser": TaskListParserTool(),
        "text_analysis": TextAnalysisTool(),
        "data_analysis": DataAnalysisTool(),
        "json_parser": JsonParserTool(),
        "regex_matcher": RegexMatcherTool(),
    }
