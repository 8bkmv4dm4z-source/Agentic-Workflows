"""Tests for src/agentic_workflows/cli/user_run.py using httpx.MockTransport."""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import httpx
import pytest
from rich.console import Console

from tests.fixtures.sse_sequences.error_event import ERROR_EVENTS
from tests.fixtures.sse_sequences.happy_path import HAPPY_PATH_EVENTS, HAPPY_PATH_RUN_ID
from tests.fixtures.sse_sequences.reconnect import RECONNECT_EVENTS, RECONNECT_RUN_ID


def _build_sse_body(events: list[dict]) -> bytes:
    """Encode events as SSE wire format: data: {json}\\n\\n per event."""
    return b"".join(f"data: {json.dumps(e)}\n\n".encode() for e in events)


def _make_transport(events: list[dict]) -> httpx.MockTransport:
    """Build an httpx.MockTransport that returns the given SSE events."""
    body = _build_sse_body(events)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body,
        )

    return httpx.MockTransport(handler)


def _make_patched_client(events: list[dict]) -> httpx.AsyncClient:
    """Create an AsyncClient backed by MockTransport for the given SSE events."""
    transport = _make_transport(events)
    return httpx.AsyncClient(
        transport=transport,
        base_url="http://mock",
        timeout=10.0,
    )


@pytest.mark.asyncio
async def test_happy_path_render():
    """stream_run() renders node_start/node_end/run_complete and returns correct run_id."""
    import agentic_workflows.cli.user_run as user_run_mod

    buf = io.StringIO()
    test_console = Console(file=buf, highlight=False, markup=True)

    mock_client = _make_patched_client(HAPPY_PATH_EVENTS)

    with (
        patch.object(user_run_mod, "console", test_console),
        patch.object(user_run_mod, "API_BASE_URL", "http://mock"),
        patch("agentic_workflows.cli.user_run.httpx.AsyncClient", return_value=mock_client),
    ):
        run_id, answer = await user_run_mod.stream_run("test input")

    assert run_id == HAPPY_PATH_RUN_ID
    assert answer == "Task completed."
    output = buf.getvalue()
    # node_start and node_end should be rendered (shows node name)
    assert "plan" in output


@pytest.mark.asyncio
async def test_error_event_exit():
    """stream_run() with an error SSE event prints [bold red]ERROR and returns empty answer."""
    import agentic_workflows.cli.user_run as user_run_mod

    buf = io.StringIO()
    test_console = Console(file=buf, highlight=False, markup=True)

    mock_client = _make_patched_client(ERROR_EVENTS)

    with (
        patch.object(user_run_mod, "console", test_console),
        patch.object(user_run_mod, "API_BASE_URL", "http://mock"),
        patch("agentic_workflows.cli.user_run.httpx.AsyncClient", return_value=mock_client),
    ):
        run_id, answer = await user_run_mod.stream_run("test input")

    output = buf.getvalue()
    assert "ERROR" in output
    # answer should be empty since no run_complete event was sent
    assert answer == ""


@pytest.mark.asyncio
async def test_reconnect_stream_renders():
    """stream_run() with partial reconnect events (no initial node_start) renders without crashing."""
    import agentic_workflows.cli.user_run as user_run_mod

    buf = io.StringIO()
    test_console = Console(file=buf, highlight=False, markup=True)

    mock_client = _make_patched_client(RECONNECT_EVENTS)

    with (
        patch.object(user_run_mod, "console", test_console),
        patch.object(user_run_mod, "API_BASE_URL", "http://mock"),
        patch("agentic_workflows.cli.user_run.httpx.AsyncClient", return_value=mock_client),
    ):
        run_id, answer = await user_run_mod.stream_run("resume test")

    assert run_id == RECONNECT_RUN_ID
    output = buf.getvalue()
    # run_complete renders "Run Complete" panel
    assert "Resumed." in output or "Run Complete" in output
