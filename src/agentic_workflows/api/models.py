"""Pydantic v2 request/response models for the Agentic Workflows API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class RunRequest(BaseModel):
    """Request body for POST /runs."""

    model_config = ConfigDict(extra="forbid")

    user_input: str
    run_id: str | None = None
    prior_context: list[dict[str, Any]] | None = None


class RunStatusResponse(BaseModel):
    """Response body for GET /runs/{run_id} and run completion."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: Literal["pending", "running", "completed", "failed"]
    elapsed_s: float | None = None
    missions_completed: int = 0
    tools_used_so_far: list[str] = []
    result: dict[str, Any] | None = None
    audit_report: dict[str, Any] | None = None
    mission_reports: list[dict[str, Any]] = []


class HealthResponse(BaseModel):
    """Response body for GET /health."""

    model_config = ConfigDict(extra="forbid")

    status: str
    provider: str
    tool_count: int


class ToolInfo(BaseModel):
    """Single tool descriptor returned by GET /tools."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str


class SSEEvent(BaseModel):
    """Typed SSE event envelope."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["node_start", "node_end", "run_complete", "state_diff", "error"]
    data: dict[str, Any]


class ErrorResponse(BaseModel):
    """Standard error envelope."""

    model_config = ConfigDict(extra="forbid")

    error: str
    run_id: str | None = None
    detail: str | None = None
