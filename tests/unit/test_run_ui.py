"""Unit tests for run_ui.py — all pure rendering/helper functions."""

from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from agentic_workflows.orchestration.langgraph.run_ui import (
    _coerce_int,
    _word_wrap,
    build_verify_gate_outcome,
    collect_pipeline_trace,
    collect_retry_counts,
    extract_notable_events,
    render_clarification_panel,
    render_context_warning_panel,
    render_execution_summary_panel,
    render_mission_status_panel,
    render_notable_events_panel,
    render_pipeline_trace_panel,
    render_specialist_routing,
    render_stuck_indicator,
    render_verify_gate_panel,
)


class TestCoerceInt(unittest.TestCase):
    def test_int_passthrough(self) -> None:
        assert _coerce_int(5) == 5

    def test_string_digit(self) -> None:
        assert _coerce_int("3") == 3

    def test_none_returns_zero(self) -> None:
        assert _coerce_int(None) == 0

    def test_non_numeric_string_returns_zero(self) -> None:
        assert _coerce_int("abc") == 0

    def test_list_returns_zero(self) -> None:
        assert _coerce_int([1, 2]) == 0


class TestCollectRetryCounts(unittest.TestCase):
    def test_empty_result_returns_all_zero(self) -> None:
        counts = collect_retry_counts({})
        assert counts["invalid_json"] == 0
        assert counts["provider_timeout"] == 0
        assert counts["finish_rejected"] == 0

    def test_derived_snapshot_values_used(self) -> None:
        result = {
            "derived_snapshot": {
                "invalid_json_retries": 3,
                "provider_timeout_retries": 1,
                "finish_rejections": 2,
            }
        }
        counts = collect_retry_counts(result)
        assert counts["invalid_json"] == 3
        assert counts["provider_timeout"] == 1
        assert counts["finish_rejected"] == 2

    def test_state_retry_counts_fallback(self) -> None:
        result = {
            "state": {"retry_counts": {"invalid_json": 2, "duplicate_tool": 1}},
        }
        counts = collect_retry_counts(result)
        assert counts["invalid_json"] == 2
        assert counts["duplicate_tool"] == 1

    def test_non_dict_derived_ignored(self) -> None:
        result = {"derived_snapshot": "bad", "state": {"retry_counts": {"invalid_json": 4}}}
        counts = collect_retry_counts(result)
        assert counts["invalid_json"] == 4


class TestRenderExecutionSummaryPanel(unittest.TestCase):
    def test_no_retries_no_files(self) -> None:
        text = render_execution_summary_panel(
            mission_count=2,
            changed_files=[],
            tool_count=3,
            retry_counts={},
        )
        assert "missions: 2" in text
        assert "<none>" in text
        assert "tool_count: 3" in text
        assert "retries: total=0" in text

    def test_with_files_and_retries(self) -> None:
        text = render_execution_summary_panel(
            mission_count=1,
            changed_files=["fib.txt", "out.txt"],
            tool_count=5,
            retry_counts={"invalid_json": 2, "duplicate_tool": 1},
        )
        assert "fib.txt" in text
        assert "out.txt" in text
        assert "total=3" in text
        assert "invalid_json=2" in text
        assert "duplicate_tool=1" in text

    def test_negative_counts_clamped(self) -> None:
        text = render_execution_summary_panel(
            mission_count=-1,
            changed_files=[],
            tool_count=-3,
            retry_counts={"invalid_json": -2},
        )
        assert "missions: 0" in text
        assert "tool_count: 0" in text
        assert "total=0" in text


class TestBuildVerifyGateOutcome(unittest.TestCase):
    def test_all_pass(self) -> None:
        result = {
            "mission_report": [{"status": "completed"}, {"status": "completed"}],
            "audit_report": {"failed": 0},
        }
        outcome = build_verify_gate_outcome(result)
        assert outcome["status"] == "pass"
        assert outcome["completed_missions"] == 2
        assert outcome["total_missions"] == 2

    def test_audit_failure(self) -> None:
        result = {
            "mission_report": [{"status": "completed"}],
            "audit_report": {"failed": 1},
        }
        outcome = build_verify_gate_outcome(result)
        assert outcome["status"] == "fail"
        assert "audit_no_failures" in outcome["failed_checks"]

    def test_incomplete_missions(self) -> None:
        result = {
            "mission_report": [{"status": "pending"}, {"status": "completed"}],
            "audit_report": {},
        }
        outcome = build_verify_gate_outcome(result)
        assert outcome["status"] == "fail"
        assert "missions_completed" in outcome["failed_checks"]

    def test_finish_rejected(self) -> None:
        result = {
            "mission_report": [{"status": "completed"}],
            "audit_report": {},
            "derived_snapshot": {"finish_rejections": 3},
        }
        outcome = build_verify_gate_outcome(result)
        assert outcome["status"] == "fail"
        assert "finish_rejections_clear" in outcome["failed_checks"]

    def test_empty_mission_list(self) -> None:
        result = {}
        outcome = build_verify_gate_outcome(result)
        assert outcome["total_missions"] == 0
        assert outcome["status"] == "fail"  # missions_completed check fails when total==0


class TestRenderVerifyGatePanel(unittest.TestCase):
    def test_pass_panel(self) -> None:
        gate = {
            "status": "pass",
            "checks": {
                "missions_completed": True,
                "audit_no_failures": True,
                "finish_rejections_clear": True,
            },
            "failed_checks": [],
            "completed_missions": 2,
            "total_missions": 2,
        }
        text = render_verify_gate_panel(gate)
        assert "PASS" in text
        assert "2/2" in text
        assert "ok" in text

    def test_fail_panel_with_failed_checks(self) -> None:
        gate = {
            "status": "fail",
            "checks": {
                "missions_completed": False,
                "audit_no_failures": True,
                "finish_rejections_clear": True,
            },
            "failed_checks": ["missions_completed"],
            "completed_missions": 1,
            "total_missions": 2,
        }
        text = render_verify_gate_panel(gate)
        assert "FAIL" in text
        assert "missions_completed" in text
        assert "1/2" in text


class TestExtractNotableEvents(unittest.TestCase):
    def test_no_events_empty_result(self) -> None:
        events = extract_notable_events({})
        assert events == []

    def test_audit_findings(self) -> None:
        result = {
            "audit_report": {
                "findings": [
                    {"level": "fail", "message": "bad"},
                    {"level": "warn", "message": "meh"},
                    {"level": "info", "message": "ok"},
                ]
            }
        }
        events = extract_notable_events(result)
        assert any("fail=1" in e and "warn=1" in e for e in events)

    def test_finish_rejected_event(self) -> None:
        result = {"derived_snapshot": {"finish_rejections": 2}}
        events = extract_notable_events(result)
        assert any("finish rejections" in e for e in events)

    def test_duplicate_tool_event(self) -> None:
        result = {"state": {"retry_counts": {"duplicate_tool": 3}}}
        events = extract_notable_events(result)
        assert any("duplicate" in e for e in events)

    def test_content_validation_event(self) -> None:
        result = {"state": {"retry_counts": {"content_validation": 1}}}
        events = extract_notable_events(result)
        assert any("content validation" in e for e in events)

    def test_context_cleared_event(self) -> None:
        result = {"state": {"context_clear_requested": True}}
        events = extract_notable_events(result)
        assert "context cleared" in events

    def test_clarify_event(self) -> None:
        result = {"answer": "__CLARIFY__: What format?"}
        events = extract_notable_events(result)
        assert "clarify action emitted" in events

    def test_non_dict_findings_ignored(self) -> None:
        result = {"audit_report": {"findings": ["not a dict", 42]}}
        events = extract_notable_events(result)
        assert events == []

    def test_with_explicit_retry_counts(self) -> None:
        result = {}
        events = extract_notable_events(result, retry_counts={"finish_rejected": 1, "duplicate_tool": 0, "content_validation": 0})
        assert any("finish" in e for e in events)


class TestRenderNotableEventsPanel(unittest.TestCase):
    def test_no_events_shows_none(self) -> None:
        text = render_notable_events_panel([])
        assert "<none>" in text
        assert "NOTABLE EVENTS" in text

    def test_events_listed(self) -> None:
        text = render_notable_events_panel(["event A", "event B"])
        assert "event A" in text
        assert "event B" in text


class TestCollectPipelineTrace(unittest.TestCase):
    def test_empty_result(self) -> None:
        assert collect_pipeline_trace({}) == []

    def test_trace_extracted(self) -> None:
        result = {
            "state": {
                "policy_flags": {
                    "pipeline_trace": [
                        {"stage": "parser", "step": 1},
                        {"stage": "tool_exec", "step": 2},
                        "not_a_dict",  # should be filtered
                    ]
                }
            }
        }
        trace = collect_pipeline_trace(result)
        assert len(trace) == 2
        assert trace[0]["stage"] == "parser"


class TestRenderSpecialistRouting(unittest.TestCase):
    def test_executor_routing_printed(self) -> None:
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            render_specialist_routing(specialist="executor", tool="sort_array", mission_id=1)
        output = buf.getvalue()
        assert "EXECUTOR" in output
        assert "sort_array" in output
        assert "mission=1" in output

    def test_unknown_specialist_no_color(self) -> None:
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            render_specialist_routing(specialist="unknown", tool="my_tool", mission_id=2, status="done")
        output = buf.getvalue()
        assert "UNKNOWN" in output
        assert "done" in output


class TestRenderMissionStatusPanel(unittest.TestCase):
    def test_empty_reports(self) -> None:
        text = render_mission_status_panel([])
        assert "Mission Status" in text

    def test_completed_mission(self) -> None:
        reports = [{"mission_id": 1, "mission": "Sort the data", "status": "completed"}]
        text = render_mission_status_panel(reports)
        assert "+" in text
        assert "Sort the data" in text

    def test_failed_mission(self) -> None:
        reports = [{"mission_id": 1, "mission": "Write file", "status": "failed"}]
        text = render_mission_status_panel(reports)
        assert "x" in text
        assert "[fail]" in text

    def test_pending_mission(self) -> None:
        reports = [{"mission_id": 1, "mission": "Compute fib", "status": "pending"}]
        text = render_mission_status_panel(reports)
        assert "-" in text
        assert "[pend]" in text

    def test_deduplication_by_mission_id(self) -> None:
        reports = [
            {"mission_id": 1, "mission": "Task 1", "status": "pending"},
            {"mission_id": 1, "mission": "Task 1", "status": "completed"},
        ]
        text = render_mission_status_panel(reports)
        # Should show only 1 row (last occurrence wins)
        assert text.count("Task 1") == 1
        assert "+" in text  # completed icon

    def test_long_mission_text_truncated(self) -> None:
        long_text = "A" * 50
        reports = [{"mission_id": 1, "mission": long_text, "status": "completed"}]
        text = render_mission_status_panel(reports)
        assert "A" * 26 in text  # truncated to 26 chars
        assert "A" * 27 not in text


class TestRenderPipelineTracePanel(unittest.TestCase):
    def test_empty_trace(self) -> None:
        text = render_pipeline_trace_panel([])
        assert "PIPELINE TRACE" in text
        assert "<no trace events>" in text

    def test_parser_stage(self) -> None:
        events = [{"stage": "parser", "step": 1, "method": "json", "step_count": 3, "flat_count": 0}]
        text = render_pipeline_trace_panel(events)
        assert "PARSER" in text
        assert "method=json" in text

    def test_planner_output_stage(self) -> None:
        events = [{"stage": "planner_output", "step": 2, "source": "llm", "action_type": "tool", "tool_name": "sort_array", "mission_id": 1}]
        text = render_pipeline_trace_panel(events)
        assert "PLANNER" in text
        assert "src=llm" in text

    def test_planner_retry_stage(self) -> None:
        events = [{"stage": "planner_retry", "step": 3, "reason": "invalid_json", "retry_count": 2}]
        text = render_pipeline_trace_panel(events)
        assert "RETRY" in text
        assert "reason=invalid_json" in text

    def test_specialist_route_stage(self) -> None:
        events = [{"stage": "specialist_route", "step": 4, "specialist": "executor", "tool_name": "write_file", "mission_id": 2}]
        text = render_pipeline_trace_panel(events)
        assert "SPECIALIST" in text
        assert "specialist=executor" in text

    def test_tool_exec_stage_no_error(self) -> None:
        events = [{"stage": "tool_exec", "step": 5, "tool": "sort_array", "has_error": False, "result_keys": ["sorted"], "mission_id": 1}]
        text = render_pipeline_trace_panel(events)
        assert "TOOL" in text
        assert "sort_array" in text

    def test_tool_exec_stage_with_error(self) -> None:
        events = [{"stage": "tool_exec", "step": 5, "tool": "write_file", "has_error": True, "result_keys": [], "mission_id": 1}]
        text = render_pipeline_trace_panel(events)
        assert "ERR" in text

    def test_validator_fail_stage(self) -> None:
        events = [{"stage": "validator_fail", "step": 6, "tool": "write_file", "retry_count": 1, "reason": "wrong length"}]
        text = render_pipeline_trace_panel(events)
        assert "VALIDATOR FAIL" in text
        assert "wrong length" in text

    def test_validator_pass_stage(self) -> None:
        events = [{"stage": "validator_pass", "step": 7, "tool": "write_file", "check": "fib_len"}]
        text = render_pipeline_trace_panel(events)
        assert "VALIDATOR OK" in text
        assert "fib_len" in text

    def test_mission_complete_stage(self) -> None:
        events = [{"stage": "mission_complete", "step": 8, "mission_id": 1, "mission_preview": "Sort data"}]
        text = render_pipeline_trace_panel(events)
        assert "MISSION DONE" in text
        assert "Sort data" in text

    def test_loop_state_stage(self) -> None:
        events = [{"stage": "loop_state", "step": 9, "queue_depth": 2, "completed_count": 1, "total_count": 3, "timeout_mode": False}]
        text = render_pipeline_trace_panel(events)
        assert "LOOP" in text
        assert "queue=2" in text

    def test_unknown_stage_fallback(self) -> None:
        events = [{"stage": "custom_stage", "step": 10, "detail": "something"}]
        text = render_pipeline_trace_panel(events)
        assert "CUSTOM_STAGE" in text


class TestWordWrap(unittest.TestCase):
    def test_short_text_single_line(self) -> None:
        assert _word_wrap("hello world", 50) == ["hello world"]

    def test_long_text_wraps(self) -> None:
        lines = _word_wrap("one two three four five", 10)
        assert len(lines) > 1
        for line in lines:
            assert len(line) <= 10

    def test_empty_string(self) -> None:
        assert _word_wrap("", 20) == [""]

    def test_single_long_word_not_broken(self) -> None:
        # Single word longer than width is kept as-is
        result = _word_wrap("superlongword", 5)
        assert result == ["superlongword"]


class TestRenderClarificationPanel(unittest.TestCase):
    def test_basic_question_no_missing(self) -> None:
        text = render_clarification_panel("What format do you want?", [])
        assert "Clarification Needed" in text
        assert "What format" in text

    def test_with_missing_items(self) -> None:
        text = render_clarification_panel("What do you need?", ["file_path", "encoding"])
        assert "Missing:" in text
        assert "file_path" in text
        assert "encoding" in text

    def test_long_question_wraps(self) -> None:
        long_q = "This is a very long question that should definitely be word-wrapped at some boundary in the panel rendering."
        text = render_clarification_panel(long_q, [])
        assert "Clarification Needed" in text
        assert "question" in text.lower()

    def test_more_than_four_missing_items_capped(self) -> None:
        missing = ["a", "b", "c", "d", "e", "f"]
        text = render_clarification_panel("Question?", missing)
        # Only first 4 shown
        assert "e" not in text.split("Missing:")[-1] or text.count("• e") == 0


class TestRenderContextWarningPanel(unittest.TestCase):
    def test_renders_scope_and_budget(self) -> None:
        text = render_context_warning_panel("run", budget_used=50_000, budget_total=200_000)
        assert "50k" in text
        assert "200k" in text
        assert "scope: run" in text
        assert "Context Reset" in text


class TestRenderStuckIndicator(unittest.TestCase):
    def test_renders_counts(self) -> None:
        text = render_stuck_indicator(3, 5)
        assert "3/5" in text
        assert "mission still pending" in text


if __name__ == "__main__":
    unittest.main()
