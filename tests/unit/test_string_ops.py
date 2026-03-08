"""Tests for StringOpsTool — all operations and error paths."""
from __future__ import annotations

from agentic_workflows.tools.string_ops import StringOpsTool

tool = StringOpsTool()


def execute(op, text="hello world", **kwargs):
    return tool.execute({"operation": op, "text": text, **kwargs})


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def test_non_string_text():
    r = tool.execute({"operation": "uppercase", "text": 123})
    assert "error" in r


def test_unknown_operation():
    r = execute("explode")
    assert "error" in r
    assert "supported_operations" in r


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def test_uppercase():
    assert execute("uppercase", text="hello")["result"] == "HELLO"


def test_lowercase():
    assert execute("lowercase", text="HELLO")["result"] == "hello"


def test_reverse():
    assert execute("reverse", text="abc")["result"] == "cba"


def test_length():
    assert execute("length", text="hello")["result"] == 5


def test_length_empty():
    assert execute("length", text="")["result"] == 0


def test_trim():
    assert execute("trim", text="  hello  ")["result"] == "hello"


def test_count_words():
    assert execute("count_words", text="one two three")["result"] == 3


def test_count_words_empty():
    assert execute("count_words", text="")["result"] == 0


def test_replace():
    r = execute("replace", text="hello world", old="world", new="python")
    assert r["result"] == "hello python"


def test_replace_not_found():
    r = execute("replace", text="hello", old="xyz", new="abc")
    assert r["result"] == "hello"


def test_split_default():
    r = execute("split", text="a b c")
    assert r["result"] == ["a", "b", "c"]


def test_split_custom_delimiter():
    r = execute("split", text="a,b,c", delimiter=",")
    assert r["result"] == ["a", "b", "c"]


def test_startswith_true():
    assert execute("startswith", text="hello", prefix="hel")["result"] is True


def test_startswith_false():
    assert execute("startswith", text="hello", prefix="xyz")["result"] is False


def test_endswith_true():
    assert execute("endswith", text="hello", suffix="llo")["result"] is True


def test_endswith_false():
    assert execute("endswith", text="hello", suffix="xyz")["result"] is False


def test_contains_true():
    assert execute("contains", text="hello world", substring="world")["result"] is True


def test_contains_false():
    assert execute("contains", text="hello", substring="xyz")["result"] is False
