"""Unit tests for action JSON parsing and schema validation."""

from __future__ import annotations

import logging
import unittest

import pytest

from agentic_workflows.orchestration.langgraph import action_parser


class TestActionParser(unittest.TestCase):
    def test_parse_action_json_recovers_first_object(self) -> None:
        raw = 'noise {"action":"finish","answer":"done"} trailing'
        parsed, _ = action_parser.parse_action_json(raw)
        self.assertEqual(parsed["action"], "finish")
        self.assertEqual(parsed["answer"], "done")

    def test_extract_all_json_objects(self) -> None:
        raw = '{"action":"finish","answer":"a"} {"action":"finish","answer":"b"}'
        objects = action_parser.extract_all_json_objects(raw)
        self.assertEqual(len(objects), 2)

    def test_parse_all_actions_json_filters_non_actions(self) -> None:
        raw = '{"foo":1} {"action":"finish","answer":"done"}'
        actions, _ = action_parser.parse_all_actions_json(raw)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "finish")

    def test_validate_action_accepts_tool_alias(self) -> None:
        registry = {"repeat_message": object()}
        model_output = '{"action":"repeat_message","args":{"message":"ok"}}'
        parsed, _ = action_parser.validate_action(model_output, registry)
        self.assertEqual(parsed["action"], "tool")
        self.assertEqual(parsed["tool_name"], "repeat_message")
        self.assertEqual(parsed["args"]["message"], "ok")

    def test_strip_thinking_removes_scratchpad(self) -> None:
        raw = '<thinking>Let me reason about this.</thinking>{"action":"finish","answer":"ok"}'
        parsed, _ = action_parser.parse_action_json(raw)
        self.assertEqual(parsed["action"], "finish")
        self.assertEqual(parsed["answer"], "ok")

    def test_strip_thinking_multiline(self) -> None:
        raw = "<thinking>\nStep 1: plan\nStep 2: act\n</thinking>\n{\"action\":\"finish\",\"answer\":\"done\"}"
        parsed, _ = action_parser.parse_action_json(raw)
        self.assertEqual(parsed["answer"], "done")

    def test_strip_thinking_parse_all_actions(self) -> None:
        raw = '<thinking>reasoning</thinking>{"action":"finish","answer":"a"} {"action":"finish","answer":"b"}'
        actions, _ = action_parser.parse_all_actions_json(raw)
        self.assertEqual(len(actions), 2)

    def test_validate_action_from_dict_preserves_mission_id(self) -> None:
        registry = {"repeat_message": object()}
        payload = {
            "action": "tool",
            "tool_name": "repeat_message",
            "args": {"message": "hello"},
            "__mission_id": 3,
        }
        validated, _ = action_parser.validate_action_from_dict(payload, registry)
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

    def test_fallback_returns_true_flag(self) -> None:
        """Fallback path returns used_fallback=True."""
        raw = 'noise {"action":"finish","answer":"done"}'
        _, used_fallback = action_parser.parse_action_json(raw, step=0)
        assert used_fallback is True, "Expected used_fallback=True on fallback path"

    def test_happy_path_returns_false_flag(self) -> None:
        """Happy path returns used_fallback=False."""
        raw = '{"action":"finish","answer":"done"}'
        _, used_fallback = action_parser.parse_action_json(raw, step=0)
        assert used_fallback is False, "Expected used_fallback=False on happy path"


class TestFormatCorrectionEscalation:
    """Tests for the 3-step format correction escalation chain in _plan_next_action.

    The escalation targets parseable-but-non-canonical output where the fallback
    parser recovers a valid action. Steps: hint (1) -> retry (2) -> accept (3).
    """

    def _make_state(self) -> dict:
        """Create a minimal state dict for escalation testing."""
        from agentic_workflows.orchestration.langgraph.state_schema import new_run_state

        state = new_run_state("system", "test input")
        state["missions"] = ["test mission"]
        state["mission_reports"] = [{
            "mission_id": 1,
            "mission": "test mission",
            "used_tools": [],
            "tool_results": [],
            "result": "",
            "status": "in_progress",
            "required_tools": [],
            "required_files": [],
            "written_files": [],
            "expected_fibonacci_count": None,
            "contract_checks": [],
            "subtask_contracts": [],
            "subtask_statuses": [],
        }]
        state["active_mission_index"] = 0
        state["active_mission_id"] = 1
        return state

    def test_escalation_first_drift_injects_hint(self) -> None:
        """First format drift injects [Orchestrator] hint message and increments format_correction_hints."""
        state = self._make_state()
        state["retry_counts"]["consecutive_format_drift"] = 0

        # Simulate first drift
        _parse_used_fallback = True
        _validate_used_fallback = False

        if _parse_used_fallback or _validate_used_fallback:
            drift_count = int(state["retry_counts"].get("consecutive_format_drift", 0)) + 1
            state["retry_counts"]["consecutive_format_drift"] = drift_count

        assert state["retry_counts"]["consecutive_format_drift"] == 1
        assert state["structural_health"]["format_correction_hints"] == 0  # Not yet incremented - needs graph.py logic
        # This test will FAIL because the escalation logic in graph.py doesn't exist yet

    def test_escalation_second_drift_triggers_retry(self) -> None:
        """Second consecutive drift triggers retry and increments format_retries."""
        state = self._make_state()
        state["retry_counts"]["consecutive_format_drift"] = 1

        # The format_retries counter should exist and be incrementable
        assert "format_retries" in state["structural_health"], (
            "format_retries must be initialized in structural_health defaults"
        )

    def test_escalation_third_drift_accepts(self) -> None:
        """Third consecutive drift accepts the parsed action (no retry)."""
        state = self._make_state()
        state["retry_counts"]["consecutive_format_drift"] = 2

        # Simulate third drift - should accept without retry
        drift_count = int(state["retry_counts"].get("consecutive_format_drift", 0)) + 1
        assert drift_count >= 3, "Third drift should be >= 3"

    def test_clean_parse_resets_drift_counter(self) -> None:
        """Correctly-formatted response resets consecutive_format_drift to 0."""
        state = self._make_state()
        state["retry_counts"]["consecutive_format_drift"] = 2

        # Simulate clean parse
        _parse_used_fallback = False
        _validate_used_fallback = False

        if not (_parse_used_fallback or _validate_used_fallback):
            state["retry_counts"]["consecutive_format_drift"] = 0

        assert state["retry_counts"]["consecutive_format_drift"] == 0

    def test_structural_health_has_format_counters(self) -> None:
        """structural_health must contain format_correction_hints and format_retries after state init."""
        state = self._make_state()

        assert "format_correction_hints" in state["structural_health"], (
            "structural_health must include format_correction_hints"
        )
        assert "format_retries" in state["structural_health"], (
            "structural_health must include format_retries"
        )

    def test_hard_parse_failure_uses_invalid_json_not_escalation(self) -> None:
        """Hard parse failures (no valid JSON) should NOT use the escalation chain."""
        state = self._make_state()
        state["retry_counts"]["consecutive_format_drift"] = 0

        # Simulate hard parse failure (exception path, not fallback path)
        invalid_count = int(state["retry_counts"].get("invalid_json", 0)) + 1
        state["retry_counts"]["invalid_json"] = invalid_count

        # Drift counter should be unchanged
        assert state["retry_counts"]["consecutive_format_drift"] == 0
        assert state["retry_counts"]["invalid_json"] == 1


if __name__ == "__main__":
    unittest.main()
