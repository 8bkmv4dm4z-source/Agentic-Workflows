"""Eval harness: deterministic ScriptedProvider scenarios through the FastAPI API.

All tests use httpx AsyncClient with ASGITransport -- zero live LLM calls.
Scenarios verify end-to-end correctness of POST /run SSE streaming and
GET /run/{id} status retrieval.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any


def _parse_sse_events(response_text: str) -> list[dict[str, Any]]:
    """Parse SSE event stream text into a list of event dicts."""
    events: list[dict[str, Any]] = []
    for line in response_text.split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            data_str = line[len("data:"):].strip()
            if data_str:
                with contextlib.suppress(json.JSONDecodeError):
                    events.append(json.loads(data_str))
    return events


def _extract_run_id(events: list[dict[str, Any]]) -> str | None:
    """Extract run_id from the first event that contains one."""
    for event in events:
        if "run_id" in event:
            return event["run_id"]
    return None


async def test_eval_simple_mission(simple_client) -> None:
    """Single mission completes with run_complete SSE and GET /run/{id} shows completed."""
    async with simple_client as client:
        # POST /run
        resp = await client.post(
            "/run",
            json={"user_input": "Task 1: Write hello world to /tmp/eval_hello.txt using write_file."},
            timeout=60.0,
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        events = _parse_sse_events(resp.text)
        event_types = [e.get("type") for e in events]
        assert "run_complete" in event_types, f"Missing run_complete. Got: {event_types}"

        run_id = _extract_run_id(events)
        assert run_id is not None, "No run_id in SSE events"

        # GET /run/{id} -- verify completed status
        status_resp = await client.get(f"/run/{run_id}")
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["status"] == "completed", f"Expected completed, got: {data['status']}"
        assert len(data.get("mission_reports", [])) >= 1, "Expected at least 1 mission report"


async def test_eval_multi_mission(multi_client) -> None:
    """Multi-mission workload produces mission_reports for all missions."""
    async with multi_client as client:
        resp = await client.post(
            "/run",
            json={
                "user_input": (
                    "Task 1: Repeat the message 'mission one' using repeat_message.\n"
                    "Task 2: Repeat the message 'mission two' using repeat_message."
                ),
            },
            timeout=60.0,
        )
        assert resp.status_code == 200

        events = _parse_sse_events(resp.text)
        event_types = [e.get("type") for e in events]
        assert "run_complete" in event_types, f"Missing run_complete. Got: {event_types}"

        run_id = _extract_run_id(events)
        assert run_id is not None

        status_resp = await client.get(f"/run/{run_id}")
        data = status_resp.json()
        assert data["status"] == "completed"
        # Multi-mission: expect at least 2 mission reports
        mission_reports = data.get("mission_reports", [])
        assert len(mission_reports) >= 2, (
            f"Expected >= 2 mission reports, got {len(mission_reports)}: {mission_reports}"
        )


async def test_eval_tool_chain(chain_client) -> None:
    """Chained tool calls (data_analysis -> sort_array) appear in correct order."""
    async with chain_client as client:
        resp = await client.post(
            "/run",
            json={
                "user_input": (
                    "Task 1: Analyse the data [5,3,8,1,9,2] with data_analysis "
                    "then sort it with sort_array in ascending order."
                ),
            },
            timeout=60.0,
        )
        assert resp.status_code == 200

        events = _parse_sse_events(resp.text)
        event_types = [e.get("type") for e in events]
        assert "run_complete" in event_types, f"Missing run_complete. Got: {event_types}"

        run_id = _extract_run_id(events)
        assert run_id is not None

        status_resp = await client.get(f"/run/{run_id}")
        data = status_resp.json()
        assert data["status"] == "completed"

        # Verify tool_history ordering from the result
        result = data.get("result", {})
        tools_used = result.get("tools_used", [])
        tool_names = [
            t["tool"] if isinstance(t, dict) else str(t)
            for t in tools_used
        ]
        # data_analysis must appear before sort_array
        assert "data_analysis" in tool_names, f"data_analysis not in tools: {tool_names}"
        assert "sort_array" in tool_names, f"sort_array not in tools: {tool_names}"
        da_idx = tool_names.index("data_analysis")
        sa_idx = tool_names.index("sort_array")
        assert da_idx < sa_idx, (
            f"data_analysis (idx {da_idx}) should appear before sort_array (idx {sa_idx})"
        )
