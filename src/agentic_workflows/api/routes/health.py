"""Health check route."""

from __future__ import annotations

import os

from fastapi import APIRouter, Request

from agentic_workflows.api.models import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Return service health, active provider, and loaded tool count."""
    orchestrator = request.app.state.orchestrator
    return HealthResponse(
        status="ok",
        provider=os.environ.get("P1_PROVIDER", "unknown"),
        tool_count=len(orchestrator.tools),
    )
