"""FastAPI application for Agentic Workflows.

The graph is compiled once at startup via the lifespan context manager.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agentic_workflows.api.models import ErrorResponse
from agentic_workflows.api.routes import health, tools
from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
from agentic_workflows.storage.sqlite import SQLiteRunStore

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Compile the graph once and initialise storage at startup."""
    log.info("api.startup", status="compiling_graph")

    orchestrator = LangGraphOrchestrator()
    application.state.orchestrator = orchestrator

    run_store = SQLiteRunStore()
    application.state.run_store = run_store

    application.state.active_streams: dict = {}  # type: ignore[annotation-unchecked]

    tool_count = len(orchestrator.tools)
    log.info("api.startup", status="graph_compiled", tools=tool_count)

    yield

    run_store.close()
    log.info("api.shutdown", status="clean")


app = FastAPI(title="Agentic Workflows", lifespan=lifespan)

# ----- Routes -----
app.include_router(health.router)
app.include_router(tools.router)


# ----- Error handlers -----

@app.exception_handler(422)
async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a structured ErrorResponse on validation failure."""
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(error="Validation error", detail=str(exc)).model_dump(),
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a structured ErrorResponse on unexpected server error."""
    log.error("api.internal_error", error=str(exc))
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(error="Internal server error", detail=str(exc)).model_dump(),
    )


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("API_HOST", "0.0.0.0"),
        port=int(os.environ.get("API_PORT", "8000")),
    )
