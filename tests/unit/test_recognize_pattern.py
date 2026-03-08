"""Tests for RecognizePatternTool — regex and sequence patterns."""
from __future__ import annotations

from agentic_workflows.tools.recognize_pattern import RecognizePatternTool

tool = RecognizePatternTool()


def execute(text, pattern_types=None):
    args = {"text": text}
    if pattern_types is not None:
        args["pattern_types"] = pattern_types
    return tool.execute(args)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_non_string_text():
    r = tool.execute({"text": 123})
    assert "error" in r


def test_invalid_pattern_type():
    r = execute("hello", pattern_types=["explode"])
    assert "error" in r


def test_pattern_types_not_a_list():
    r = tool.execute({"text": "hello", "pattern_types": "email"})
    assert "error" in r


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def test_email_found():
    r = execute("Contact us at alice@example.com or bob@test.org", ["email"])
    assert "email" in r["patterns_found"]
    assert "alice@example.com" in r["patterns_found"]["email"]


def test_email_not_found():
    r = execute("no emails here", ["email"])
    assert "email" not in r["patterns_found"]


# ---------------------------------------------------------------------------
# URL
# ---------------------------------------------------------------------------

def test_url_found():
    r = execute("Visit https://example.com for details", ["url"])
    assert "url" in r["patterns_found"]


def test_url_not_found():
    r = execute("no urls here", ["url"])
    assert "url" not in r["patterns_found"]


# ---------------------------------------------------------------------------
# Date
# ---------------------------------------------------------------------------

def test_date_iso_found():
    r = execute("Event on 2024-06-15", ["date"])
    assert "date" in r["patterns_found"]
    assert "2024-06-15" in r["patterns_found"]["date"]


def test_date_slash_format():
    r = execute("Born on 01/15/1990", ["date"])
    assert "date" in r["patterns_found"]


# ---------------------------------------------------------------------------
# Phone
# ---------------------------------------------------------------------------

def test_phone_found():
    r = execute("Call 555-123-4567 now", ["phone"])
    assert "phone" in r["patterns_found"]


# ---------------------------------------------------------------------------
# IP address
# ---------------------------------------------------------------------------

def test_ip_found():
    r = execute("Server at 192.168.1.1", ["ip_address"])
    assert "ip_address" in r["patterns_found"]


def test_ip_not_found():
    r = execute("no ip here", ["ip_address"])
    assert "ip_address" not in r["patterns_found"]


# ---------------------------------------------------------------------------
# Hex color
# ---------------------------------------------------------------------------

def test_hex_color_found():
    r = execute("Color is #ff0000 and #abc", ["hex_color"])
    assert "hex_color" in r["patterns_found"]


def test_hex_color_not_found():
    r = execute("no color here", ["hex_color"])
    assert "hex_color" not in r["patterns_found"]


# ---------------------------------------------------------------------------
# Fibonacci sequence
# ---------------------------------------------------------------------------

def test_fibonacci_found():
    r = execute("1 1 2 3 5 8 13", ["fibonacci_sequence"])
    assert "fibonacci_sequence" in r["patterns_found"]


def test_fibonacci_too_short():
    r = execute("1 1", ["fibonacci_sequence"])
    assert "fibonacci_sequence" not in r["patterns_found"]


def test_fibonacci_not_present():
    # "3 5 7 9": differences are constant but 3+5≠7, 5+7≠9 — not fib-like
    r = execute("3 5 7 9 11", ["fibonacci_sequence"])
    assert "fibonacci_sequence" not in r["patterns_found"]


# ---------------------------------------------------------------------------
# Arithmetic sequence
# ---------------------------------------------------------------------------

def test_arithmetic_found():
    r = execute("2 4 6 8 10", ["arithmetic_sequence"])
    assert "arithmetic_sequence" in r["patterns_found"]


def test_arithmetic_not_found():
    r = execute("1 2 4 8", ["arithmetic_sequence"])
    assert "arithmetic_sequence" not in r["patterns_found"]


def test_arithmetic_too_short():
    r = execute("5 10", ["arithmetic_sequence"])
    assert "arithmetic_sequence" not in r["patterns_found"]


# ---------------------------------------------------------------------------
# Geometric sequence
# ---------------------------------------------------------------------------

def test_geometric_found():
    r = execute("2 4 8 16 32", ["geometric_sequence"])
    assert "geometric_sequence" in r["patterns_found"]


def test_geometric_not_found():
    r = execute("1 2 3 4 5", ["geometric_sequence"])
    assert "geometric_sequence" not in r["patterns_found"]


def test_geometric_too_short():
    r = execute("2 4", ["geometric_sequence"])
    assert "geometric_sequence" not in r["patterns_found"]


def test_geometric_zero_start_skipped():
    # A zero at the start can't anchor a geometric sequence
    r = execute("0 0 0 2 4 8", ["geometric_sequence"])
    # Either found starting at 2,4,8 or not found — no crash
    assert "error" not in r


# ---------------------------------------------------------------------------
# total_matches and checked_types
# ---------------------------------------------------------------------------

def test_total_matches_count():
    r = execute("alice@x.com bob@y.com", ["email"])
    assert r["total_matches"] == 2


def test_checked_types_returned():
    r = execute("hello", ["email", "url"])
    assert set(r["checked_types"]) == {"email", "url"}


def test_default_pattern_types():
    r = execute("alice@x.com")
    assert "email" in r["patterns_found"]
    assert "checked_types" in r
