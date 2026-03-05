"""FastAPI application for Agentic Workflows.

The graph is compiled once at startup via the lifespan context manager.
"""

from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from agentic_workflows.api.middleware import APIKeyMiddleware, RequestIDMiddleware
from agentic_workflows.api.models import ErrorResponse
from agentic_workflows.api.routes import health, run, runs, tools
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

    # Stream token secret: use API_KEY if set, else generate a random per-startup secret
    application.state.stream_secret = (
        os.environ.get("API_KEY") or secrets.token_hex(32)
    )

    tool_count = len(orchestrator.tools)
    log.info("api.startup", status="graph_compiled", tools=tool_count)

    yield

    run_store.close()
    log.info("api.shutdown", status="clean")


app = FastAPI(
    title="Agentic Workflows",
    description="Multi-agent orchestration platform with SSE streaming. "
    "Plan-and-execute architecture powered by LangGraph.",
    version="1.0.0",
    lifespan=lifespan,
)

# ----- Middleware (registered outermost-first; Starlette processes in reverse) -----

# 1. CORS — outermost, handles preflight before auth check
_cors_origins_raw = os.environ.get("CORS_ORIGINS", "")
_cors_origins = (
    [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
    if _cors_origins_raw
    else ["http://localhost:3000", "http://localhost:8080"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 2. Body size limit — 1 MB (1_048_576 bytes); returns 413 on exceed
class _BodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > 1_048_576:
            return JSONResponse(
                status_code=413,
                content=ErrorResponse(
                    error="Payload Too Large",
                    detail="Request body exceeds 1MB limit",
                ).model_dump(),
            )
        return await call_next(request)


app.add_middleware(_BodySizeLimitMiddleware)

# 3. Request ID — binds request_id to structlog context
app.add_middleware(RequestIDMiddleware)

# 4. API Key — innermost auth check
app.add_middleware(APIKeyMiddleware)

# ----- Routes -----
app.include_router(health.router)
app.include_router(tools.router)
app.include_router(run.router)
app.include_router(runs.router)


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
