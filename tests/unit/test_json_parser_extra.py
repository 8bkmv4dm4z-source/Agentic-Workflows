"""Extra coverage for JsonParserTool — all operations and edge cases."""
from __future__ import annotations

from agentic_workflows.tools.json_parser import JsonParserTool

tool = JsonParserTool()


def execute(text, op, **kwargs):
    return tool.execute({"text": text, "operation": op, **kwargs})


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_missing_text():
    r = tool.execute({"operation": "parse"})
    assert "error" in r


def test_missing_operation():
    r = tool.execute({"text": "{}"})
    assert "error" in r


def test_unknown_operation():
    r = execute("{}", "nope")
    assert "error" in r


def test_invalid_json_non_validate():
    r = execute("{bad}", "parse")
    assert "error" in r


def test_invalid_json_validate():
    r = execute("{bad}", "validate")
    assert r["valid"] is False
    assert "error" in r


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------

def test_parse_object():
    r = execute('{"a": 1}', "parse")
    assert r["parsed"] == {"a": 1}


def test_parse_array():
    r = execute('[1, 2, 3]', "parse")
    assert r["parsed"] == [1, 2, 3]


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

def test_validate_no_schema():
    r = execute('{"a": 1}', "validate")
    assert r["valid"] is True
    assert r["type"] == "dict"


def test_validate_with_matching_schema():
    r = execute('{"a": 1, "b": 2}', "validate", schema={"a": None, "b": None})
    assert r["valid"] is True


def test_validate_with_missing_keys():
    r = execute('{"a": 1}', "validate", schema={"a": None, "b": None})
    assert r["valid"] is False
    assert "missing" in r["error"]


def test_validate_schema_type_mismatch():
    r = execute('[1, 2]', "validate", schema={"key": None})
    assert r["valid"] is False


def test_validate_non_dict_schema_no_check():
    r = execute('"hello"', "validate", schema="string")
    assert r["valid"] is True


# ---------------------------------------------------------------------------
# extract_keys
# ---------------------------------------------------------------------------

def test_extract_keys_from_dict():
    r = execute('{"x": 1, "y": 2}', "extract_keys")
    assert set(r["keys"]) == {"x", "y"}
    assert r["count"] == 2


def test_extract_keys_from_list_of_dicts():
    r = execute('[{"a": 1}, {"b": 2, "a": 3}]', "extract_keys")
    assert "a" in r["keys"]
    assert "b" in r["keys"]


def test_extract_keys_from_scalar():
    r = execute('"hello"', "extract_keys")
    assert r["keys"] == []
    assert r["count"] == 0


# ---------------------------------------------------------------------------
# flatten
# ---------------------------------------------------------------------------

def test_flatten_nested_dict():
    r = execute('{"a": {"b": {"c": 1}}}', "flatten")
    assert r["flattened"]["a.b.c"] == 1


def test_flatten_list():
    r = execute('[1, 2, 3]', "flatten")
    assert r["flattened"]["0"] == 1
    assert r["flattened"]["2"] == 3


def test_flatten_mixed():
    r = execute('{"items": [1, 2]}', "flatten")
    assert r["flattened"]["items.0"] == 1


# ---------------------------------------------------------------------------
# get_path
# ---------------------------------------------------------------------------

def test_get_path_dict():
    r = execute('{"user": {"name": "Alice"}}', "get_path", path="user.name")
    assert r["value"] == "Alice"
    assert r["found"] is True


def test_get_path_list_index():
    r = execute('[10, 20, 30]', "get_path", path="1")
    assert r["value"] == 20


def test_get_path_nested_list():
    r = execute('{"items": [1, 2, 3]}', "get_path", path="items.2")
    assert r["value"] == 3


def test_get_path_key_not_found():
    r = execute('{"a": 1}', "get_path", path="b")
    assert r["found"] is False
    assert "error" in r


def test_get_path_index_out_of_range():
    r = execute('[1, 2]', "get_path", path="5")
    assert r["found"] is False


def test_get_path_invalid_index():
    r = execute('[1, 2]', "get_path", path="abc")
    assert r["found"] is False


def test_get_path_traverse_into_scalar():
    r = execute('{"a": 1}', "get_path", path="a.b")
    assert r["found"] is False


def test_get_path_missing_path():
    r = execute('{"a": 1}', "get_path")
    assert "error" in r


# ---------------------------------------------------------------------------
# pretty_print
# ---------------------------------------------------------------------------

def test_pretty_print():
    r = execute('{"a":1}', "pretty_print")
    assert "pretty" in r
    assert "\n" in r["pretty"]


# ---------------------------------------------------------------------------
# count_elements
# ---------------------------------------------------------------------------

def test_count_dict():
    r = execute('{"a": 1, "b": 2}', "count_elements")
    assert r["count"] == 2
    assert r["type"] == "object"


def test_count_array():
    r = execute('[1, 2, 3, 4]', "count_elements")
    assert r["count"] == 4
    assert r["type"] == "array"


def test_count_scalar():
    r = execute('"hello"', "count_elements")
    assert r["count"] == 1
    assert r["type"] == "str"
