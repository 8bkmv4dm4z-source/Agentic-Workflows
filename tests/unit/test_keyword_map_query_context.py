"""Unit tests for keyword map additions and supervisor few-shot for query_context."""

from __future__ import annotations

from pathlib import Path

from agentic_workflows.orchestration.langgraph.mission_parser import _TOOL_KEYWORD_MAP


def test_prior_maps_to_query_context():
    assert "query_context" in _TOOL_KEYWORD_MAP["prior"]


def test_recall_maps_to_query_context():
    assert "query_context" in _TOOL_KEYWORD_MAP["recall"]


def test_remember_maps_to_query_context():
    assert "query_context" in _TOOL_KEYWORD_MAP["remember"]


def test_previous_contains_both_tools():
    """'previous' keyword must map to BOTH retrieve_run_context AND query_context."""
    previous = _TOOL_KEYWORD_MAP["previous"]
    assert "retrieve_run_context" in previous
    assert "query_context" in previous


def test_supervisor_few_shot_contains_query_context():
    """supervisor.md FEW_SHOT section includes query_context example."""
    supervisor_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "agentic_workflows"
        / "directives"
        / "supervisor.md"
    )
    content = supervisor_path.read_text()
    assert "query_context" in content
    assert "FEW_SHOT" in content
