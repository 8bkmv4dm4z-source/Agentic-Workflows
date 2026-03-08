"""Unit tests for fallback_planner — deterministic_fallback_action and normalize_tool_args."""

from __future__ import annotations

import json
import unittest

from agentic_workflows.orchestration.langgraph.fallback_planner import (
    deterministic_fallback_action,
    normalize_tool_args,
)


def _pending_state(mission: str, required_tools: list[str] | None = None) -> dict:
    """Minimal state with one pending mission report."""
    return {
        "run_id": "test-run",
        "mission_reports": [
            {
                "mission_id": 1,
                "mission": mission,
                "status": "pending",
                "required_tools": required_tools or [],
                "used_tools": [],
                "required_files": [],
                "written_files": [],
            }
        ],
        "seen_tool_signatures": [],
        "policy_flags": {},
        "missions": [mission],
        "mission_contracts": [],
    }


def _all_done_state() -> dict:
    """State where all missions are completed."""
    return {
        "run_id": "test-run",
        "mission_reports": [
            {
                "mission_id": 1,
                "mission": "Echo hello",
                "status": "completed",
                "result": "done",
                "required_tools": [],
                "used_tools": ["repeat_message"],
                "required_files": [],
                "written_files": [],
            }
        ],
        "seen_tool_signatures": [],
        "policy_flags": {},
    }


class TestDeterministicFallbackMemoRequired(unittest.TestCase):
    def test_memo_required_with_key_returns_memoize_action(self) -> None:
        state = {
            "run_id": "r1",
            "mission_reports": [],
            "seen_tool_signatures": [],
            "policy_flags": {
                "memo_required": True,
                "memo_required_key": "sort_result",
                "last_tool_name": "sort_array",
                "last_tool_result": {"sorted": [1, 2, 3]},
            },
            "mission_contracts": [],
        }
        action = deterministic_fallback_action(state)
        assert action is not None
        assert action["action"] == "tool"
        assert action["tool_name"] == "memoize"
        assert action["args"]["key"] == "sort_result"
        assert action["args"]["source_tool"] == "sort_array"
        assert action["args"]["value"] == {"sorted": [1, 2, 3]}

    def test_memo_required_empty_last_result_uses_default_value(self) -> None:
        state = {
            "run_id": "r1",
            "mission_reports": [],
            "seen_tool_signatures": [],
            "policy_flags": {
                "memo_required": True,
                "memo_required_key": "my_key",
                "last_tool_name": "",
                "last_tool_result": {},
            },
            "mission_contracts": [],
        }
        action = deterministic_fallback_action(state)
        assert action is not None
        assert action["args"]["value"] == {"status": "memoized_by_fallback"}
        assert action["args"]["source_tool"] == "memoize"  # empty name falls back

    def test_memo_required_but_no_key_falls_through(self) -> None:
        """When memo_required=True but key is empty, should not return memoize action."""
        state = {
            "run_id": "r1",
            "mission_reports": [
                {
                    "mission_id": 1,
                    "mission": 'Say "hello"',
                    "status": "completed",
                    "result": "done",
                    "required_tools": [],
                    "used_tools": [],
                    "required_files": [],
                    "written_files": [],
                }
            ],
            "seen_tool_signatures": [],
            "policy_flags": {
                "memo_required": True,
                "memo_required_key": "",
            },
            "mission_contracts": [],
        }
        # Should fall through to finish (all missions completed)
        action = deterministic_fallback_action(state)
        assert action is not None
        assert action["action"] == "finish"


class TestDeterministicFallbackAllDone(unittest.TestCase):
    def test_returns_finish_when_all_completed(self) -> None:
        action = deterministic_fallback_action(_all_done_state())
        assert action is not None
        assert action["action"] == "finish"
        assert "All tasks completed" in action["answer"]


class TestDeterministicFallbackEmptyMission(unittest.TestCase):
    def test_empty_mission_text_returns_finish(self) -> None:
        """next_incomplete_mission returns '' → fallback emits finish."""
        state = {
            "run_id": "r1",
            "mission_reports": [
                {
                    "mission_id": 1,
                    "mission": "",  # empty mission text
                    "status": "pending",
                    "required_tools": [],
                    "used_tools": [],
                    "required_files": [],
                    "written_files": [],
                }
            ],
            "seen_tool_signatures": [],
            "policy_flags": {},
            "mission_contracts": [],
        }
        action = deterministic_fallback_action(state)
        assert action is not None
        assert action["action"] == "finish"


class TestDeterministicFallbackRepeatMessage(unittest.TestCase):
    def test_repeat_message_action_returned(self) -> None:
        state = _pending_state('Repeat the message "hello world"', ["repeat_message"])
        action = deterministic_fallback_action(state)
        assert action is not None
        assert action["tool_name"] == "repeat_message"
        assert action["args"]["message"] == "hello world"

    def test_repeat_message_skipped_when_duplicate(self) -> None:
        state = _pending_state('Repeat the message "hello world"', ["repeat_message"])
        # Pre-populate seen signatures with the repeat_message action
        sig = 'repeat_message:' + json.dumps({"message": "hello world"}, sort_keys=True)
        state["seen_tool_signatures"] = [sig]
        # Should fall through to None (no other path matches)
        action = deterministic_fallback_action(state)
        # Either None or a different action — repeat_message not returned
        if action is not None:
            assert action.get("tool_name") != "repeat_message" or action.get("args", {}).get("message") != "hello world"


class TestDeterministicFallbackSortArray(unittest.TestCase):
    def test_sort_asc_from_mission_text(self) -> None:
        state = _pending_state("Sort the numbers [3, 1, 2] in ascending order", ["sort_array"])
        action = deterministic_fallback_action(state)
        assert action is not None
        assert action["tool_name"] == "sort_array"
        assert action["args"]["order"] == "asc"
        assert set(action["args"]["items"]) == {3, 1, 2}

    def test_sort_desc_from_mission_text(self) -> None:
        state = _pending_state("Sort [5, 3, 8] in descending desc order", ["sort_array"])
        action = deterministic_fallback_action(state)
        assert action is not None
        assert action["tool_name"] == "sort_array"
        assert action["args"]["order"] == "desc"

    def test_sort_no_numbers_falls_through(self) -> None:
        state = _pending_state("Sort this data somehow", ["sort_array"])
        action = deterministic_fallback_action(state)
        # No numbers → sort path skipped
        assert action is None or action.get("tool_name") != "sort_array"


class TestDeterministicFallbackStringOps(unittest.TestCase):
    def test_uppercase_action(self) -> None:
        state = _pending_state('Uppercase the text "hello"', ["string_ops"])
        action = deterministic_fallback_action(state)
        assert action is not None
        assert action["tool_name"] == "string_ops"
        assert action["args"]["operation"] == "uppercase"
        assert action["args"]["text"] == "hello"

    def test_lowercase_action(self) -> None:
        state = _pending_state('Lowercase the word "HELLO"', ["string_ops"])
        action = deterministic_fallback_action(state)
        assert action is not None
        assert action["tool_name"] == "string_ops"
        assert action["args"]["operation"] == "lowercase"

    def test_reverse_action(self) -> None:
        state = _pending_state('Reverse the string "abcde"', ["string_ops"])
        action = deterministic_fallback_action(state)
        assert action is not None
        assert action["tool_name"] == "string_ops"
        assert action["args"]["operation"] == "reverse"

    def test_string_ops_duplicate_skipped_falls_to_none(self) -> None:
        state = _pending_state('Uppercase the text "hello"', ["string_ops"])
        sig = 'string_ops:' + json.dumps({"operation": "uppercase", "text": "hello"}, sort_keys=True)
        state["seen_tool_signatures"] = [sig]
        action = deterministic_fallback_action(state)
        # Lowercase and reverse don't match "uppercase" mission → falls through
        assert action is None or action.get("args", {}).get("operation") != "uppercase"


class TestDeterministicFallbackFibWrite(unittest.TestCase):
    def test_fibonacci_write_action(self) -> None:
        state = _pending_state(
            "Compute the first 10 Fibonacci numbers and write them to fib.txt",
            ["write_file"],
        )
        action = deterministic_fallback_action(state)
        assert action is not None
        assert action["tool_name"] == "write_file"
        assert "fib" in action["args"]["path"].lower()
        content = action["args"]["content"]
        nums = [int(x.strip()) for x in content.split(",") if x.strip()]
        assert nums[:3] == [0, 1, 1]

    def test_fibonacci_write_uses_expected_count_from_report(self) -> None:
        state = _pending_state(
            "Compute fibonacci numbers and write to fib.txt",
            ["write_file"],
        )
        state["mission_reports"][0]["expected_fibonacci_count"] = 5
        action = deterministic_fallback_action(state)
        assert action is not None
        nums = [int(x.strip()) for x in action["args"]["content"].split(",") if x.strip()]
        assert len(nums) == 5


class TestDeterministicFallbackRepeatFallback(unittest.TestCase):
    def test_repeat_in_mission_lower_fallback(self) -> None:
        """The catch-all 'repeat' path at end of function."""
        state = _pending_state('Please repeat "goodbye" to the user', [])
        action = deterministic_fallback_action(state)
        # This hits the catch-all repeat path
        assert action is not None
        assert action["tool_name"] == "repeat_message"
        assert action["args"]["message"] == "goodbye"

    def test_returns_none_when_no_path_matches(self) -> None:
        state = _pending_state("Do something completely unrecognised", [])
        action = deterministic_fallback_action(state)
        assert action is None


class TestNormalizeToolArgs(unittest.TestCase):
    # sort_array aliases
    def test_sort_array_array_alias(self) -> None:
        result = normalize_tool_args("sort_array", {"array": [3, 1, 2]})
        assert result == {"items": [3, 1, 2]}

    def test_sort_array_values_alias(self) -> None:
        result = normalize_tool_args("sort_array", {"values": [5, 4]})
        assert result == {"items": [5, 4]}

    def test_sort_array_items_unchanged(self) -> None:
        result = normalize_tool_args("sort_array", {"items": [1, 2]})
        assert result == {"items": [1, 2]}

    # repeat_message alias
    def test_repeat_message_text_alias(self) -> None:
        result = normalize_tool_args("repeat_message", {"text": "hi"})
        assert result == {"message": "hi"}

    # string_ops alias
    def test_string_ops_op_alias(self) -> None:
        result = normalize_tool_args("string_ops", {"text": "x", "op": "uppercase"})
        assert result == {"text": "x", "operation": "uppercase"}

    # write_file aliases
    def test_write_file_file_path_alias(self) -> None:
        result = normalize_tool_args("write_file", {"file_path": "out.txt", "content": "x"})
        assert result == {"path": "out.txt", "content": "x"}

    def test_write_file_filename_alias(self) -> None:
        result = normalize_tool_args("write_file", {"filename": "out.txt", "content": "x"})
        assert result == {"path": "out.txt", "content": "x"}

    def test_write_file_text_alias(self) -> None:
        result = normalize_tool_args("write_file", {"path": "out.txt", "text": "hello"})
        assert result == {"path": "out.txt", "content": "hello"}

    def test_write_file_data_alias(self) -> None:
        result = normalize_tool_args("write_file", {"path": "out.txt", "data": "vals"})
        assert result == {"path": "out.txt", "content": "vals"}

    # memoize alias
    def test_memoize_data_alias(self) -> None:
        result = normalize_tool_args("memoize", {"key": "k", "data": {"x": 1}})
        assert result == {"key": "k", "value": {"x": 1}}

    # text_analysis alias
    def test_text_analysis_op_alias(self) -> None:
        result = normalize_tool_args("text_analysis", {"text": "abc", "op": "word_count"})
        assert result == {"text": "abc", "operation": "word_count"}

    # data_analysis aliases
    def test_data_analysis_data_alias(self) -> None:
        result = normalize_tool_args("data_analysis", {"data": [1.0, 2.0]})
        assert result == {"numbers": [1.0, 2.0]}

    def test_data_analysis_values_alias(self) -> None:
        result = normalize_tool_args("data_analysis", {"values": [3.0]})
        assert result == {"numbers": [3.0]}

    # regex_matcher alias
    def test_regex_matcher_regex_alias(self) -> None:
        result = normalize_tool_args("regex_matcher", {"regex": r"\d+", "text": "abc123"})
        assert result == {"pattern": r"\d+", "text": "abc123"}

    # outline_code alias
    def test_outline_code_file_path_alias(self) -> None:
        result = normalize_tool_args("outline_code", {"file_path": "main.py"})
        assert result == {"path": "main.py"}

    # list_directory / search_content / search_files aliases
    def test_list_directory_directory_alias(self) -> None:
        result = normalize_tool_args("list_directory", {"directory": "/tmp"})
        assert result == {"path": "/tmp"}

    def test_search_content_glob_alias(self) -> None:
        result = normalize_tool_args("search_content", {"path": "/tmp", "glob": "*.py"})
        assert result == {"path": "/tmp", "pattern": "*.py"}

    def test_search_files_query_alias(self) -> None:
        result = normalize_tool_args("search_files", {"path": "/tmp", "query": "hello"})
        assert result == {"path": "/tmp", "pattern": "hello"}

    # compare_texts aliases
    def test_compare_texts_left_right_aliases(self) -> None:
        result = normalize_tool_args("compare_texts", {"left": "a", "right": "b"})
        assert result == {"text1": "a", "text2": "b"}

    # file_manager aliases
    def test_file_manager_src_dst_aliases(self) -> None:
        result = normalize_tool_args("file_manager", {"src": "a.txt", "dst": "b.txt"})
        assert result == {"source": "a.txt", "destination": "b.txt"}

    def test_file_manager_dest_alias(self) -> None:
        result = normalize_tool_args("file_manager", {"source": "a.txt", "dest": "b.txt"})
        assert result == {"source": "a.txt", "destination": "b.txt"}

    def test_file_manager_op_alias(self) -> None:
        result = normalize_tool_args("file_manager", {"source": "a.txt", "destination": "b.txt", "op": "move"})
        assert result == {"source": "a.txt", "destination": "b.txt", "operation": "move"}

    # format_converter aliases
    def test_format_converter_input_format_alias(self) -> None:
        result = normalize_tool_args("format_converter", {"input_format": "json", "output_format": "yaml", "data": "{}"})
        assert result == {"from_format": "json", "to_format": "yaml", "data": "{}"}

    # encode_decode / classify_intent / validate_data / retrieve_run_context
    def test_encode_decode_op_alias(self) -> None:
        result = normalize_tool_args("encode_decode", {"text": "hello", "op": "base64_encode"})
        assert result == {"text": "hello", "operation": "base64_encode"}

    def test_classify_intent_op_alias(self) -> None:
        result = normalize_tool_args("classify_intent", {"text": "x", "op": "classify"})
        assert result == {"text": "x", "operation": "classify"}

    def test_validate_data_op_alias(self) -> None:
        result = normalize_tool_args("validate_data", {"data": {}, "op": "schema"})
        assert result == {"data": {}, "operation": "schema"}

    def test_retrieve_run_context_op_alias(self) -> None:
        result = normalize_tool_args("retrieve_run_context", {"op": "get"})
        assert result == {"operation": "get"}

    # No-op for unknown tool
    def test_unknown_tool_passthrough(self) -> None:
        result = normalize_tool_args("unknown_tool", {"foo": "bar"})
        assert result == {"foo": "bar"}


if __name__ == "__main__":
    unittest.main()
