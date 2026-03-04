"""Unit tests for Pydantic API models and SSE event builders."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentic_workflows.api.models import (
    HealthResponse,
    RunRequest,
    RunStatusResponse,
    ToolInfo,
)
from agentic_workflows.api.sse import (
    make_error,
    make_node_end,
    make_node_start,
    make_run_complete,
    make_state_diff,
)


# ---- RunRequest ----

def test_run_request_valid():
    req = RunRequest(user_input="hello")
    assert req.user_input == "hello"
    assert req.run_id is None
    assert req.prior_context is None


def test_run_request_extra_field_rejected():
    with pytest.raises(ValidationError):
        RunRequest(user_input="hello", surprise="boom")


# ---- RunStatusResponse ----

def test_run_status_response_defaults():
    resp = RunStatusResponse(run_id="r1", status="pending")
    assert resp.elapsed_s is None
    assert resp.missions_completed == 0
    assert resp.tools_used_so_far == []
    assert resp.result is None
    assert resp.audit_report is None
    assert resp.mission_reports == []


# ---- HealthResponse ----

def test_health_response():
    hr = HealthResponse(status="ok", provider="ollama", tool_count=12)
    assert hr.status == "ok"
    assert hr.provider == "ollama"
    assert hr.tool_count == 12


# ---- ToolInfo ----

def test_tool_info():
    ti = ToolInfo(name="search_files", description="Search files by pattern")
    assert ti.name == "search_files"


# ---- SSE event builders ----

def test_make_node_start():
    evt = make_node_start("plan", "run-1")
    assert evt["type"] == "node_start"
    assert evt["tier"] == "ui"
    assert evt["node"] == "plan"
    assert "timestamp" in evt


def test_make_node_end():
    evt = make_node_end("plan", "run-1", updates={"step": 2})
    assert evt["type"] == "node_end"
    assert evt["tier"] == "ui"
    assert evt["updates"] == {"step": 2}


def test_make_run_complete():
    evt = make_run_complete("run-1", result={"answer": "done"})
    assert evt["type"] == "run_complete"
    assert evt["tier"] == "ui"
    assert evt["result"] == {"answer": "done"}


def test_make_state_diff():
    evt = make_state_diff("execute", "run-1", diff={"step_count": 3})
    assert evt["type"] == "state_diff"
    assert evt["tier"] == "debug"


def test_make_error():
    evt = make_error("run-1", "something broke")
    assert evt["type"] == "error"
    assert evt["tier"] == "ui"
    assert evt["detail"] == "something broke"


def test_make_error_no_run_id():
    evt = make_error(None, "early failure")
    assert evt["run_id"] is None
