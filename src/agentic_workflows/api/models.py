"""Pydantic v2 request/response models for the Agentic Workflows API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ContextEntry(BaseModel):
    """A single prior-context message with role and content."""

    model_config = ConfigDict(extra="forbid")

    role: str = Field(description="Message role (e.g. 'user', 'assistant', 'system')")
    content: str = Field(description="Message content")


class RunRequest(BaseModel):
    """Request body for POST /run — start an orchestrator run."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"user_input": "Sort [3,1,2] and compute fibonacci(10)"},
                {"user_input": "Analyze the dataset [10, 20, 300, 25, 15]"},
            ]
        },
    )

    user_input: str = Field(
        min_length=2,
        max_length=8000,
        description="The natural-language task for the agent to execute",
    )
    prior_context: list[ContextEntry] = Field(
        default=[],
        max_length=50,
        description="Prior conversation messages for multi-turn context (max 50 entries)",
    )


class RunStatusResponse(BaseModel):
    """Response body for GET /run/{run_id} and run completion."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(description="Unique identifier for the run")
    status: Literal["pending", "running", "completed", "failed"] = Field(description="Current run status")
    elapsed_s: float | None = Field(default=None, description="Wall-clock seconds elapsed")
    missions_completed: int = Field(default=0, description="Number of missions finished so far")
    tools_used_so_far: list[str] = Field(default=[], description="Tool names invoked during the run")
    result: dict[str, Any] | None = Field(default=None, description="Full result payload (only when completed)")
    audit_report: dict[str, Any] | None = Field(default=None, description="Post-run audit report")
    mission_reports: list[dict[str, Any]] = Field(default=[], description="Per-mission execution reports")


class HealthResponse(BaseModel):
    """Response body for GET /health."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(description="Service status ('ok')")
    provider: str = Field(description="Active LLM provider name")
    tool_count: int = Field(description="Number of registered tools")


class ToolInfo(BaseModel):
    """Single tool descriptor returned by GET /tools."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Tool function name")
    description: str = Field(description="Tool docstring / purpose")


class SSEEvent(BaseModel):
    """Typed SSE event envelope sent during POST /run streaming."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["node_start", "node_end", "run_complete", "state_diff", "error"] = Field(
        description="Event category for client-side dispatch"
    )
    data: dict[str, Any] = Field(description="Event payload")


class ErrorResponse(BaseModel):
    """Standard error envelope returned on 4xx/5xx responses."""

    model_config = ConfigDict(extra="forbid")

    error: str = Field(description="Short error label")
    run_id: str | None = Field(default=None, description="Associated run ID, if applicable")
    detail: str | None = Field(default=None, description="Human-readable error details")


class RunSummary(BaseModel):
    """Summary row returned by GET /runs."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(description="Public run identifier")
    status: str = Field(description="Run status")
    created_at: datetime = Field(description="When the run was created")
    elapsed_s: float | None = Field(default=None, description="Wall-clock seconds if completed")
    missions_completed: int = Field(default=0, description="Missions finished")


class RunListResponse(BaseModel):
    """Paginated response for GET /runs."""

    model_config = ConfigDict(extra="forbid")

    items: list[RunSummary] = Field(description="Run summaries, newest first")
    next_cursor: str | None = Field(default=None, description="Cursor for next page; None if last page")
