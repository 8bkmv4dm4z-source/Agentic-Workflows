"""Happy-path SSE fixture: full streaming run sequence."""

from __future__ import annotations

HAPPY_PATH_RUN_ID = "pub_abc123happypath"

HAPPY_PATH_EVENTS: list[dict] = [
    {
        "type": "node_start",
        "tier": "ui",
        "node": "plan",
        "run_id": HAPPY_PATH_RUN_ID,
        "timestamp": "2026-03-06T00:00:00+00:00",
    },
    {
        "type": "node_end",
        "tier": "ui",
        "node": "plan",
        "run_id": HAPPY_PATH_RUN_ID,
        "updates": {},
        "timestamp": "2026-03-06T00:00:01+00:00",
    },
    {
        "type": "node_start",
        "tier": "ui",
        "node": "tool",
        "run_id": HAPPY_PATH_RUN_ID,
        "timestamp": "2026-03-06T00:00:02+00:00",
    },
    {
        "type": "node_end",
        "tier": "ui",
        "node": "tool",
        "run_id": HAPPY_PATH_RUN_ID,
        "updates": {},
        "timestamp": "2026-03-06T00:00:03+00:00",
    },
    {
        "type": "node_start",
        "tier": "ui",
        "node": "plan",
        "run_id": HAPPY_PATH_RUN_ID,
        "timestamp": "2026-03-06T00:00:04+00:00",
    },
    {
        "type": "node_end",
        "tier": "ui",
        "node": "plan",
        "run_id": HAPPY_PATH_RUN_ID,
        "updates": {},
        "timestamp": "2026-03-06T00:00:05+00:00",
    },
    {
        "type": "run_complete",
        "tier": "ui",
        "run_id": HAPPY_PATH_RUN_ID,
        "result": {
            "answer": "Task completed.",
            "mission_report": [],
            "audit_report": None,
        },
        "timestamp": "2026-03-06T00:00:06+00:00",
    },
]
