"""Tests for MemoizeTool."""
from __future__ import annotations

from agentic_workflows.tools.memoize import MemoizeTool

tool = MemoizeTool()


def execute(**kwargs):
    return tool.execute(kwargs)


def test_missing_key():
    r = execute(value="hello")
    assert "error" in r


def test_missing_value():
    r = execute(key="some_key")
    assert "error" in r


def test_write_and_read(tmp_path):
    p = tmp_path / "memo.txt"
    r = execute(key=str(p), value="hello world")
    assert "error" not in r
    assert "Successfully memoized" in r["result"]
    assert p.read_text() == "hello world"


def test_numeric_value(tmp_path):
    p = tmp_path / "memo.txt"
    r = execute(key=str(p), value=42)
    assert "error" not in r
    assert p.read_text() == "42"


def test_invalid_path():
    r = execute(key="/nonexistent_dir/deep/path/x.txt", value="data")
    assert "error" in r
