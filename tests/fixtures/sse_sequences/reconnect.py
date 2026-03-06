"""Reconnect SSE fixture: partial run state (post-reconnect events only)."""

from __future__ import annotations

RECONNECT_RUN_ID = "pub_abc123reconnect"

RECONNECT_EVENTS: list[dict] = [
    {
        "type": "node_end",
        "tier": "ui",
        "node": "tool",
        "run_id": RECONNECT_RUN_ID,
        "updates": {},
        "timestamp": "2026-03-06T00:00:10+00:00",
    },
    {
        "type": "run_complete",
        "tier": "ui",
        "run_id": RECONNECT_RUN_ID,
        "result": {"answer": "Resumed."},
        "timestamp": "2026-03-06T00:00:11+00:00",
    },
]
