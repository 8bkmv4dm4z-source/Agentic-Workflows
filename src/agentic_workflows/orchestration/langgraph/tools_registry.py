from __future__ import annotations

"""Tool registry and memo-specific tool adapters for Phase 1."""

from typing import Any

from agentic_workflows.orchestration.langgraph.checkpoint_store import SQLiteCheckpointStore
from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore
from agentic_workflows.tools.base import Tool
from agentic_workflows.tools.classify_intent import ClassifyIntentTool
from agentic_workflows.tools.clear_context import ClearContextTool
from agentic_workflows.tools.compare_texts import CompareTextsTool
from agentic_workflows.tools.data_analysis import DataAnalysisTool
from agentic_workflows.tools.datetime_ops import DateTimeOpsTool
from agentic_workflows.tools.describe_db_schema import DescribeDbSchemaTool
from agentic_workflows.tools.echo import EchoTool
from agentic_workflows.tools.encode_decode import EncodeDecodeTool
from agentic_workflows.tools.extract_table import ExtractTableTool
from agentic_workflows.tools.file_manager import FileManagerTool
from agentic_workflows.tools.fill_template import FillTemplateTool
from agentic_workflows.tools.format_converter import FormatConverterTool
from agentic_workflows.tools.hash_content import HashContentTool
from agentic_workflows.tools.http_request import HttpRequestTool
from agentic_workflows.tools.json_parser import JsonParserTool
from agentic_workflows.tools.list_directory import ListDirectoryTool
from agentic_workflows.tools.math_stats import MathStatsTool
from agentic_workflows.tools.parse_code_structure import ParseCodeStructureTool
from agentic_workflows.tools.query_db import QueryDBTool
from agentic_workflows.tools.read_file import ReadFileTool
from agentic_workflows.tools.recognize_pattern import RecognizePatternTool
from agentic_workflows.tools.regex_matcher import RegexMatcherTool
from agentic_workflows.tools.retrieve_run_context import RetrieveRunContextTool
from agentic_workflows.tools.run_bash import RunBashTool
from agentic_workflows.tools.search_content import SearchContentTool
from agentic_workflows.tools.search_files import SearchFilesTool
from agentic_workflows.tools.sort_array import SortArrayTool
from agentic_workflows.tools.string_ops import StringOpsTool
from agentic_workflows.tools.summarize_text import SummarizeTextTool
from agentic_workflows.tools.task_list_parser import TaskListParserTool
from agentic_workflows.tools.text_analysis import TextAnalysisTool
from agentic_workflows.tools.update_file_section import UpdateFileSectionTool
from agentic_workflows.tools.validate_data import ValidateDataTool
from agentic_workflows.tools.write_file import WriteFileTool


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


def build_tool_registry(
    store: SQLiteMemoStore,
    checkpoint_store: SQLiteCheckpointStore | None = None,
) -> dict[str, Tool]:
    """Build the full tool map used by graph execution nodes."""
    registry: dict[str, Tool] = {
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
        "parse_code_structure": ParseCodeStructureTool(),
        "describe_db_schema": DescribeDbSchemaTool(),
        "read_file": ReadFileTool(),
        "run_bash": RunBashTool(),
        "http_request": HttpRequestTool(),
        "datetime_ops": DateTimeOpsTool(),
        "extract_table": ExtractTableTool(),
        "fill_template": FillTemplateTool(),
        "hash_content": HashContentTool(),
        "query_db": QueryDBTool(),
        "recognize_pattern": RecognizePatternTool(),
        "clear_context": ClearContextTool(),
        "update_file_section": UpdateFileSectionTool(),
        # New tools
        "list_directory": ListDirectoryTool(),
        "search_files": SearchFilesTool(),
        "search_content": SearchContentTool(),
        "summarize_text": SummarizeTextTool(),
        "compare_texts": CompareTextsTool(),
        "classify_intent": ClassifyIntentTool(),
        "format_converter": FormatConverterTool(),
        "file_manager": FileManagerTool(),
        "encode_decode": EncodeDecodeTool(),
        "validate_data": ValidateDataTool(),
    }
    if checkpoint_store is not None:
        registry["retrieve_run_context"] = RetrieveRunContextTool(checkpoint_store)
    return registry
