"""Error-event SSE fixture: stream contains a provider error."""

from __future__ import annotations

ERROR_RUN_ID = "pub_abc123errorrun"

ERROR_EVENTS: list[dict] = [
    {
        "type": "node_start",
        "tier": "ui",
        "node": "plan",
        "run_id": ERROR_RUN_ID,
        "timestamp": "2026-03-06T00:00:00+00:00",
    },
    {
        "type": "error",
        "tier": "ui",
        "run_id": ERROR_RUN_ID,
        "detail": "provider_error: Ollama HTTP 500 error",
        "timestamp": "2026-03-06T00:00:01+00:00",
    },
]
