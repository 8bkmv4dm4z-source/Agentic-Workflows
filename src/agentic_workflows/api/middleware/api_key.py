"""API key authentication middleware."""

from __future__ import annotations

import os

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from agentic_workflows.api.models import ErrorResponse


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validate X-API-Key header on all non-health routes.

    Dev passthrough: if API_KEY env var is not set, all requests pass through
    without validation (keeps all existing tests green without changes).
    """

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        api_key = os.environ.get("API_KEY")

        # Dev passthrough — no key configured
        if not api_key:
            return await call_next(request)

        # Health endpoint is always public
        if request.url.path == "/health":
            return await call_next(request)

        # Validate X-API-Key header
        provided_key = request.headers.get("X-API-Key")
        if not provided_key or provided_key != api_key:
            return JSONResponse(
                status_code=401,
                content=ErrorResponse(
                    error="Unauthorized",
                    detail="Missing or invalid X-API-Key header",
                ).model_dump(),
            )

        return await call_next(request)
