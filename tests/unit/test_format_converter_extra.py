"""Extra coverage for FormatConverterTool — YAML/TOML/INI/CSV edge cases."""
from __future__ import annotations

import json

from agentic_workflows.tools.format_converter import FormatConverterTool

tool = FormatConverterTool()


def execute(**kwargs):
    return tool.execute(kwargs)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_unsupported_to_format():
    r = execute(content='{"a": 1}', to_format="xml")
    assert "error" in r


def test_empty_content_whitespace():
    r = execute(content="   ", to_format="json")
    assert "error" in r


def test_unsupported_from_format():
    r = execute(content='{"a": 1}', from_format="xml", to_format="json")
    assert "error" in r


def test_autodetect_cannot_detect():
    r = execute(content="just plain text without structure", to_format="json")
    assert "error" in r


# ---------------------------------------------------------------------------
# YAML parsing edge cases
# ---------------------------------------------------------------------------

def test_yaml_bool_true():
    r = execute(content="active: true\n", from_format="yaml", to_format="json")
    assert "result" in r
    assert json.loads(r["result"])["active"] is True


def test_yaml_bool_false():
    r = execute(content="active: false\n", from_format="yaml", to_format="json")
    assert json.loads(r["result"])["active"] is False


def test_yaml_null():
    r = execute(content="value: null\n", from_format="yaml", to_format="json")
    assert json.loads(r["result"])["value"] is None


def test_yaml_tilde_null():
    r = execute(content="value: ~\n", from_format="yaml", to_format="json")
    assert json.loads(r["result"])["value"] is None


def test_yaml_integer():
    r = execute(content="count: 42\n", from_format="yaml", to_format="json")
    assert json.loads(r["result"])["count"] == 42


def test_yaml_float():
    r = execute(content="ratio: 3.14\n", from_format="yaml", to_format="json")
    assert abs(json.loads(r["result"])["ratio"] - 3.14) < 0.001


def test_yaml_double_quoted_string():
    r = execute(content='name: "Alice"\n', from_format="yaml", to_format="json")
    assert json.loads(r["result"])["name"] == "Alice"


def test_yaml_single_quoted_string():
    r = execute(content="name: 'Bob'\n", from_format="yaml", to_format="json")
    assert json.loads(r["result"])["name"] == "Bob"


def test_yaml_comment_ignored():
    r = execute(content="# comment\nname: Alice\n", from_format="yaml", to_format="json")
    parsed = json.loads(r["result"])
    assert parsed["name"] == "Alice"
    assert "comment" not in parsed


def test_yaml_line_without_colon_ignored():
    r = execute(content="name: Alice\njust_a_word\n", from_format="yaml", to_format="json")
    assert "result" in r


# ---------------------------------------------------------------------------
# YAML emit — list and dict outputs
# ---------------------------------------------------------------------------

def test_yaml_emit_list():
    json_list = '[{"a": 1}, {"b": 2}]'
    r = execute(content=json_list, from_format="json", to_format="yaml")
    assert "result" in r
    assert "-" in r["result"]


def test_yaml_emit_dict_with_null():
    r = execute(content='{"x": null}', from_format="json", to_format="yaml")
    assert "null" in r["result"]


def test_yaml_emit_dict_with_bool():
    r = execute(content='{"flag": true}', from_format="json", to_format="yaml")
    assert "true" in r["result"]


def test_yaml_emit_scalar_fallback():
    # Non-dict/list data emitted as string
    r = execute(content='"just a string"', from_format="json", to_format="yaml")
    assert "result" in r


# ---------------------------------------------------------------------------
# TOML → other
# ---------------------------------------------------------------------------

def test_toml_to_json():
    r = execute(content='title = "hello"\n', from_format="toml", to_format="json")
    assert "result" in r
    assert json.loads(r["result"])["title"] == "hello"


def test_toml_with_section_to_json():
    toml = '[author]\nname = "Alice"\n'
    r = execute(content=toml, from_format="toml", to_format="json")
    parsed = json.loads(r["result"])
    assert parsed["author"]["name"] == "Alice"


def test_toml_to_yaml():
    r = execute(content='name = "Alice"\n', from_format="toml", to_format="yaml")
    assert "Alice" in r["result"]


# ---------------------------------------------------------------------------
# TOML emit edge cases
# ---------------------------------------------------------------------------

def test_toml_emit_bool():
    r = execute(content='{"flag": true, "off": false}', from_format="json", to_format="toml")
    assert "true" in r["result"]
    assert "false" in r["result"]


def test_toml_emit_none():
    r = execute(content='{"nothing": null}', from_format="json", to_format="toml")
    assert "result" in r


def test_toml_emit_sections():
    nested = '{"title": "app", "db": {"host": "localhost"}}'
    r = execute(content=nested, from_format="json", to_format="toml")
    assert "[db]" in r["result"]
    assert "localhost" in r["result"]


def test_toml_emit_non_dict_scalar():
    # _emit_toml with non-dict returns str(data)
    r = execute(content='"hello"', from_format="json", to_format="toml")
    assert "result" in r


# ---------------------------------------------------------------------------
# INI → other
# ---------------------------------------------------------------------------

def test_ini_to_yaml():
    ini = "[section]\nkey = value\n"
    r = execute(content=ini, from_format="ini", to_format="yaml")
    assert "result" in r


def test_ini_to_toml():
    ini = "[section]\nkey = value\n"
    r = execute(content=ini, from_format="ini", to_format="toml")
    assert "result" in r


# ---------------------------------------------------------------------------
# INI emit
# ---------------------------------------------------------------------------

def test_json_to_ini():
    nested = '{"section": {"host": "localhost", "port": "5432"}}'
    r = execute(content=nested, from_format="json", to_format="ini")
    assert "result" in r
    assert "section" in r["result"].lower()
    assert "localhost" in r["result"]


def test_ini_emit_non_dict_scalar():
    r = execute(content='"hello"', from_format="json", to_format="ini")
    assert "result" in r


# ---------------------------------------------------------------------------
# CSV emit from dict (single row)
# ---------------------------------------------------------------------------

def test_json_dict_to_csv():
    r = execute(content='{"name": "Alice", "age": 30}', from_format="json", to_format="csv")
    assert "result" in r
    assert "Alice" in r["result"]


def test_csv_non_list_non_dict_fallback():
    # When JSON is a scalar, CSV emit falls back to str(data)
    r = execute(content='"just a string"', from_format="json", to_format="csv")
    assert "result" in r


# ---------------------------------------------------------------------------
# Auto-detect format hints
# ---------------------------------------------------------------------------

def test_autodetect_csv_by_commas():
    csv = "a,b,c\n1,2,3\n"
    r = execute(content=csv, to_format="json")
    assert r.get("from_format") == "csv"
