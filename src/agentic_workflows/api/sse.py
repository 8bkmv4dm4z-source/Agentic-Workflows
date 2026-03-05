"""SSE event builder functions for the Agentic Workflows streaming API.

Each builder returns a plain dict ready for ``json.dumps``.
Events are split into two tiers:
  - **ui**: safe for end-user consumption (node lifecycle, completion, errors)
  - **debug**: internal detail (state diffs)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def make_node_start(node: str, run_id: str, model: str | None = None) -> dict[str, Any]:
    """Emit when a graph node begins execution."""
    evt: dict[str, Any] = {
        "type": "node_start",
        "tier": "ui",
        "node": node,
        "run_id": run_id,
        "timestamp": _now_iso(),
    }
    if model is not None:
        evt["model"] = model
    return evt


def make_node_end(
    node: str, run_id: str, updates: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Emit when a graph node finishes execution."""
    return {
        "type": "node_end",
        "tier": "ui",
        "node": node,
        "run_id": run_id,
        "updates": updates or {},
        "timestamp": _now_iso(),
    }


def make_run_complete(
    run_id: str, result: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Emit when the full run is done."""
    return {
        "type": "run_complete",
        "tier": "ui",
        "run_id": run_id,
        "result": result or {},
        "timestamp": _now_iso(),
    }


def make_state_diff(node: str, run_id: str, diff: dict[str, Any]) -> dict[str, Any]:
    """Emit a debug-tier state diff after a node mutates RunState."""
    return {
        "type": "state_diff",
        "tier": "debug",
        "node": node,
        "run_id": run_id,
        "diff": diff,
        "timestamp": _now_iso(),
    }


def make_error(run_id: str | None, detail: str) -> dict[str, Any]:
    """Emit when an unrecoverable error occurs during a run."""
    return {
        "type": "error",
        "tier": "ui",
        "run_id": run_id,
        "detail": detail,
        "timestamp": _now_iso(),
    }
