"""Tests for tool output schema validation."""

from __future__ import annotations

import pytest

from agentic_workflows.tools import output_schemas  # noqa: E402
from agentic_workflows.tools.output_schemas import validate_tool_output  # noqa: E402

# ---------------------------------------------------------------------------
# Passthrough / bypass
# ---------------------------------------------------------------------------


class TestPassthrough:
    def test_unregistered_tool_passes_through(self):
        raw = {"foo": "bar", "extra": 123}
        assert validate_tool_output("unknown_tool", raw) is raw

    def test_error_result_skips_validation(self):
        raw = {"error": "something broke"}
        assert validate_tool_output("write_file", raw) is raw

    def test_error_result_with_extra_fields_skips(self):
        raw = {"error": "bad path", "hint": "check permissions"}
        assert validate_tool_output("write_file", raw) is raw


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------


class TestWriteFile:
    def test_valid_write_file(self):
        raw = {"result": "Successfully wrote 42 characters to out.txt", "path": "/tmp/out.txt"}
        out = validate_tool_output("write_file", raw)
        assert out == raw

    def test_extra_field_rejected_failopen(self):
        raw = {"result": "ok", "path": "/tmp/x", "bonus": True}
        out = validate_tool_output("write_file", raw)
        # fail-open: returns original
        assert out == raw


# ---------------------------------------------------------------------------
# sort_array
# ---------------------------------------------------------------------------


class TestSortArray:
    def test_valid_sort_array(self):
        raw = {"sorted": [1, 2, 3], "count": 3, "order": "asc", "original": [3, 1, 2]}
        out = validate_tool_output("sort_array", raw)
        assert out == raw

    def test_empty_sort_array(self):
        raw = {"sorted": [], "count": 0, "order": "asc", "original": []}
        out = validate_tool_output("sort_array", raw)
        assert out == raw


# ---------------------------------------------------------------------------
# repeat_message
# ---------------------------------------------------------------------------


class TestEcho:
    def test_valid_echo(self):
        raw = {"echo": "hello world"}
        out = validate_tool_output("repeat_message", raw)
        assert out == raw


# ---------------------------------------------------------------------------
# math_stats
# ---------------------------------------------------------------------------


class TestMathStats:
    def test_valid_int_result(self):
        raw = {"result": 42}
        out = validate_tool_output("math_stats", raw)
        assert out == raw

    def test_valid_float_result(self):
        raw = {"result": 3.14}
        out = validate_tool_output("math_stats", raw)
        assert out == raw


# ---------------------------------------------------------------------------
# data_analysis — polymorphic dispatch
# ---------------------------------------------------------------------------


class TestDataAnalysis:
    def test_summary_stats(self):
        raw = {
            "count": 3, "sum": 6.0, "mean": 2.0, "median": 2.0,
            "stdev": 0.816497, "min": 1.0, "max": 3.0, "range": 2.0,
        }
        out = validate_tool_output("data_analysis", raw, {"operation": "summary_stats"})
        assert out["count"] == 3

    def test_outliers(self):
        raw = {
            "outliers": [100.0], "non_outliers": [1.0, 2.0, 3.0],
            "q1": 1.5, "q3": 2.5, "iqr": 1.0,
            "lower_bound": 0.0, "upper_bound": 4.0, "threshold": 1.5,
        }
        out = validate_tool_output("data_analysis", raw, {"operation": "outliers"})
        assert out["outliers"] == [100.0]

    def test_percentiles(self):
        raw = {"p10": 1.0, "p25": 2.0, "p50": 3.0, "p75": 4.0, "p90": 5.0, "p95": 5.5, "p99": 5.9}
        out = validate_tool_output("data_analysis", raw, {"operation": "percentiles"})
        assert out["p50"] == 3.0

    def test_correlation(self):
        raw = {"correlation": 0.95}
        out = validate_tool_output("data_analysis", raw, {"operation": "correlation"})
        assert out["correlation"] == 0.95

    def test_normalize(self):
        raw = {"normalized": [0.0, 0.5, 1.0]}
        out = validate_tool_output("data_analysis", raw, {"operation": "normalize"})
        assert out["normalized"] == [0.0, 0.5, 1.0]

    def test_z_scores(self):
        raw = {"z_scores": [-1.0, 0.0, 1.0]}
        out = validate_tool_output("data_analysis", raw, {"operation": "z_scores"})
        assert out["z_scores"] == [-1.0, 0.0, 1.0]

    def test_distribution(self):
        raw = {"bins": [{"range": "0-1", "count": 5}], "bin_width": 1.0}
        out = validate_tool_output("data_analysis", raw, {"operation": "distribution"})
        assert out["bins"][0]["count"] == 5

    def test_unknown_operation_passes_through(self):
        raw = {"custom_field": True}
        out = validate_tool_output("data_analysis", raw, {"operation": "nonexistent"})
        assert out is raw

    def test_no_args_passes_through(self):
        raw = {"some": "data"}
        out = validate_tool_output("data_analysis", raw)
        assert out is raw


# ---------------------------------------------------------------------------
# Strict mode
# ---------------------------------------------------------------------------


class TestStrictMode:
    def test_strict_raises_on_mismatch(self, monkeypatch):
        # Reset cached strict flag
        monkeypatch.setattr(output_schemas, "_strict_mode", None)
        monkeypatch.setenv("P1_TOOL_OUTPUT_SCHEMA_STRICT", "1")
        bad = {"result": "ok", "path": "/tmp/x", "bonus": True}
        with pytest.raises(ValueError, match="schema mismatch"):
            validate_tool_output("write_file", bad)
        # Restore
        monkeypatch.setattr(output_schemas, "_strict_mode", None)

    def test_strict_off_returns_original(self, monkeypatch):
        monkeypatch.setattr(output_schemas, "_strict_mode", None)
        monkeypatch.setenv("P1_TOOL_OUTPUT_SCHEMA_STRICT", "0")
        bad = {"result": "ok", "path": "/tmp/x", "bonus": True}
        out = validate_tool_output("write_file", bad)
        assert out == bad
        monkeypatch.setattr(output_schemas, "_strict_mode", None)
