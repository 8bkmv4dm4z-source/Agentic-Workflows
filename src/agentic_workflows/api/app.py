"""FastAPI application for Agentic Workflows.

The graph is compiled once at startup via the lifespan context manager.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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
    from agentic_workflows.logger import setup_dual_logging as _setup_logging
    _log_dir = os.environ.get("GSD_LOG_DIR", ".tmp")
    _setup_logging(log_dir=_log_dir)

    log.info("api.startup", status="compiling_graph")

    db_url = os.environ.get("DATABASE_URL")
    pool = None

    if db_url:
        # -- Postgres backend --
        from psycopg_pool import ConnectionPool as PgConnectionPool

        from agentic_workflows.orchestration.langgraph.checkpoint_postgres import (
            PostgresCheckpointStore,
        )
        from agentic_workflows.orchestration.langgraph.memo_postgres import PostgresMemoStore
        from agentic_workflows.storage.postgres import PostgresRunStore

        # Retry opening the pool so startup survives Postgres coming up
        # slightly after uvicorn (common when auto-started locally).
        # Pool must be recreated each attempt — psycopg_pool raises
        # "pool has already been opened/closed" if open() is retried on the same object.
        _pg_retries = int(os.environ.get("PG_CONNECT_RETRIES", "10"))
        _pg_delay = float(os.environ.get("PG_CONNECT_RETRY_DELAY", "2.0"))
        pool = None
        for _attempt in range(1, _pg_retries + 1):
            try:
                pool = PgConnectionPool(
                    conninfo=db_url,
                    min_size=2,
                    max_size=10,
                    open=False,
                    kwargs={"autocommit": True, "prepare_threshold": 0},
                )
                pool.open(wait=True, timeout=10)
                break
            except Exception as _exc:
                if _attempt == _pg_retries:
                    raise RuntimeError(
                        f"Postgres unavailable after {_pg_retries} attempts: {_exc}"
                    ) from _exc
                log.warning(
                    "api.postgres_not_ready",
                    attempt=_attempt,
                    retries=_pg_retries,
                    error=str(_exc),
                )
                import time as _time
                _time.sleep(_pg_delay)

        run_store = PostgresRunStore(pool)
        checkpoint_store = PostgresCheckpointStore(pool)
        memo_store = PostgresMemoStore(pool)
        log.info("api.startup", storage="postgres", pool_max_size=10)
    else:
        # -- SQLite backend (dev/test default) --
        from agentic_workflows.orchestration.langgraph.checkpoint_store import (
            SQLiteCheckpointStore,
        )
        from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore

        run_store = SQLiteRunStore()
        checkpoint_store = SQLiteCheckpointStore()
        memo_store = SQLiteMemoStore()
        log.info("api.startup", storage="sqlite")

    # -- Semantic context layer (Phase 7.3) --
    # Active when DATABASE_URL is set; gracefully disabled (pool=None) otherwise.
    from agentic_workflows.context.embedding_provider import get_embedding_provider
    from agentic_workflows.storage.artifact_store import ArtifactStore
    from agentic_workflows.storage.mission_context_store import MissionContextStore

    embedding_provider = get_embedding_provider()  # reads EMBEDDING_PROVIDER env var
    mission_context_store = MissionContextStore(pool=pool, embedding_provider=embedding_provider)
    artifact_store = ArtifactStore(pool=pool, embedding_provider=embedding_provider)
    application.state.artifact_store = artifact_store
    log.info(
        "api.startup",
        semantic_layer="enabled" if pool is not None else "disabled(sqlite)",
        embedding_provider=type(embedding_provider).__name__,
    )

    orchestrator = LangGraphOrchestrator(
        memo_store=memo_store,
        checkpoint_store=checkpoint_store,
        embedding_provider=embedding_provider,
        mission_context_store=mission_context_store,
        artifact_store=artifact_store,  # NEW — was created above, now forwarded
    )
    application.state.orchestrator = orchestrator
    application.state.run_store = run_store

    application.state.active_streams: dict = {}  # type: ignore[annotation-unchecked]

    # Stream token secret: use API_KEY if set, else generate a random per-startup secret
    application.state.stream_secret = (
        os.environ.get("API_KEY") or secrets.token_hex(32)
    )

    tool_count = len(orchestrator.tools)
    log.info("api.startup", status="graph_compiled", tools=tool_count)

    yield

    if pool is not None:
        pool.close()
    else:
        run_store.close()  # type: ignore[union-attr]
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
