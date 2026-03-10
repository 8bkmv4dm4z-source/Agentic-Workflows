"""Parametrized contract tests for all registered tools (W3-10).

Verifies each tool has: name (str), description (str), callable execute(), execute({}) returns dict.
Stubs replaced with assertions in plan 07.2-04.
Extended with args_schema validation in plan 07.7-01.
"""

from __future__ import annotations

import os

import pytest

from agentic_workflows.orchestration.langgraph.checkpoint_store import SQLiteCheckpointStore
from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore
from agentic_workflows.orchestration.langgraph.tools_registry import build_tool_registry
from agentic_workflows.tools.base import Tool


def _build_all_tools() -> dict:
    os.makedirs(".tmp", exist_ok=True)
    memo = SQLiteMemoStore(":memory:")
    ck = SQLiteCheckpointStore(".tmp/test_contracts.db")
    return build_tool_registry(memo, checkpoint_store=ck)


_ALL_TOOLS = list(_build_all_tools().items())  # [(name, tool), ...]


@pytest.mark.parametrize("tool_name,tool", _ALL_TOOLS, ids=[t[0] for t in _ALL_TOOLS])
def test_tool_has_name(tool_name, tool):
    assert isinstance(tool.name, str) and len(tool.name) > 0, \
        f"Tool {tool_name!r}: name must be non-empty string, got {tool.name!r}"


@pytest.mark.parametrize("tool_name,tool", _ALL_TOOLS, ids=[t[0] for t in _ALL_TOOLS])
def test_tool_has_description(tool_name, tool):
    assert isinstance(tool.description, str) and len(tool.description) > 0, \
        f"Tool {tool_name!r}: description must be non-empty string"


@pytest.mark.parametrize("tool_name,tool", _ALL_TOOLS, ids=[t[0] for t in _ALL_TOOLS])
def test_tool_execute_is_callable(tool_name, tool):
    assert callable(tool.execute), \
        f"Tool {tool_name!r}: execute must be callable"


@pytest.mark.parametrize("tool_name,tool", _ALL_TOOLS, ids=[t[0] for t in _ALL_TOOLS])
def test_tool_execute_returns_dict_on_empty_args(tool_name, tool):
    try:
        result = tool.execute({})
        assert isinstance(result, dict), \
            f"Tool {tool_name!r}: execute({{}}) returned {type(result).__name__}, expected dict"
    except Exception as exc:
        # Typed errors from the project hierarchy are acceptable
        from agentic_workflows.errors import AgenticWorkflowError
        assert isinstance(exc, (AgenticWorkflowError, KeyError, ValueError, TypeError)), \
            f"Tool {tool_name!r}: execute({{}}) raised unexpected {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# args_schema contract tests (07.7-01)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name,tool", _ALL_TOOLS, ids=[t[0] for t in _ALL_TOOLS])
def test_args_schema_non_empty(tool_name, tool):
    """Every registered tool must return a non-empty args_schema dict."""
    schema = tool.args_schema
    assert isinstance(schema, dict), \
        f"Tool {tool_name!r}: args_schema must be a dict, got {type(schema).__name__}"
    assert len(schema) > 0, \
        f"Tool {tool_name!r}: args_schema must be non-empty"


@pytest.mark.parametrize("tool_name,tool", _ALL_TOOLS, ids=[t[0] for t in _ALL_TOOLS])
def test_args_schema_values_have_type(tool_name, tool):
    """Every arg in args_schema must have at least a 'type' key."""
    schema = tool.args_schema
    for arg_name, meta in schema.items():
        assert isinstance(meta, dict), \
            f"Tool {tool_name!r}: args_schema[{arg_name!r}] must be a dict"
        assert "type" in meta, \
            f"Tool {tool_name!r}: args_schema[{arg_name!r}] must have 'type' key"


def test_args_schema_fallback_to_required_args():
    """A bare Tool subclass without _args_schema falls back to required_args()."""

    class BareSubclass(Tool):
        name = "bare_test"
        description = "Test tool. Required args: foo (str), bar (int)."

        def execute(self, args):
            return {}

    tool = BareSubclass()
    schema = tool.args_schema
    # required_args() should parse "foo" and "bar" from description
    assert "foo" in schema
    assert "bar" in schema
    # Fallback gives type="string" for all
    assert schema["foo"] == {"type": "string"}
    assert schema["bar"] == {"type": "string"}
