"""Parametrized contract tests for all registered tools (W3-10).

Verifies each tool has: name (str), description (str), callable execute(), execute({}) returns dict.
Stubs replaced with assertions in plan 07.2-04.
"""

from __future__ import annotations

import pytest

from agentic_workflows.orchestration.langgraph.checkpoint_store import SQLiteCheckpointStore
from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore
from agentic_workflows.orchestration.langgraph.tools_registry import build_tool_registry


def _build_all_tools() -> dict:
    memo = SQLiteMemoStore(":memory:")
    ck = SQLiteCheckpointStore(".tmp/test_contracts.db")
    return build_tool_registry(memo, checkpoint_store=ck)


_ALL_TOOLS = list(_build_all_tools().items())  # [(name, tool), ...]


@pytest.mark.parametrize("tool_name,tool", _ALL_TOOLS, ids=[t[0] for t in _ALL_TOOLS])
def test_tool_has_name(tool_name, tool):
    pytest.fail("MISSING — implement in plan 07.2-04")


@pytest.mark.parametrize("tool_name,tool", _ALL_TOOLS, ids=[t[0] for t in _ALL_TOOLS])
def test_tool_has_description(tool_name, tool):
    pytest.fail("MISSING — implement in plan 07.2-04")


@pytest.mark.parametrize("tool_name,tool", _ALL_TOOLS, ids=[t[0] for t in _ALL_TOOLS])
def test_tool_execute_is_callable(tool_name, tool):
    pytest.fail("MISSING — implement in plan 07.2-04")


@pytest.mark.parametrize("tool_name,tool", _ALL_TOOLS, ids=[t[0] for t in _ALL_TOOLS])
def test_tool_execute_returns_dict_on_empty_args(tool_name, tool):
    pytest.fail("MISSING — implement in plan 07.2-04")
