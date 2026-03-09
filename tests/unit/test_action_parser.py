"""Unit tests for action JSON parsing and schema validation."""

from __future__ import annotations

import logging
import unittest

import pytest

from agentic_workflows.orchestration.langgraph import action_parser


class TestActionParser(unittest.TestCase):
    def test_parse_action_json_recovers_first_object(self) -> None:
        raw = 'noise {"action":"finish","answer":"done"} trailing'
        parsed = action_parser.parse_action_json(raw)
        self.assertEqual(parsed["action"], "finish")
        self.assertEqual(parsed["answer"], "done")

    def test_extract_all_json_objects(self) -> None:
        raw = '{"action":"finish","answer":"a"} {"action":"finish","answer":"b"}'
        objects = action_parser.extract_all_json_objects(raw)
        self.assertEqual(len(objects), 2)

    def test_parse_all_actions_json_filters_non_actions(self) -> None:
        raw = '{"foo":1} {"action":"finish","answer":"done"}'
        actions = action_parser.parse_all_actions_json(raw)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "finish")

    def test_validate_action_accepts_tool_alias(self) -> None:
        registry = {"repeat_message": object()}
        model_output = '{"action":"repeat_message","args":{"message":"ok"}}'
        parsed = action_parser.validate_action(model_output, registry)
        self.assertEqual(parsed["action"], "tool")
        self.assertEqual(parsed["tool_name"], "repeat_message")
        self.assertEqual(parsed["args"]["message"], "ok")

    def test_strip_thinking_removes_scratchpad(self) -> None:
        raw = '<thinking>Let me reason about this.</thinking>{"action":"finish","answer":"ok"}'
        parsed = action_parser.parse_action_json(raw)
        self.assertEqual(parsed["action"], "finish")
        self.assertEqual(parsed["answer"], "ok")

    def test_strip_thinking_multiline(self) -> None:
        raw = "<thinking>\nStep 1: plan\nStep 2: act\n</thinking>\n{\"action\":\"finish\",\"answer\":\"done\"}"
        parsed = action_parser.parse_action_json(raw)
        self.assertEqual(parsed["answer"], "done")

    def test_strip_thinking_parse_all_actions(self) -> None:
        raw = '<thinking>reasoning</thinking>{"action":"finish","answer":"a"} {"action":"finish","answer":"b"}'
        actions = action_parser.parse_all_actions_json(raw)
        self.assertEqual(len(actions), 2)

    def test_validate_action_from_dict_preserves_mission_id(self) -> None:
        registry = {"repeat_message": object()}
        payload = {
            "action": "tool",
            "tool_name": "repeat_message",
            "args": {"message": "hello"},
            "__mission_id": 3,
        }
        validated = action_parser.validate_action_from_dict(payload, registry)
        self.assertEqual(validated["__mission_id"], 3)
        self.assertEqual(validated["tool_name"], "repeat_message")


class TestParserFallbackLogging:
    """Tests for WARNING log emission on fallback parse path."""

    def test_fallback_emits_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Fallback path emits WARNING with PARSER FALLBACK marker."""
        raw = 'noise before {"action":"finish","answer":"done"}'
        with caplog.at_level(logging.WARNING, logger="langgraph.action_parser"):
            action_parser.parse_action_json(raw, step=3)
        assert any("PARSER FALLBACK" in r.message for r in caplog.records), (
            "Expected WARNING with PARSER FALLBACK in message"
        )

    def test_fallback_warning_contains_step(self, caplog: pytest.LogCaptureFixture) -> None:
        """WARNING message includes the step number."""
        raw = 'noise {"action":"finish","answer":"x"}'
        with caplog.at_level(logging.WARNING, logger="langgraph.action_parser"):
            action_parser.parse_action_json(raw, step=7)
        combined = " ".join(r.message for r in caplog.records)
        assert "step=7" in combined, f"Expected step=7 in WARNING; got: {combined}"

    def test_fallback_prose_prefix_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """A second WARNING with prose_prefix is emitted when prefix is non-empty."""
        raw = 'some prose before {"action":"finish","answer":"x"}'
        with caplog.at_level(logging.WARNING, logger="langgraph.action_parser"):
            action_parser.parse_action_json(raw, step=5)
        assert any("prose_prefix" in r.message for r in caplog.records), (
            "Expected prose_prefix WARNING when there is text before the JSON object"
        )

    def test_happy_path_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Happy path (clean JSON) emits NO WARNING."""
        raw = '{"action":"finish","answer":"x"}'
        with caplog.at_level(logging.WARNING, logger="langgraph.action_parser"):
            action_parser.parse_action_json(raw, step=0)
        assert not caplog.records, (
            f"Expected no warnings on happy path; got: {[r.message for r in caplog.records]}"
        )


if __name__ == "__main__":
    unittest.main()
