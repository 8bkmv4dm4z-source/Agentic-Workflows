"""Tests for DateTimeOpsTool — all operations, error paths, and helpers."""
from __future__ import annotations

import pytest

from agentic_workflows.tools.datetime_ops import DateTimeOpsTool

tool = DateTimeOpsTool()


def execute(op, **kwargs):
    return tool.execute({"operation": op, **kwargs})


# ---------------------------------------------------------------------------
# Invalid operation
# ---------------------------------------------------------------------------

def test_invalid_operation():
    r = tool.execute({"operation": "explode"})
    assert "error" in r


def test_missing_operation():
    r = tool.execute({})
    assert "error" in r


# ---------------------------------------------------------------------------
# now
# ---------------------------------------------------------------------------

def test_now_returns_result():
    r = execute("now")
    assert "result" in r
    assert r["timezone"] == "UTC"
    assert r["operation"] == "now"


def test_now_format_is_iso():
    r = execute("now")
    from datetime import datetime
    # Should parse without error
    datetime.strptime(r["result"], "%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------

def test_parse_iso_datetime():
    r = execute("parse", dt="2024-06-15T10:30:00")
    assert "result" in r
    assert "2024-06-15" in r["result"]


def test_parse_space_separated():
    r = execute("parse", dt="2024-06-15 10:30:00")
    assert "result" in r


def test_parse_date_only():
    r = execute("parse", dt="2024-06-15")
    assert "result" in r


def test_parse_missing_dt():
    r = execute("parse")
    assert "error" in r


def test_parse_invalid_format():
    r = execute("parse", dt="not-a-date")
    assert "error" in r


# ---------------------------------------------------------------------------
# format
# ---------------------------------------------------------------------------

def test_format_custom():
    r = execute("format", dt="2024-06-15T10:30:00", fmt="%d/%m/%Y")
    assert r["result"] == "15/06/2024"


def test_format_missing_fmt():
    r = execute("format", dt="2024-06-15T10:30:00")
    assert "error" in r


def test_format_missing_dt():
    r = execute("format", fmt="%Y")
    assert "error" in r


# ---------------------------------------------------------------------------
# add / subtract
# ---------------------------------------------------------------------------

def test_add_days():
    r = execute("add", dt="2024-01-01T00:00:00", unit="days", amount=1)
    assert r["result"] == "2024-01-02T00:00:00"


def test_add_hours():
    r = execute("add", dt="2024-01-01T10:00:00", unit="hours", amount=2)
    assert r["result"] == "2024-01-01T12:00:00"


def test_add_minutes():
    r = execute("add", dt="2024-01-01T10:00:00", unit="minutes", amount=30)
    assert r["result"] == "2024-01-01T10:30:00"


def test_add_seconds():
    r = execute("add", dt="2024-01-01T10:00:00", unit="seconds", amount=90)
    assert r["result"] == "2024-01-01T10:01:30"


def test_subtract_days():
    r = execute("subtract", dt="2024-01-10T00:00:00", unit="days", amount=5)
    assert r["result"] == "2024-01-05T00:00:00"


def test_add_unknown_unit():
    r = execute("add", dt="2024-01-01T00:00:00", unit="years", amount=1)
    assert "error" in r


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------

def test_diff_seconds():
    r = execute("diff", dt="2024-01-01T00:00:00", dt2="2024-01-01T00:01:00", unit="seconds")
    assert r["result"] == pytest.approx(60.0)


def test_diff_minutes():
    r = execute("diff", dt="2024-01-01T00:00:00", dt2="2024-01-01T01:00:00", unit="minutes")
    assert r["result"] == pytest.approx(60.0)


def test_diff_hours():
    r = execute("diff", dt="2024-01-01T00:00:00", dt2="2024-01-02T00:00:00", unit="hours")
    assert r["result"] == pytest.approx(24.0)


def test_diff_days():
    r = execute("diff", dt="2024-01-01T00:00:00", dt2="2024-01-08T00:00:00", unit="days")
    assert r["result"] == pytest.approx(7.0)


def test_diff_default_unit():
    r = execute("diff", dt="2024-01-01T00:00:00", dt2="2024-01-01T00:00:30")
    assert r["result"] == pytest.approx(30.0)
    assert r["unit"] == "seconds"


# ---------------------------------------------------------------------------
# weekday
# ---------------------------------------------------------------------------

def test_weekday_monday():
    r = execute("weekday", dt="2024-01-01")  # Monday
    assert r["result"] == "Monday"
    assert r["weekday_index"] == 0


def test_weekday_sunday():
    r = execute("weekday", dt="2024-01-07")  # Sunday
    assert r["result"] == "Sunday"
    assert r["weekday_index"] == 6


# ---------------------------------------------------------------------------
# to_timestamp / from_timestamp
# ---------------------------------------------------------------------------

def test_to_timestamp():
    r = execute("to_timestamp", dt="2024-01-01T00:00:00")
    assert "result" in r
    assert isinstance(r["result"], float)


def test_from_timestamp():
    r = execute("from_timestamp", amount=0)
    assert "result" in r
    assert "1970-01-01" in r["result"]


def test_roundtrip_timestamp():
    ts_r = execute("to_timestamp", dt="2024-06-15T12:00:00")
    back = execute("from_timestamp", amount=ts_r["result"])
    assert "2024-06-15T12:00:00" in back["result"]
