"""Tools listing route."""

from __future__ import annotations

from fastapi import APIRouter, Request

from agentic_workflows.api.models import ToolInfo

router = APIRouter()


@router.get("/tools", response_model=list[ToolInfo])
async def list_tools(request: Request) -> list[ToolInfo]:
    """Return metadata for every tool registered with the orchestrator."""
    orchestrator = request.app.state.orchestrator
    return [
        ToolInfo(
            name=tool_name,
            description=getattr(tool, "__doc__", None) or "",
        )
        for tool_name, tool in orchestrator.tools.items()
    ]
