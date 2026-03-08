"""Tests for ExtractTableTool — parse, column, filter, summary, and error paths."""
from __future__ import annotations

from agentic_workflows.tools.extract_table import ExtractTableTool

tool = ExtractTableTool()

CSV = "name,age,city\nAlice,30,NYC\nBob,25,LA\nCharlie,35,NYC\n"
TSV = "name\tage\nAlice\t30\nBob\t25\n"


def execute(**kwargs):
    return tool.execute(kwargs)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_invalid_operation():
    r = execute(text=CSV, operation="explode")
    assert "error" in r


def test_missing_text():
    r = execute(operation="parse")
    assert "error" in r


# ---------------------------------------------------------------------------
# parse / to_json
# ---------------------------------------------------------------------------

def test_parse_basic():
    r = execute(text=CSV, operation="parse")
    assert r["headers"] == ["name", "age", "city"]
    assert r["row_count"] == 3
    assert r["col_count"] == 3


def test_to_json_same_as_parse():
    r = execute(text=CSV, operation="to_json")
    assert r["headers"] == ["name", "age", "city"]
    assert r["row_count"] == 3


def test_parse_tsv():
    r = execute(text=TSV, operation="parse", delimiter="\t")
    assert r["headers"] == ["name", "age"]
    assert r["row_count"] == 2


def test_parse_no_header():
    r = execute(text="1,2,3\n4,5,6\n", operation="parse", has_header=False)
    assert r["headers"] == ["0", "1", "2"]
    assert r["row_count"] == 2


# ---------------------------------------------------------------------------
# column
# ---------------------------------------------------------------------------

def test_column_by_name():
    r = execute(text=CSV, operation="column", column="name")
    assert r["values"] == ["Alice", "Bob", "Charlie"]
    assert r["count"] == 3


def test_column_by_index():
    r = execute(text=CSV, operation="column", column=1)
    assert r["values"] == ["30", "25", "35"]


def test_column_missing_column_arg():
    r = execute(text=CSV, operation="column")
    assert "error" in r


def test_column_not_found_by_name():
    r = execute(text=CSV, operation="column", column="nonexistent")
    assert "error" in r


def test_column_index_out_of_range():
    r = execute(text=CSV, operation="column", column=99)
    assert "error" in r


# ---------------------------------------------------------------------------
# filter
# ---------------------------------------------------------------------------

def test_filter_match():
    r = execute(text=CSV, operation="filter", filter_col="city", filter_value="NYC")
    assert r["matched"] == 2
    assert all(row[2] == "NYC" for row in r["rows"])


def test_filter_no_match():
    r = execute(text=CSV, operation="filter", filter_col="city", filter_value="Boston")
    assert r["matched"] == 0
    assert r["rows"] == []


def test_filter_missing_filter_col():
    r = execute(text=CSV, operation="filter", filter_value="NYC")
    assert "error" in r


def test_filter_col_not_found():
    r = execute(text=CSV, operation="filter", filter_col="nonexistent", filter_value="x")
    assert "error" in r


def test_filter_by_index():
    r = execute(text=CSV, operation="filter", filter_col=2, filter_value="NYC")
    assert r["matched"] == 2


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------

def test_summary():
    r = execute(text=CSV, operation="summary")
    assert r["row_count"] == 3
    assert r["col_count"] == 3
    assert len(r["sample"]) <= 3
    assert r["headers"] == ["name", "age", "city"]


def test_summary_sample_truncated():
    big_csv = "a,b\n" + "\n".join(f"{i},{i}" for i in range(10))
    r = execute(text=big_csv, operation="summary")
    assert len(r["sample"]) == 3
