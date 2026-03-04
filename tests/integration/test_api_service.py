"""HTTP contract tests for the Agentic Workflows API.

Tests use ScriptedProvider for deterministic responses -- no live LLM calls.
All tests use httpx AsyncClient with ASGITransport against the real FastAPI app.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from typing import Any

import httpx
from fastapi import FastAPI

from agentic_workflows.api.routes import health, run, tools
from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
from agentic_workflows.storage.sqlite import SQLiteRunStore
from tests.conftest import ScriptedProvider


def _build_test_app(
    responses: list[dict[str, Any]] | None = None,
    tmp_dir: str | None = None,
) -> FastAPI:
    """Build a FastAPI app with a ScriptedProvider orchestrator for testing.

    State is set directly on the app (bypassing lifespan) because httpx
    ASGITransport does not trigger ASGI lifespan events.
    """
    if responses is None:
        responses = [
            {"action": "tool", "tool_name": "repeat_message", "args": {"message": "hello"}},
            {"action": "finish", "answer": "Test completed successfully."},
        ]

    provider = ScriptedProvider(responses=responses)
    orchestrator = LangGraphOrchestrator(provider=provider, max_steps=10)

    _tmp_dir = tmp_dir or tempfile.mkdtemp()
    run_store = SQLiteRunStore(db_path=f"{_tmp_dir}/test_runs.db")

    test_app = FastAPI(title="Test Agentic Workflows")
    test_app.include_router(health.router)
    test_app.include_router(tools.router)
    test_app.include_router(run.router)

    # Set state directly (lifespan not triggered by ASGITransport)
    test_app.state.orchestrator = orchestrator
    test_app.state.run_store = run_store
    test_app.state.active_streams = {}

    return test_app


def _parse_sse_events(response_text: str) -> list[dict[str, Any]]:
    """Parse SSE event stream text into a list of event dicts."""
    events: list[dict[str, Any]] = []
    for line in response_text.split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            data_str = line[len("data:"):].strip()
            if data_str:
                try:
                    events.append(json.loads(data_str))
                except json.JSONDecodeError:
                    pass
    return events


def _extract_run_id_from_events(events: list[dict[str, Any]]) -> str | None:
    """Extract run_id from SSE events."""
    for event in events:
        if "run_id" in event:
            return event["run_id"]
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_health() -> None:
    """GET /health returns 200 with status=ok, provider, tool_count > 0."""
    app = _build_test_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "provider" in data
    assert data["tool_count"] > 0


async def test_tools_list() -> None:
    """GET /tools returns 200 with list of {name, description} dicts, length > 0."""
    app = _build_test_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert "name" in data[0]
    assert "description" in data[0]


async def test_post_run_sse() -> None:
    """POST /run with valid input returns 200 with content-type text/event-stream.

    Response body must contain at least one node_end event and one run_complete event.
    """
    app = _build_test_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/run",
            json={"user_input": "Task 1: Repeat the message 'hello' using repeat_message."},
            timeout=60.0,
        )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")

    events = _parse_sse_events(resp.text)
    event_types = [e.get("type") for e in events]
    assert "node_end" in event_types, f"No node_end event found. Events: {event_types}"
    assert "run_complete" in event_types, f"No run_complete event found. Events: {event_types}"


async def test_get_run_completed() -> None:
    """After POST /run completes, GET /run/{id} returns status=completed with result."""
    app = _build_test_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # First, do a run
        resp = await client.post(
            "/run",
            json={"user_input": "Task 1: Repeat the message 'hello' using repeat_message."},
            timeout=60.0,
        )
        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        run_id = _extract_run_id_from_events(events)
        assert run_id is not None, f"Could not extract run_id from events: {events}"

        # Now fetch the run status
        status_resp = await client.get(f"/run/{run_id}")
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert data["status"] == "completed", f"Expected completed, got: {data}"
    assert data["result"] is not None


async def test_get_run_not_found() -> None:
    """GET /run/{nonexistent-id} returns 404."""
    app = _build_test_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/run/nonexistent-id-12345")
    assert resp.status_code == 404


async def test_get_run_stream_not_found() -> None:
    """GET /run/{nonexistent-id}/stream returns 404."""
    app = _build_test_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/run/nonexistent-id-12345/stream")
    assert resp.status_code == 404


async def test_post_run_invalid_body() -> None:
    """POST /run with empty body returns 422."""
    app = _build_test_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/run", json={})
    assert resp.status_code == 422


async def test_concurrent_runs() -> None:
    """3 concurrent POST /run requests all return 200 (no SQLite locked errors)."""
    # Each run needs its own provider responses since they are consumed sequentially
    responses = [
        {"action": "tool", "tool_name": "repeat_message", "args": {"message": "hello"}},
        {"action": "finish", "answer": "done"},
    ] * 3  # Repeat enough times for 3 runs

    app = _build_test_app(responses=responses)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        tasks = [
            client.post(
                "/run",
                json={"user_input": f"Task 1: Repeat message '{i}' using repeat_message."},
                timeout=120.0,
            )
            for i in range(3)
        ]
        results = await asyncio.gather(*tasks)

    statuses = [r.status_code for r in results]
    assert all(s == 200 for s in statuses), f"Not all requests succeeded: {statuses}"

    # Verify distinct run_ids
    run_ids = set()
    for r in results:
        events = _parse_sse_events(r.text)
        rid = _extract_run_id_from_events(events)
        if rid:
            run_ids.add(rid)
    assert len(run_ids) == 3, f"Expected 3 distinct run_ids, got {len(run_ids)}: {run_ids}"
