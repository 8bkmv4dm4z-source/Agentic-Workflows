"""Eval-specific fixtures: deterministic ScriptedProvider scenarios through the API."""

from __future__ import annotations

import tempfile
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from agentic_workflows.api.routes import health, run, tools
from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
from agentic_workflows.storage.sqlite import SQLiteRunStore
from tests.conftest import ScriptedProvider


# ---------------------------------------------------------------------------
# ScriptedProvider response sequences
# ---------------------------------------------------------------------------

SIMPLE_MISSION_RESPONSES: list[dict[str, Any]] = [
    # Single mission: one tool call then finish
    {"action": "tool", "tool_name": "write_file", "args": {"path": "/tmp/eval_hello.txt", "content": "hello world"}},
    {"action": "finish", "answer": "Wrote hello world to /tmp/eval_hello.txt"},
]

MULTI_MISSION_RESPONSES: list[dict[str, Any]] = [
    # Mission 1: repeat a message
    {"action": "tool", "tool_name": "repeat_message", "args": {"message": "mission one"}},
    {"action": "finish", "answer": "Mission 1 complete: repeated 'mission one'"},
    # Mission 2: repeat another message
    {"action": "tool", "tool_name": "repeat_message", "args": {"message": "mission two"}},
    {"action": "finish", "answer": "Mission 2 complete: repeated 'mission two'"},
]

TOOL_CHAIN_RESPONSES: list[dict[str, Any]] = [
    # Chain: data_analysis -> sort_array
    {
        "action": "tool",
        "tool_name": "data_analysis",
        "args": {"data": [5, 3, 8, 1, 9, 2]},
    },
    {
        "action": "tool",
        "tool_name": "sort_array",
        "args": {"array": [5, 3, 8, 1, 9, 2], "order": "ascending"},
    },
    {"action": "finish", "answer": "Data analysed and sorted: [1, 2, 3, 5, 8, 9]"},
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_eval_app(
    responses: list[dict[str, Any]],
    tmp_dir: str | None = None,
) -> FastAPI:
    """Build a FastAPI app with ScriptedProvider for eval testing."""
    provider = ScriptedProvider(responses=responses)
    orchestrator = LangGraphOrchestrator(provider=provider, max_steps=15)

    _tmp_dir = tmp_dir or tempfile.mkdtemp()
    run_store = SQLiteRunStore(db_path=f"{_tmp_dir}/eval_runs.db")

    eval_app = FastAPI(title="Eval Agentic Workflows")
    eval_app.include_router(health.router)
    eval_app.include_router(tools.router)
    eval_app.include_router(run.router)

    eval_app.state.orchestrator = orchestrator
    eval_app.state.run_store = run_store
    eval_app.state.active_streams = {}

    return eval_app


@pytest.fixture
def simple_app(tmp_path):
    """App configured for single-mission eval scenario."""
    return _build_eval_app(SIMPLE_MISSION_RESPONSES, str(tmp_path))


@pytest.fixture
def multi_app(tmp_path):
    """App configured for multi-mission eval scenario."""
    return _build_eval_app(MULTI_MISSION_RESPONSES, str(tmp_path))


@pytest.fixture
def chain_app(tmp_path):
    """App configured for tool-chain eval scenario."""
    return _build_eval_app(TOOL_CHAIN_RESPONSES, str(tmp_path))


@pytest.fixture
def simple_client(simple_app):
    """httpx AsyncClient against simple_app."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=simple_app),
        base_url="http://eval",
    )


@pytest.fixture
def multi_client(multi_app):
    """httpx AsyncClient against multi_app."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=multi_app),
        base_url="http://eval",
    )


@pytest.fixture
def chain_client(chain_app):
    """httpx AsyncClient against chain_app."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=chain_app),
        base_url="http://eval",
    )
